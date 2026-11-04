from django.core.management.base import BaseCommand

from invoices.models import Invoice, InvoiceLineItem
from invoices.ocr import extract_line_items


class Command(BaseCommand):
    help = "Extract line items from saved OCR text for existing invoices."

    def add_arguments(self, parser):
        parser.add_argument(
            "--invoice-id",
            type=int,
            help="Process only the invoice with this database ID.",
        )

    def handle(self, *args, **options):
        invoices = Invoice.objects.filter(ocr_text__gt="")
        if options["invoice_id"] is not None:
            invoices = invoices.filter(pk=options["invoice_id"])

        processed = 0
        created = 0

        for invoice in invoices.iterator():
            if invoice.line_items.exists():
                continue

            items = extract_line_items(invoice.ocr_text)
            processed += 1
            if not items:
                continue

            InvoiceLineItem.objects.bulk_create(
                [
                    InvoiceLineItem(invoice=invoice, **item)
                    for item in items
                ]
            )
            created += len(items)
            self.stdout.write(
                f"Invoice {invoice.pk} ({invoice.invoice_number}): "
                f"saved {len(items)} line items."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {processed} invoice(s); saved {created} line item(s)."
            )
        )
