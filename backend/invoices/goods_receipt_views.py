from django.db import transaction
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from .models import GoodsReceipt
from .audit import record_audit_event, snapshot
from .permissions import HasInvoiceRole
from .serializers import GoodsReceiptSerializer


class GoodsReceiptListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"AP Clerk"}}
    queryset = GoodsReceipt.objects.select_related(
        "purchase_order",
    ).prefetch_related(
        "line_items__purchase_order_line",
    )
    serializer_class = GoodsReceiptSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        receipt = serializer.save()
        record_audit_event(
            actor=self.request.user,
            entity_type="GOODS_RECEIPT",
            entity_id=receipt.pk,
            entity_label=receipt.receipt_number,
            action="CREATED",
            changes={
                **snapshot(
                    receipt,
                    ["receipt_number", "purchase_order_id", "receipt_date"],
                ),
                "line_count": receipt.line_items.count(),
                "quantities_received": [
                    {
                        "purchase_order_line_id": line.purchase_order_line_id,
                        "quantity_received": str(line.quantity_received),
                    }
                    for line in receipt.line_items.all()
                ],
            },
        )
