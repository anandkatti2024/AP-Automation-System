
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import (
    Invoice,
    AuditEvent,
    ApprovalNotification,
    InvoiceApprovalStep,
    InvoiceLineItem,
    GoodsReceipt,
    GoodsReceiptLineItem,
    InvoiceApprovalHistory,
    InvoiceApprovalRule,
    InvoicePayment,
    PaymentRequest,
    PurchaseOrder,
    PurchaseOrderLineItem,
    Vendor,
)
from .matching import (
    compare_invoice_to_purchase_order,
    compare_invoice_to_purchase_order_and_receipts,
)
from .validation import (
    GSTIN_PATTERN,
    find_vendor_for_invoice,
    has_duplicate_invoice,
)


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "entity_type",
            "entity_id",
            "entity_label",
            "action",
            "changes",
            "actor_name",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceApprovalStepSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(
        source="approved_by.username",
        read_only=True,
        default="",
    )

    class Meta:
        model = InvoiceApprovalStep
        fields = [
            "id",
            "role",
            "status",
            "approved_by_name",
            "approved_at",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceApprovalRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceApprovalRule
        fields = [
            "id",
            "name",
            "minimum_amount",
            "maximum_amount",
            "approver_roles",
            "reminder_after_hours",
            "escalation_after_hours",
            "active",
        ]
        read_only_fields = fields


class ApprovalNotificationSerializer(serializers.ModelSerializer):
    invoice_id = serializers.IntegerField(
        source="approval_step.invoice_id",
        read_only=True,
    )
    invoice_number = serializers.CharField(
        source="approval_step.invoice.invoice_number",
        read_only=True,
    )

    class Meta:
        model = ApprovalNotification
        fields = [
            "id",
            "invoice_id",
            "invoice_number",
            "notification_type",
            "message",
            "created_at",
            "read_at",
        ]
        read_only_fields = fields


class PaymentRequestSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
    )
    vendor_name = serializers.CharField(source="invoice.vendor_name", read_only=True)
    currency = serializers.CharField(source="invoice.currency", read_only=True)

    class Meta:
        model = PaymentRequest
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "vendor_name",
            "currency",
            "requested_amount",
            "requested_by_name",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    validation_errors = serializers.SerializerMethodField()
    validation_status = serializers.SerializerMethodField()
    line_items = serializers.SerializerMethodField()
    vendor_master_id = serializers.SerializerMethodField()
    purchase_order = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseOrder.objects.all(),
        required=False,
        allow_null=True,
    )
    two_way_match = serializers.SerializerMethodField()
    three_way_match = serializers.SerializerMethodField()
    approval_history = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    approval_steps = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "vendor_name",
            "vendor_master_id",
            "vendor_gst_number",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax_amount",
            "total_amount",
            "currency",
            "invoice_file",
            "ocr_text",
            "ocr_confidence",
            "quickbooks_bill_id",
            "quickbooks_synced_at",
            "line_items",
            "purchase_order",
            "two_way_match",
            "three_way_match",
            "approval_history",
            "approval_steps",
            "payments",
            "status",
            "created_at",
            "updated_at",
            "validation_errors",
            "validation_status",
        ]
        read_only_fields = [
            "id",
            "ocr_text",
            "ocr_confidence",
            "quickbooks_bill_id",
            "quickbooks_synced_at",
            "line_items",
            "two_way_match",
            "three_way_match",
            "approval_history",
            "approval_steps",
            "payments",
            "status",
            "created_at",
            "updated_at",
            "validation_errors",
            "validation_status",
        ]

    def get_line_items(self, invoice):
        return InvoiceLineItemSerializer(
            invoice.line_items.all(),
            many=True,
        ).data

    def get_vendor_master_id(self, invoice):
        vendor = find_vendor_for_invoice(invoice)
        return vendor.pk if vendor else None

    def get_two_way_match(self, invoice):
        if not invoice.purchase_order_id:
            return {"status": "NOT_LINKED", "discrepancies": []}
        return compare_invoice_to_purchase_order(
            invoice,
            invoice.purchase_order,
        )

    def get_three_way_match(self, invoice):
        if not invoice.purchase_order_id:
            return {"status": "NOT_LINKED", "discrepancies": []}
        return compare_invoice_to_purchase_order_and_receipts(
            invoice,
            invoice.purchase_order,
        )

    def get_approval_history(self, invoice):
        return InvoiceApprovalHistorySerializer(
            invoice.approval_history.select_related("actor").all(),
            many=True,
        ).data

    def get_approval_steps(self, invoice):
        return InvoiceApprovalStepSerializer(
            invoice.approval_steps.select_related("approved_by").all(),
            many=True,
        ).data

    def get_payments(self, invoice):
        return InvoicePaymentSerializer(
            invoice.payments.select_related("actor").all(),
            many=True,
        ).data

    def validate(self, attrs):
        if self.instance and self.instance.status in {
            "PENDING_APPROVAL",
            "APPROVED",
            "PAID",
        } and attrs:
            raise serializers.ValidationError(
                "Invoice details cannot be changed while approval is pending "
                "or after the invoice is approved."
            )
        return attrs

    def to_internal_value(self, data):
        if self.instance and "status" in data:
            raise serializers.ValidationError({
                "status": "Use the invoice approval actions to change status."
            })
        return super().to_internal_value(data)

    def validate_purchase_order(self, purchase_order):
        if purchase_order is None or not self.instance:
            return purchase_order

        if purchase_order.status != "OPEN":
            raise serializers.ValidationError(
                "Only open purchase orders can be linked to an invoice."
            )

        invoice_vendor = find_vendor_for_invoice(self.instance)
        if (
            invoice_vendor is None
            or invoice_vendor.pk != purchase_order.vendor_id
        ):
            raise serializers.ValidationError(
                "The purchase order vendor must match the invoice vendor."
            )
        return purchase_order

    def get_validation_errors(self, invoice):
        errors = []

        # 1. Check mandatory invoice fields.
        if not invoice.invoice_number or invoice.invoice_number.startswith(
            "UPLOAD-"
        ):
            errors.append("Invoice number is missing.")

        if (
            not invoice.vendor_name
            or invoice.vendor_name.lower() == "pending extraction"
        ):
            errors.append("Vendor name is missing.")

        if not invoice.invoice_date:
            errors.append("Invoice date is missing.")

        if not invoice.total_amount or invoice.total_amount <= 0:
            errors.append("Total amount is missing or invalid.")

        # 2. Check whether subtotal + tax equals total.
        subtotal = invoice.subtotal or Decimal("0.00")
        tax = invoice.tax_amount or Decimal("0.00")
        total = invoice.total_amount or Decimal("0.00")

        calculated_total = subtotal + tax

        if abs(calculated_total - total) > Decimal("0.01"):
            errors.append(
                "Amount mismatch: subtotal plus tax does not equal total."
            )

        # 3. Check for duplicate invoice numbers from the same vendor.
        if has_duplicate_invoice(invoice):
            errors.append(
                "Possible duplicate: this vendor has an invoice "
                "with the same invoice number."
            )

        if invoice.purchase_order_id:
            match = compare_invoice_to_purchase_order_and_receipts(
                invoice,
                invoice.purchase_order,
            )
            for discrepancy in match["discrepancies"]:
                if discrepancy["message"] not in errors:
                    errors.append(discrepancy["message"])

        if (
            invoice.vendor_gst_number
            and not GSTIN_PATTERN.fullmatch(
                invoice.vendor_gst_number.strip().upper()
            )
        ):
            errors.append(
                "Vendor GST number does not match the 15-character "
                "Indian GSTIN format."
            )

        vendor = find_vendor_for_invoice(invoice)
        if vendor is None:
            errors.append("Vendor is not registered in the vendor master.")
        elif vendor.onboarding_status != "ACTIVE":
            errors.append(
                "Vendor onboarding is not complete. Verify this vendor "
                "before proceeding."
            )

        # 4. Check due date.
        if (
            invoice.invoice_date
            and invoice.due_date
            and invoice.due_date < invoice.invoice_date
        ):
            errors.append(
                "Due date cannot be earlier than the invoice date."
            )

        # 5. Check OCR confidence.
        if (
            invoice.ocr_confidence is not None
            and invoice.ocr_confidence < 70
        ):
            errors.append(
                "OCR confidence is low. Please verify extracted fields."
            )

        return errors

    def get_validation_status(self, invoice):
        errors = self.get_validation_errors(invoice)

        return "VALID" if not errors else "NEEDS_REVIEW"


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = [
            "id",
            "line_number",
            "description",
            "quantity",
            "unit_price",
            "line_total",
        ]
        read_only_fields = fields


class InvoiceApprovalHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceApprovalHistory
        fields = ["id", "action", "comment", "actor_name", "created_at"]
        read_only_fields = fields


class InvoicePaymentSerializer(serializers.ModelSerializer):
    invoice = serializers.PrimaryKeyRelatedField(read_only=True)
    invoice_number = serializers.CharField(
        source="invoice.invoice_number",
        read_only=True,
    )
    vendor_name = serializers.CharField(
        source="invoice.vendor_name",
        read_only=True,
    )
    currency = serializers.CharField(source="invoice.currency", read_only=True)
    actor_name = serializers.CharField(read_only=True)

    class Meta:
        model = InvoicePayment
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "vendor_name",
            "amount",
            "currency",
            "payment_date",
            "payment_reference",
            "payment_method",
            "notes",
            "actor_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "invoice_number",
            "vendor_name",
            "currency",
            "actor_name",
            "created_at",
        ]

    def validate_amount(self, amount):
        if amount <= 0:
            raise serializers.ValidationError(
                "Payment amount must be greater than zero."
            )
        return amount

    def validate_payment_date(self, payment_date):
        if payment_date > timezone.localdate():
            raise serializers.ValidationError(
                "Payment date cannot be in the future."
            )
        return payment_date

    def validate(self, attrs):
        invoice = self.context["invoice"]
        if invoice.status != "APPROVED":
            raise serializers.ValidationError({
                "invoice": "Only approved, unpaid invoices can be paid."
            })

        previous_payments = invoice.payments.aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")
        new_total = previous_payments + attrs.get("amount", Decimal("0.00"))
        if new_total > invoice.total_amount:
            raise serializers.ValidationError({
                "amount": (
                    f"Payment would exceed the outstanding amount of "
                    f"{invoice.total_amount - previous_payments} "
                    f"{invoice.currency}."
                )
            })
        return attrs


class PurchaseOrderLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            "id",
            "line_number",
            "description",
            "quantity",
            "unit_price",
            "line_total",
        ]
        read_only_fields = ["id"]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Quantity must be greater than zero."
            )
        return value

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Unit price cannot be negative."
            )
        return value

    def validate_line_total(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Line total cannot be negative."
            )
        return value


class PurchaseOrderSerializer(serializers.ModelSerializer):
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all())
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    line_items = PurchaseOrderLineItemSerializer(many=True)
    total_amount = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "po_number",
            "vendor",
            "vendor_name",
            "currency",
            "order_date",
            "status",
            "line_items",
            "total_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_total_amount(self, purchase_order):
        return purchase_order.total_amount

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "A purchase order must have at least one line item."
            )

        if any(not line["description"].strip() for line in value):
            raise serializers.ValidationError(
                "Every line item needs a description."
            )

        for line in value:
            expected_total = (
                line["quantity"] * line["unit_price"]
            ).quantize(Decimal("0.01"))
            if abs(line["line_total"] - expected_total) > Decimal("0.01"):
                raise serializers.ValidationError(
                    "Each line total must equal quantity multiplied by "
                    "unit price (within one cent)."
                )

        return value

    def validate(self, attrs):
        vendor = attrs.get("vendor")
        if vendor and vendor.onboarding_status != "ACTIVE":
            raise serializers.ValidationError({
                "vendor": "Only active vendors can be used on a purchase order."
            })
        return attrs

    def create(self, validated_data):
        line_items = validated_data.pop("line_items")
        purchase_order = PurchaseOrder.objects.create(**validated_data)
        PurchaseOrderLineItem.objects.bulk_create(
            [
                PurchaseOrderLineItem(
                    purchase_order=purchase_order,
                    **line_item,
                )
                for line_item in line_items
            ]
        )
        return purchase_order


class GoodsReceiptLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceiptLineItem
        fields = [
            "id",
            "purchase_order_line",
            "description",
            "quantity_ordered",
            "quantity_received",
        ]
        read_only_fields = ["id", "description", "quantity_ordered"]

    description = serializers.CharField(
        source="purchase_order_line.description",
        read_only=True,
    )
    quantity_ordered = serializers.DecimalField(
        source="purchase_order_line.quantity",
        max_digits=12,
        decimal_places=3,
        read_only=True,
    )

    def validate_quantity_received(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Received quantity must be greater than zero."
            )
        return value

class GoodsReceiptSerializer(serializers.ModelSerializer):
    line_items = GoodsReceiptLineItemSerializer(many=True)
    purchase_order_number = serializers.CharField(
        source="purchase_order.po_number",
        read_only=True,
    )

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "receipt_number",
            "purchase_order",
            "purchase_order_number",
            "receipt_date",
            "line_items",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "A goods receipt must include at least one received line."
            )

        line_ids = [line["purchase_order_line"].id for line in value]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError(
                "A PO line can appear only once in a goods receipt."
            )
        return value

    def validate(self, attrs):
        purchase_order = attrs.get("purchase_order")
        lines = attrs.get("line_items", [])
        if purchase_order and any(
            line["purchase_order_line"].purchase_order_id != purchase_order.id
            for line in lines
        ):
            raise serializers.ValidationError({
                "line_items": (
                    "Every received line must belong to the selected "
                    "purchase order."
                )
            })

        if purchase_order and purchase_order.status != "OPEN":
            raise serializers.ValidationError({
                "purchase_order": (
                    "Goods can only be received against an open purchase order."
                )
            })
        return attrs

    def create(self, validated_data):
        line_items = validated_data.pop("line_items")
        receipt = GoodsReceipt.objects.create(**validated_data)
        GoodsReceiptLineItem.objects.bulk_create(
            [
                GoodsReceiptLineItem(goods_receipt=receipt, **line)
                for line in line_items
            ]
        )
        return receipt
