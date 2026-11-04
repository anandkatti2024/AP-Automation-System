from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Vendor, VendorOnboardingHistory
from .audit import changed_fields, record_audit_event, snapshot
from .permissions import HasInvoiceRole
from .vendor_serializers import VendorSerializer


class VendorOnboardingActionSerializer(serializers.Serializer):
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )


class VendorListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"AP Clerk"}}
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer

    def perform_create(self, serializer):
        vendor = serializer.save()
        fields = [
            "name",
            "gstin",
            "tax_id",
            "contact_email",
            "contact_phone",
            "onboarding_status",
            "bank_account_last4",
        ]
        record_audit_event(
            actor=self.request.user,
            entity_type="VENDOR",
            entity_id=vendor.pk,
            entity_label=vendor.name,
            action="CREATED",
            changes=snapshot(vendor, fields),
        )


class VendorDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {
        "PUT": {"AP Clerk"},
        "PATCH": {"AP Clerk"},
        "DELETE": {"AP Clerk"},
    }
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer

    def perform_update(self, serializer):
        fields = [
            "name",
            "gstin",
            "tax_id",
            "contact_email",
            "contact_phone",
            "onboarding_status",
            "bank_account_last4",
        ]
        before = snapshot(serializer.instance, fields)
        vendor = serializer.save()
        changes = changed_fields(before, snapshot(vendor, fields))
        if changes:
            record_audit_event(
                actor=self.request.user,
                entity_type="VENDOR",
                entity_id=vendor.pk,
                entity_label=vendor.name,
                action="UPDATED",
                changes=changes,
            )

    def perform_destroy(self, instance):
        record_audit_event(
            actor=self.request.user,
            entity_type="VENDOR",
            entity_id=instance.pk,
            entity_label=instance.name,
            action="DELETED",
            changes=snapshot(
                instance,
                ["name", "gstin", "onboarding_status"],
            ),
        )
        instance.delete()


class VendorOnboardingActionView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {}
    action = None

    @transaction.atomic
    def post(self, request, pk):
        serializer = VendorOnboardingActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get("comment", "").strip()
        vendor = get_object_or_404(Vendor.objects.select_for_update(), pk=pk)

        allowed_statuses = {
            "SUBMITTED": {"PENDING", "REJECTED"},
            "APPROVED": {"UNDER_REVIEW"},
            "REJECTED": {"UNDER_REVIEW"},
        }
        if vendor.onboarding_status not in allowed_statuses[self.action]:
            raise ValidationError({
                "onboarding_status": (
                    f"Cannot perform {self.action.lower()} while vendor "
                    f"status is {vendor.onboarding_status}."
                )
            })

        if self.action == "REJECTED" and not comment:
            raise ValidationError({
                "comment": "A reason is required when rejecting a vendor."
            })

        previous_status = vendor.onboarding_status
        next_status = {
            "SUBMITTED": "UNDER_REVIEW",
            "APPROVED": "ACTIVE",
            "REJECTED": "REJECTED",
        }[self.action]
        vendor.onboarding_status = next_status
        vendor.save(update_fields=["onboarding_status", "updated_at"])

        user = request.user
        VendorOnboardingHistory.objects.create(
            vendor=vendor,
            action=self.action,
            comment=comment,
            actor=user,
            actor_name=user.get_username(),
        )
        record_audit_event(
            actor=user,
            entity_type="VENDOR",
            entity_id=vendor.pk,
            entity_label=vendor.name,
            action=f"ONBOARDING_{self.action}",
            changes={
                "onboarding_status": {
                    "from": previous_status,
                    "to": next_status,
                },
                "comment": comment,
            },
        )
        return Response(VendorSerializer(vendor).data, status=status.HTTP_200_OK)


class SubmitVendorForReviewView(VendorOnboardingActionView):
    action = "SUBMITTED"
    required_roles_by_method = {"POST": {"AP Clerk"}}


class ApproveVendorView(VendorOnboardingActionView):
    action = "APPROVED"
    required_roles_by_method = {"POST": {"Approver"}}


class RejectVendorView(VendorOnboardingActionView):
    action = "REJECTED"
    required_roles_by_method = {"POST": {"Approver"}}
