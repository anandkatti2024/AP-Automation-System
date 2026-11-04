from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Invoice, InvoicePayment, PaymentRequest
from .audit import record_audit_event
from .permissions import HasInvoiceRole
from .serializers import InvoicePaymentSerializer, PaymentRequestSerializer


class PaymentRequestCreateSerializer(serializers.Serializer):
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all())


class PaymentRequestListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {
        "POST": {"Payment Clerk"},
    }

    def get(self, request):
        requests = PaymentRequest.objects.select_related(
            "invoice",
            "requested_by",
        )
        return Response(PaymentRequestSerializer(requests, many=True).data)

    @transaction.atomic
    def post(self, request):
        serializer = PaymentRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = get_object_or_404(
            Invoice.objects.select_for_update(),
            pk=serializer.validated_data["invoice"].pk,
        )
        if invoice.status != "APPROVED":
            raise serializers.ValidationError(
                {"invoice": "Only approved invoices can have payment requests."}
            )

        paid = invoice.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        outstanding = invoice.total_amount - paid
        if outstanding <= 0:
            raise serializers.ValidationError(
                {"invoice": "This invoice has no outstanding balance."}
            )
        if PaymentRequest.objects.filter(
            invoice=invoice,
            status="REQUESTED",
        ).exists():
            raise serializers.ValidationError(
                {"invoice": "An open payment request already exists for this invoice."}
            )

        user = request.user
        payment_request = PaymentRequest.objects.create(
            invoice=invoice,
            requested_amount=outstanding,
            requested_by=user,
            requested_by_name=user.get_username(),
        )
        record_audit_event(
            actor=user,
            entity_type="PAYMENT",
            entity_id=payment_request.pk,
            entity_label=invoice.invoice_number,
            action="REQUESTED",
            changes={
                "amount": str(outstanding),
                "invoice_id": invoice.pk,
            },
        )
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_201_CREATED,
        )


class InvoicePaymentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    queryset = InvoicePayment.objects.select_related("invoice", "actor")
    serializer_class = InvoicePaymentSerializer


class InvoicePaymentCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"Payment Clerk"}}
    serializer_class = InvoicePaymentSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        self.invoice = get_object_or_404(
            Invoice.objects.select_for_update(),
            pk=kwargs["invoice_id"],
        )
        return super().create(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["invoice"] = self.invoice
        return context

    def perform_create(self, serializer):
        user = self.request.user
        actor = user if user.is_authenticated else None
        actor_name = user.get_username() if actor else "Unauthenticated user"
        payment = serializer.save(
            invoice=self.invoice,
            actor=actor,
            actor_name=actor_name,
        )
        record_audit_event(
            actor=actor,
            entity_type="PAYMENT",
            entity_id=payment.pk,
            entity_label=payment.payment_reference,
            action="RECORDED",
            changes={
                "invoice_id": self.invoice.pk,
                "invoice_number": self.invoice.invoice_number,
                "amount": str(payment.amount),
                "payment_date": payment.payment_date.isoformat(),
                "payment_method": payment.payment_method,
                "payment_reference": payment.payment_reference,
            },
        )
        total_paid = self.invoice.payments.aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")
        if total_paid >= self.invoice.total_amount:
            self.invoice.status = "PAID"
            self.invoice.save(update_fields=["status", "updated_at"])
            record_audit_event(
                actor=actor,
                entity_type="INVOICE",
                entity_id=self.invoice.pk,
                entity_label=self.invoice.invoice_number,
                action="STATUS_CHANGED",
                changes={"status": {"from": "APPROVED", "to": "PAID"}},
            )
        self.invoice.payment_requests.filter(
            status="REQUESTED",
            requested_amount__lte=total_paid,
        ).update(status="PAID")
