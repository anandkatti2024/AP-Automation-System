from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Vendor(models.Model):
    ONBOARDING_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("UNDER_REVIEW", "Under Review"),
        ("ACTIVE", "Active"),
        ("REJECTED", "Rejected"),
    ]

    name = models.CharField(max_length=255)
    gstin = models.CharField(max_length=15, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    bank_account_name = models.CharField(max_length=255, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    bank_ifsc = models.CharField(max_length=11, blank=True)
    quickbooks_vendor_id = models.CharField(max_length=100, blank=True)
    quickbooks_expense_account_id = models.CharField(max_length=100, blank=True)
    stripe_connected_account_id = models.CharField(max_length=100, blank=True)
    onboarding_status = models.CharField(
        max_length=20,
        choices=ONBOARDING_STATUS_CHOICES,
        default="PENDING",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    @property
    def bank_account_last4(self):
        return self.bank_account_number[-4:] if self.bank_account_number else ""


class VendorOnboardingHistory(models.Model):
    ACTION_CHOICES = [
        ("SUBMITTED", "Submitted for review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    vendor = models.ForeignKey(
        Vendor,
        related_name="onboarding_history",
        on_delete=models.CASCADE,
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="vendor_onboarding_actions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.vendor.name}: {self.action}"


class AuditEvent(models.Model):
    ENTITY_CHOICES = [
        ("INVOICE", "Invoice"),
        ("VENDOR", "Vendor"),
        ("PURCHASE_ORDER", "Purchase order"),
        ("GOODS_RECEIPT", "Goods receipt"),
        ("PAYMENT", "Payment"),
    ]

    entity_type = models.CharField(max_length=30, choices=ENTITY_CHOICES)
    entity_id = models.CharField(max_length=64)
    entity_label = models.CharField(max_length=255)
    action = models.CharField(max_length=40)
    changes = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="ap_audit_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.entity_type} {self.entity_label}: {self.action}"


class Invoice(models.Model):
    STATUS_CHOICES = [
        ("UPLOADED", "Uploaded"),
        ("PROCESSING", "Processing"),
        ("PENDING_REVIEW", "Pending Review"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("PAID", "Paid"),
    ]

    invoice_number = models.CharField(max_length=100)
    vendor_name = models.CharField(max_length=255)
    vendor_gst_number = models.CharField(max_length=20, blank=True)

    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )

    currency = models.CharField(max_length=3, default="INR")
    purchase_order = models.ForeignKey(
        "PurchaseOrder",
        related_name="invoices",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    invoice_file = models.FileField(
        upload_to="invoices/", blank=True, null=True
    )
    ocr_text = models.TextField(blank=True)
    ocr_confidence = models.FloatField(null=True, blank=True)
    quickbooks_bill_id = models.CharField(max_length=100, blank=True)
    quickbooks_synced_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="UPLOADED",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.invoice_number} - {self.vendor_name}"

    class Meta:
        ordering = ["-created_at"]


class InvoiceApprovalHistory(models.Model):
    ACTION_CHOICES = [
        ("SUBMITTED", "Submitted for approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    invoice = models.ForeignKey(
        Invoice,
        related_name="approval_history",
        on_delete=models.CASCADE,
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    comment = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="invoice_approval_actions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.action}"


class InvoiceApprovalRule(models.Model):
    name = models.CharField(max_length=100, unique=True)
    minimum_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    approver_roles = models.JSONField(default=list)
    reminder_after_hours = models.PositiveIntegerField(default=24)
    escalation_after_hours = models.PositiveIntegerField(default=72)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["minimum_amount", "name"]

    def clean(self):
        errors = {}
        if self.minimum_amount < 0:
            errors["minimum_amount"] = "Minimum amount cannot be negative."
        if (
            self.maximum_amount is not None
            and self.maximum_amount < self.minimum_amount
        ):
            errors["maximum_amount"] = (
                "Maximum amount must be greater than or equal to minimum amount."
            )
        if not isinstance(self.approver_roles, list) or not self.approver_roles:
            errors["approver_roles"] = "Select at least one approver role."
        else:
            from django.contrib.auth.models import Group

            existing_roles = set(
                Group.objects.filter(name__in=self.approver_roles)
                .values_list("name", flat=True)
            )
            unknown_roles = set(self.approver_roles) - existing_roles
            if unknown_roles:
                errors["approver_roles"] = (
                    "Unknown role group(s): " + ", ".join(sorted(unknown_roles))
                )
        if self.escalation_after_hours < self.reminder_after_hours:
            errors["escalation_after_hours"] = (
                "Escalation must occur after the reminder interval."
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        upper_bound = self.maximum_amount or "and above"
        return f"{self.name}: {self.minimum_amount} to {upper_bound}"


class InvoiceApprovalStep(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    invoice = models.ForeignKey(
        Invoice,
        related_name="approval_steps",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="invoice_approval_steps",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    reminder_after_hours = models.PositiveIntegerField(default=24)
    escalation_after_hours = models.PositiveIntegerField(default=72)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "role"],
                name="unique_invoice_approval_role",
            )
        ]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.role} ({self.status})"


class ApprovalNotification(models.Model):
    NOTIFICATION_TYPES = [
        ("REMINDER", "Approval reminder"),
        ("ESCALATION", "Approval escalation"),
    ]

    approval_step = models.ForeignKey(
        InvoiceApprovalStep,
        related_name="notifications",
        on_delete=models.CASCADE,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="approval_notifications",
        on_delete=models.CASCADE,
    )
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    message = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["approval_step", "recipient", "notification_type"],
                name="unique_approval_notification_per_recipient",
            )
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.recipient}"


class InvoicePayment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ("BANK_TRANSFER", "Bank transfer"),
        ("CHEQUE", "Cheque"),
        ("UPI", "UPI"),
        ("OTHER", "Other"),
    ]

    invoice = models.ForeignKey(
        Invoice,
        related_name="payments",
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_reference = models.CharField(max_length=100, unique=True)
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
    )
    notes = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="invoice_payments_recorded",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    actor_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.payment_reference}"


class PaymentRequest(models.Model):
    STATUS_CHOICES = [
        ("REQUESTED", "Requested"),
        ("PAID", "Paid"),
        ("CANCELLED", "Cancelled"),
    ]

    invoice = models.ForeignKey(
        Invoice,
        related_name="payment_requests",
        on_delete=models.PROTECT,
    )
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="ap_payment_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    requested_by_name = models.CharField(max_length=150)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="REQUESTED",
    )
    stripe_transfer_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.requested_amount} ({self.status})"


class IntegrationCredential(models.Model):
    PROVIDER_CHOICES = [
        ("QUICKBOOKS", "QuickBooks Online"),
    ]

    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, unique=True)
    access_token_encrypted = models.TextField()
    refresh_token_encrypted = models.TextField()
    realm_id = models.CharField(max_length=100)
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider} integration credentials"


class ImportedEmail(models.Model):
    mailbox = models.CharField(max_length=255)
    uid_validity = models.CharField(max_length=100, default="")
    uid = models.CharField(max_length=255)
    message_id = models.CharField(max_length=255, blank=True)
    invoice_ids = models.JSONField(default=list, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mailbox", "uid_validity", "uid"],
                name="unique_imported_email_uid",
            )
        ]
        ordering = ["-processed_at"]

    def __str__(self):
        return f"{self.mailbox}: {self.uid}"


class InvoiceLineItem(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        related_name="line_items",
        on_delete=models.CASCADE,
    )
    line_number = models.PositiveIntegerField()
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["line_number", "id"]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.description}"


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("CLOSED", "Closed"),
        ("CANCELLED", "Cancelled"),
    ]

    po_number = models.CharField(max_length=100, unique=True)
    vendor = models.ForeignKey(
        Vendor,
        related_name="purchase_orders",
        on_delete=models.PROTECT,
    )
    currency = models.CharField(max_length=3, default="INR")
    order_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="OPEN",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.po_number

    @property
    def total_amount(self):
        return sum(
            (line.line_total for line in self.line_items.all()),
            Decimal("0.00"),
        )


class PurchaseOrderLineItem(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        related_name="line_items",
        on_delete=models.CASCADE,
    )
    line_number = models.PositiveIntegerField()
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["line_number", "id"]

    def __str__(self):
        return f"{self.purchase_order.po_number}: {self.description}"


class GoodsReceipt(models.Model):
    receipt_number = models.CharField(max_length=100, unique=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        related_name="goods_receipts",
        on_delete=models.PROTECT,
    )
    receipt_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-receipt_date", "-created_at"]

    def __str__(self):
        return self.receipt_number


class GoodsReceiptLineItem(models.Model):
    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        related_name="line_items",
        on_delete=models.CASCADE,
    )
    purchase_order_line = models.ForeignKey(
        PurchaseOrderLineItem,
        related_name="receipt_lines",
        on_delete=models.PROTECT,
    )
    quantity_received = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["purchase_order_line__line_number", "id"]

    def __str__(self):
        return (
            f"{self.goods_receipt.receipt_number}: "
            f"{self.purchase_order_line.description}"
        )
