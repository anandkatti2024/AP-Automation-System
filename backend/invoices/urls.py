from django.urls import path
from .views import (
    ApprovalNotificationListView,
    ApprovalNotificationReadView,
    AuditEventListView,
    EmailInvoiceImportView,
    InvoiceListCreateView,
    InvoiceDetailView,
)
from .vendor_views import (
    ApproveVendorView,
    RejectVendorView,
    SubmitVendorForReviewView,
    VendorListCreateView,
    VendorDetailView,
)
from .purchase_order_views import PurchaseOrderListCreateView
from .goods_receipt_views import GoodsReceiptListCreateView
from .approval_views import (
    ApproveInvoiceView,
    RejectInvoiceView,
    SubmitInvoiceForApprovalView,
)
from .payment_views import (
    InvoicePaymentCreateView,
    InvoicePaymentListView,
    PaymentRequestListCreateView,
)
from .integration_views import (
    QuickBooksAuthorizeView,
    QuickBooksDraftBillView,
    QuickBooksOAuthCallbackView,
    StripeConnectTransferView,
)

urlpatterns = [
    path(
        "integrations/quickbooks/authorize/",
        QuickBooksAuthorizeView.as_view(),
        name="quickbooks-authorize",
    ),
    path(
        "integrations/quickbooks/callback/",
        QuickBooksOAuthCallbackView.as_view(),
        name="quickbooks-callback",
    ),
    path(
        "<int:pk>/quickbooks-sync/",
        QuickBooksDraftBillView.as_view(),
        name="quickbooks-draft-bill",
    ),
    path(
        "payment-requests/<int:pk>/stripe-transfer/",
        StripeConnectTransferView.as_view(),
        name="stripe-connect-transfer",
    ),
    path(
        "email-import/",
        EmailInvoiceImportView.as_view(),
        name="email-invoice-import",
    ),
    path(
        "approval-notifications/",
        ApprovalNotificationListView.as_view(),
        name="approval-notification-list",
    ),
    path(
        "approval-notifications/<int:pk>/read/",
        ApprovalNotificationReadView.as_view(),
        name="approval-notification-read",
    ),
    path("audit-events/", AuditEventListView.as_view(), name="audit-event-list"),
    path("", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path("<int:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    path(
        "<int:pk>/submit-for-approval/",
        SubmitInvoiceForApprovalView.as_view(),
        name="invoice-submit-for-approval",
    ),
    path(
        "<int:pk>/approve/",
        ApproveInvoiceView.as_view(),
        name="invoice-approve",
    ),
    path(
        "<int:pk>/reject/",
        RejectInvoiceView.as_view(),
        name="invoice-reject",
    ),
    path(
        "payments/",
        InvoicePaymentListView.as_view(),
        name="invoice-payment-list",
    ),
    path(
        "payment-requests/",
        PaymentRequestListCreateView.as_view(),
        name="payment-request-list-create",
    ),
    path(
        "<int:invoice_id>/payments/",
        InvoicePaymentCreateView.as_view(),
        name="invoice-payment-create",
    ),
    path("vendors/", VendorListCreateView.as_view(), name="vendor-list-create"),
    path(
        "vendors/<int:pk>/",
        VendorDetailView.as_view(),
        name="vendor-detail",
    ),
    path(
        "vendors/<int:pk>/submit-for-review/",
        SubmitVendorForReviewView.as_view(),
        name="vendor-submit-for-review",
    ),
    path(
        "vendors/<int:pk>/approve/",
        ApproveVendorView.as_view(),
        name="vendor-approve",
    ),
    path(
        "vendors/<int:pk>/reject/",
        RejectVendorView.as_view(),
        name="vendor-reject",
    ),
    path(
        "purchase-orders/",
        PurchaseOrderListCreateView.as_view(),
        name="purchase-order-list-create",
    ),
    path(
        "goods-receipts/",
        GoodsReceiptListCreateView.as_view(),
        name="goods-receipt-list-create",
    ),
]