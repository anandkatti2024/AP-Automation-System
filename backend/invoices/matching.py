import re
import unicodedata
from decimal import Decimal

from django.db.models import Sum


AMOUNT_TOLERANCE = Decimal("0.01")


def _normalize_description(value):
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def compare_invoice_to_purchase_order(invoice, purchase_order):
    discrepancies = []

    if invoice.currency.upper() != purchase_order.currency.upper():
        discrepancies.append({
            "type": "currency_mismatch",
            "message": (
                f"Invoice currency {invoice.currency} does not match PO "
                f"currency {purchase_order.currency}."
            ),
        })

    unmatched_po_lines = list(purchase_order.line_items.all())
    invoice_lines = list(invoice.line_items.all())

    for invoice_line in invoice_lines:
        normalized_description = _normalize_description(
            invoice_line.description
        )
        matching_index = next(
            (
                index
                for index, po_line in enumerate(unmatched_po_lines)
                if _normalize_description(po_line.description)
                == normalized_description
            ),
            None,
        )

        if matching_index is None:
            discrepancies.append({
                "type": "invoice_line_not_in_po",
                "message": (
                    f"Invoice line '{invoice_line.description}' is not "
                    "present in the purchase order."
                ),
            })
            continue

        po_line = unmatched_po_lines.pop(matching_index)
        if invoice_line.quantity != po_line.quantity:
            discrepancies.append({
                "type": "quantity_mismatch",
                "message": (
                    f"'{invoice_line.description}' quantity differs: "
                    f"invoice {invoice_line.quantity}, PO {po_line.quantity}."
                ),
            })
        if abs(invoice_line.unit_price - po_line.unit_price) > AMOUNT_TOLERANCE:
            discrepancies.append({
                "type": "unit_price_mismatch",
                "message": (
                    f"'{invoice_line.description}' unit price differs: "
                    f"invoice {invoice_line.unit_price}, "
                    f"PO {po_line.unit_price}."
                ),
            })
        if abs(invoice_line.line_total - po_line.line_total) > AMOUNT_TOLERANCE:
            discrepancies.append({
                "type": "line_total_mismatch",
                "message": (
                    f"'{invoice_line.description}' line total differs: "
                    f"invoice {invoice_line.line_total}, "
                    f"PO {po_line.line_total}."
                ),
            })

    for po_line in unmatched_po_lines:
        discrepancies.append({
            "type": "po_line_missing_from_invoice",
            "message": (
                f"PO line '{po_line.description}' is missing from the invoice."
            ),
        })

    po_total = purchase_order.total_amount
    if abs(invoice.subtotal - po_total) > AMOUNT_TOLERANCE:
        discrepancies.append({
            "type": "subtotal_mismatch",
            "message": (
                f"Invoice subtotal {invoice.subtotal} does not match "
                f"PO total {po_total}."
            ),
        })

    return {
        "status": "MATCHED" if not discrepancies else "MISMATCH",
        "purchase_order_id": purchase_order.id,
        "purchase_order_number": purchase_order.po_number,
        "purchase_order_total": str(po_total),
        "invoice_subtotal": str(invoice.subtotal),
        "discrepancies": discrepancies,
    }


def compare_invoice_to_purchase_order_and_receipts(invoice, purchase_order):
    two_way = compare_invoice_to_purchase_order(invoice, purchase_order)
    discrepancies = list(two_way["discrepancies"])
    receipts = list(
        purchase_order.goods_receipts.prefetch_related(
            "line_items__purchase_order_line",
        ).all()
    )

    if not receipts:
        discrepancies.append({
            "type": "goods_receipt_missing",
            "message": "No goods receipt has been recorded for this purchase order.",
        })
    else:
        received_by_po_line = {
            entry["id"]: entry["total_received"]
            for entry in purchase_order.line_items.filter(
                receipt_lines__goods_receipt__in=receipts,
            )
            .values("id")
            .annotate(total_received=Sum("receipt_lines__quantity_received"))
            .values("id", "total_received")
        }

        unmatched_po_lines = list(purchase_order.line_items.all())
        for invoice_line in invoice.line_items.all():
            description = _normalize_description(invoice_line.description)
            match_index = next(
                (
                    index
                    for index, po_line in enumerate(unmatched_po_lines)
                    if _normalize_description(po_line.description) == description
                ),
                None,
            )
            if match_index is None:
                continue

            po_line = unmatched_po_lines.pop(match_index)
            quantity_received = received_by_po_line.get(
                po_line.id,
                Decimal("0"),
            )
            if quantity_received < invoice_line.quantity:
                discrepancies.append({
                    "type": "received_quantity_too_low",
                    "message": (
                        f"'{invoice_line.description}' invoice quantity "
                        f"{invoice_line.quantity} exceeds received quantity "
                        f"{quantity_received}."
                    ),
                })

        for po_line in purchase_order.line_items.all():
            quantity_received = received_by_po_line.get(
                po_line.id,
                Decimal("0"),
            )
            if quantity_received > po_line.quantity:
                discrepancies.append({
                    "type": "received_quantity_exceeds_po",
                    "message": (
                        f"'{po_line.description}' received quantity "
                        f"{quantity_received} exceeds PO quantity "
                        f"{po_line.quantity}."
                    ),
                })

    return {
        "status": (
            "THREE_WAY_MATCHED"
            if not discrepancies
            else "MISMATCH"
        ),
        "purchase_order_id": purchase_order.id,
        "purchase_order_number": purchase_order.po_number,
        "goods_receipt_count": len(receipts),
        "goods_receipts": [
            {
                "id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "receipt_date": (
                    receipt.receipt_date.isoformat()
                    if receipt.receipt_date
                    else None
                ),
            }
            for receipt in receipts
        ],
        "discrepancies": discrepancies,
    }
