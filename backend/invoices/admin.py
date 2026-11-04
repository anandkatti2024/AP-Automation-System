from django.contrib import admin

from .models import (
    ApprovalNotification,
    AuditEvent,
    InvoiceApprovalRule,
    InvoiceApprovalStep,
    PaymentRequest,
    Vendor,
    VendorOnboardingHistory,
)


@admin.register(InvoiceApprovalRule)
class InvoiceApprovalRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "minimum_amount",
        "maximum_amount",
        "approver_roles",
        "active",
    )
    list_filter = ("active",)
    search_fields = ("name",)


@admin.register(InvoiceApprovalStep)
class InvoiceApprovalStepAdmin(admin.ModelAdmin):
    list_display = ("invoice", "role", "status", "approved_by", "created_at")
    list_filter = ("role", "status")
    readonly_fields = (
        "invoice",
        "role",
        "status",
        "approved_by",
        "approved_at",
        "reminder_after_hours",
        "escalation_after_hours",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "entity_type", "entity_label", "action", "actor_name")
    list_filter = ("entity_type", "action")
    search_fields = ("entity_label", "actor_name")
    readonly_fields = (
        "entity_type",
        "entity_id",
        "entity_label",
        "action",
        "changes",
        "actor",
        "actor_name",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(
    [ApprovalNotification, PaymentRequest, VendorOnboardingHistory]
)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "onboarding_status", "quickbooks_vendor_id")
    search_fields = ("name", "gstin", "quickbooks_vendor_id")
    fields = (
        "name",
        "gstin",
        "tax_id",
        "contact_email",
        "contact_phone",
        "address",
        "onboarding_status",
        "quickbooks_vendor_id",
        "quickbooks_expense_account_id",
        "stripe_connected_account_id",
    )
