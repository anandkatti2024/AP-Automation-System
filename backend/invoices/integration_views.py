import hmac
import secrets
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import record_audit_event
from .integrations import (
    ExternalIntegrationError,
    IntegrationConfigurationError,
    create_quickbooks_draft_bill,
    create_stripe_connect_transfer,
    exchange_quickbooks_code,
    quickbooks_authorization_url,
)
from .models import (
    Invoice,
    InvoicePayment,
    PaymentRequest,
)
from .permissions import HasInvoiceRole
from .serializers import InvoicePaymentSerializer, InvoiceSerializer
from .validation import find_vendor_for_invoice


class QuickBooksAuthorizeView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"GET": {"Administrator"}}

    def get(self, request):
        state = secrets.token_urlsafe(32)
        request.session["quickbooks_oauth_state"] = state
        try:
            url = quickbooks_authorization_url(state)
        except IntegrationConfigurationError as error:
            raise ValidationError({"quickbooks": str(error)}) from error
        return Response({"authorization_url": url})


class QuickBooksOAuthCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @staticmethod
    def _frontend_result(result, detail=""):
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        query = {"integration": f"quickbooks-{result}"}
        if detail:
            query["detail"] = detail
        return HttpResponseRedirect(f"{frontend_url}/?{urlencode(query)}")

    def get(self, request):
        expected_state = request.session.pop("quickbooks_oauth_state", "")
        received_state = request.query_params.get("state", "")
        if not expected_state or not hmac.compare_digest(
            expected_state,
            received_state,
        ):
            return self._frontend_result(
                "error",
                "Authorization state did not match. Start the connection again.",
            )
        if request.query_params.get("error"):
            return self._frontend_result("error", "Authorization was cancelled.")
        code = request.query_params.get("code")
        realm_id = request.query_params.get("realmId")
        if not code or not realm_id:
            return self._frontend_result(
                "error",
                "QuickBooks did not return an authorization code and company ID.",
            )
        try:
            exchange_quickbooks_code(code, realm_id)
        except (IntegrationConfigurationError, ExternalIntegrationError) as error:
            return self._frontend_result("error", str(error))
        return self._frontend_result("connected")


class QuickBooksDraftBillView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"Payment Clerk"}}

    @transaction.atomic
    def post(self, request, pk):
        invoice = get_object_or_404(
            Invoice.objects.select_for_update().prefetch_related("line_items"),
            pk=pk,
        )
        if invoice.quickbooks_bill_id:
            return Response(
                InvoiceSerializer(
                    invoice,
                    context={"request": request},
                ).data
            )
        if invoice.status != "APPROVED":
            raise ValidationError({
                "invoice": "Only approved invoices can be synced to QuickBooks."
            })

        vendor = find_vendor_for_invoice(invoice)
        if not vendor or vendor.onboarding_status != "ACTIVE":
            raise ValidationError({
                "vendor": "An active matching vendor is required for QuickBooks sync."
            })
        try:
            bill_id = create_quickbooks_draft_bill(invoice, vendor)
        except IntegrationConfigurationError as error:
            raise ValidationError({"quickbooks": str(error)}) from error
        except ExternalIntegrationError as error:
            return Response(
                {"quickbooks": str(error)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        invoice.quickbooks_bill_id = bill_id
        invoice.quickbooks_synced_at = timezone.now()
        invoice.save(
            update_fields=["quickbooks_bill_id", "quickbooks_synced_at", "updated_at"]
        )
        record_audit_event(
            actor=request.user,
            entity_type="INVOICE",
            entity_id=invoice.pk,
            entity_label=invoice.invoice_number,
            action="QUICKBOOKS_DRAFT_CREATED",
            changes={"quickbooks_bill_id": bill_id},
        )
        return Response(
            InvoiceSerializer(
                invoice,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class StripeTransferConfirmationSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                "Explicit confirmation is required to initiate a Stripe transfer."
            )
        return value


class StripeConnectTransferView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"Payment Clerk"}}

    @transaction.atomic
    def post(self, request, pk):
        confirmation = StripeTransferConfirmationSerializer(data=request.data)
        confirmation.is_valid(raise_exception=True)
        payment_request = get_object_or_404(
            PaymentRequest.objects.select_for_update().select_related(
                "invoice",
            ),
            pk=pk,
        )
        invoice = Invoice.objects.select_for_update().get(
            pk=payment_request.invoice_id
        )
        if payment_request.stripe_transfer_id:
            payment = InvoicePayment.objects.get(
                payment_reference=f"STRIPE-{payment_request.stripe_transfer_id}"
            )
            return Response(InvoicePaymentSerializer(payment).data)
        if payment_request.status != "REQUESTED":
            raise ValidationError({
                "payment_request": "Only an open payment request can be paid."
            })
        if invoice.status != "APPROVED":
            raise ValidationError({
                "invoice": "Only approved invoices can be paid."
            })

        vendor = find_vendor_for_invoice(invoice)
        if not vendor or vendor.onboarding_status != "ACTIVE":
            raise ValidationError({
                "vendor": "An active matching vendor is required for a Stripe transfer."
            })

        paid = invoice.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        outstanding = invoice.total_amount - paid
        if payment_request.requested_amount > outstanding:
            raise ValidationError({
                "payment_request": (
                    "The requested amount exceeds the invoice's current outstanding balance."
                )
            })

        try:
            transfer_id = create_stripe_connect_transfer(
                invoice,
                vendor,
                payment_request,
            )
        except IntegrationConfigurationError as error:
            raise ValidationError({"stripe": str(error)}) from error
        except ExternalIntegrationError as error:
            return Response(
                {"stripe": str(error)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        user = request.user
        payment = InvoicePayment.objects.create(
            invoice=invoice,
            amount=payment_request.requested_amount,
            payment_date=timezone.localdate(),
            payment_reference=f"STRIPE-{transfer_id}",
            payment_method="BANK_TRANSFER",
            notes=f"Stripe Connect transfer {transfer_id}",
            actor=user,
            actor_name=user.get_username(),
        )
        payment_request.status = "PAID"
        payment_request.stripe_transfer_id = transfer_id
        payment_request.save(
            update_fields=["status", "stripe_transfer_id", "updated_at"]
        )
        record_audit_event(
            actor=user,
            entity_type="PAYMENT",
            entity_id=payment.pk,
            entity_label=payment.payment_reference,
            action="STRIPE_CONNECT_TRANSFER_CREATED",
            changes={
                "invoice_id": invoice.pk,
                "amount": str(payment.amount),
                "currency": invoice.currency,
                "stripe_transfer_id": transfer_id,
            },
        )

        total_paid = invoice.payments.aggregate(total=Sum("amount"))["total"]
        if total_paid >= invoice.total_amount:
            previous_status = invoice.status
            invoice.status = "PAID"
            invoice.save(update_fields=["status", "updated_at"])
            record_audit_event(
                actor=user,
                entity_type="INVOICE",
                entity_id=invoice.pk,
                entity_label=invoice.invoice_number,
                action="STATUS_CHANGED",
                changes={"status": {"from": previous_status, "to": "PAID"}},
            )
        return Response(
            InvoicePaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )
