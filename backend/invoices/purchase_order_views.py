from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from .models import PurchaseOrder
from .audit import record_audit_event, snapshot
from .permissions import HasInvoiceRole
from .serializers import PurchaseOrderSerializer


class PurchaseOrderListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"AP Clerk"}}
    queryset = PurchaseOrder.objects.select_related("vendor").prefetch_related(
        "line_items",
    )
    serializer_class = PurchaseOrderSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        purchase_order = serializer.save()
        record_audit_event(
            actor=self.request.user,
            entity_type="PURCHASE_ORDER",
            entity_id=purchase_order.pk,
            entity_label=purchase_order.po_number,
            action="CREATED",
            changes={
                **snapshot(
                    purchase_order,
                    ["po_number", "vendor_id", "currency", "order_date", "status", "total_amount"],
                ),
                "line_count": purchase_order.line_items.count(),
            },
        )
