from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .matching import compare_invoice_to_purchase_order_and_receipts
from .models import (
    Invoice,
    InvoiceApprovalHistory,
    InvoiceApprovalStep,
)
from .audit import record_audit_event
from .approval import approval_requirements_for_invoice
from .permissions import HasInvoiceRole
from .serializers import InvoiceSerializer


class ApprovalActionSerializer(serializers.Serializer):
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )


class InvoiceApprovalActionView(APIView):
    action = None
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {}

    @transaction.atomic
    def post(self, request, pk):
        comment_serializer = ApprovalActionSerializer(data=request.data)
        comment_serializer.is_valid(raise_exception=True)
        comment = comment_serializer.validated_data.get("comment", "").strip()

        invoice = get_object_or_404(
            Invoice.objects.select_for_update(of=("self",)).select_related(
                "purchase_order",
            ).prefetch_related(
                "line_items",
                "purchase_order__line_items",
                "purchase_order__goods_receipts__line_items",
            ),
            pk=pk,
        )

        allowed_statuses = {
            "SUBMITTED": {"UPLOADED", "PENDING_REVIEW", "REJECTED"},
            "APPROVED": {"PENDING_APPROVAL"},
            "REJECTED": {"PENDING_APPROVAL"},
        }
        if invoice.status not in allowed_statuses[self.action]:
            raise ValidationError({
                "status": (
                    f"Cannot perform {self.action.lower()} while invoice "
                    f"status is {invoice.status}."
                )
            })

        if self.action == "REJECTED" and not comment:
            raise ValidationError({
                "comment": "A reason is required when rejecting an invoice."
            })

        if self.action in {"APPROVED", "REJECTED"}:
            steps = list(invoice.approval_steps.all())
            pending_steps = [step for step in steps if step.status == "PENDING"]
            user_roles = set(
                request.user.groups.values_list("name", flat=True)
            )
            administrator = (
                request.user.is_superuser or "Administrator" in user_roles
            )
            matching_steps = [
                step for step in pending_steps
                if administrator or step.role in user_roles
            ]
            if not matching_steps:
                raise PermissionDenied({
                    "approval": (
                        "No pending approval step is assigned to one of your roles."
                    )
                })
        else:
            pending_steps = []
            matching_steps = []

        if self.action in {"SUBMITTED", "APPROVED"}:
            validation_errors = InvoiceSerializer(
                invoice
            ).get_validation_errors(invoice)
            if validation_errors:
                raise ValidationError({
                    "validation_errors": validation_errors,
                })

            if not invoice.purchase_order_id:
                raise ValidationError({
                    "three_way_match": (
                        "Link a purchase order and record its goods receipt "
                        "before submitting this invoice for approval."
                    )
                })

            three_way_match = compare_invoice_to_purchase_order_and_receipts(
                invoice,
                invoice.purchase_order,
            )
            if three_way_match["status"] != "THREE_WAY_MATCHED":
                raise ValidationError({
                    "three_way_match": three_way_match["discrepancies"],
                })

        previous_status = invoice.status
        next_status = {
            "SUBMITTED": "PENDING_APPROVAL",
            "APPROVED": "APPROVED",
            "REJECTED": "REJECTED",
        }[self.action]

        actor = request.user if request.user.is_authenticated else None
        actor_name = actor.get_username() if actor else "Unauthenticated user"
        if self.action == "SUBMITTED":
            requirements = approval_requirements_for_invoice(invoice)
            InvoiceApprovalStep.objects.bulk_create(
                [
                    InvoiceApprovalStep(
                        invoice=invoice,
                        role=role,
                        reminder_after_hours=requirements["reminder_after_hours"],
                        escalation_after_hours=requirements["escalation_after_hours"],
                    )
                    for role in requirements["roles"]
                ]
            )
            invoice.status = next_status
            invoice.save(update_fields=["status", "updated_at"])
        elif self.action == "APPROVED":
            for step in matching_steps:
                step.status = "APPROVED"
                step.approved_by = actor
                step.approved_at = timezone.now()
                step.save(
                    update_fields=["status", "approved_by", "approved_at"]
                )
                InvoiceApprovalHistory.objects.create(
                    invoice=invoice,
                    action="APPROVED",
                    comment=comment,
                    actor=actor,
                    actor_name=actor_name,
                )
            if not invoice.approval_steps.filter(status="PENDING").exists():
                invoice.status = next_status
                invoice.save(update_fields=["status", "updated_at"])
        else:
            for step in matching_steps:
                step.status = "REJECTED"
                step.approved_by = actor
                step.approved_at = timezone.now()
                step.save(
                    update_fields=["status", "approved_by", "approved_at"]
                )
            invoice.approval_steps.filter(status="PENDING").update(
                status="REJECTED"
            )
            invoice.status = next_status
            invoice.save(update_fields=["status", "updated_at"])

        InvoiceApprovalHistory.objects.create(
            invoice=invoice,
            action="SUBMITTED" if self.action == "SUBMITTED" else self.action,
            comment=comment,
            actor=actor,
            actor_name=actor_name,
        )
        record_audit_event(
            actor=actor,
            entity_type="INVOICE",
            entity_id=invoice.pk,
            entity_label=invoice.invoice_number,
            action=f"APPROVAL_{self.action}",
            changes={
                "status": {
                    "from": previous_status,
                    "to": invoice.status,
                },
                "comment": comment,
                "approval_roles": (
                    [step.role for step in matching_steps]
                    if self.action in {"APPROVED", "REJECTED"}
                    else [
                        step.role
                        for step in invoice.approval_steps.all()
                    ]
                ),
            },
        )

        return Response(
            InvoiceSerializer(
                invoice,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_200_OK,
        )

    def get_serializer_context(self):
        return {"request": self.request, "view": self, "format": None}


class SubmitInvoiceForApprovalView(InvoiceApprovalActionView):
    action = "SUBMITTED"
    required_roles_by_method = {"POST": {"AP Clerk"}}


class ApproveInvoiceView(InvoiceApprovalActionView):
    action = "APPROVED"
    required_roles_by_method = {}


class RejectInvoiceView(InvoiceApprovalActionView):
    action = "REJECTED"
    required_roles_by_method = {}
