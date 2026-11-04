
from email import policy
from email.parser import BytesParser
from pathlib import PurePath
from uuid import uuid4

from rest_framework import generics, status
from rest_framework.parsers import (
    MultiPartParser,
    FormParser,
    JSONParser,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from .models import ApprovalNotification, AuditEvent, Invoice, InvoiceLineItem
from .audit import changed_fields, record_audit_event, snapshot
from .serializers import (
    ApprovalNotificationSerializer,
    AuditEventSerializer,
    InvoiceSerializer,
)
from .ocr import (
    extract_text_from_file,
    extract_invoice_fields,
    extract_line_items,
    calculate_file_confidence,
)
from .validation import has_duplicate_invoice
from .permissions import HasInvoiceRole
INVOICE_AUDIT_FIELDS = [
    "invoice_number",
    "vendor_name",
    "vendor_gst_number",
    "invoice_date",
    "due_date",
    "subtotal",
    "tax_amount",
    "total_amount",
    "currency",
    "purchase_order_id",
    "status",
]


def process_invoice_file(invoice, actor):
    if not invoice.invoice_file:
        return

    try:
        before_ocr = snapshot(invoice, INVOICE_AUDIT_FIELDS)
        invoice.invoice_file.open("rb")
        text = extract_text_from_file(invoice.invoice_file)
        confidence = calculate_file_confidence(invoice.invoice_file)
        fields = extract_invoice_fields(text)
        line_items = extract_line_items(text)

        for field in (
            "invoice_number",
            "vendor_name",
            "vendor_gst_number",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax_amount",
            "total_amount",
        ):
            if fields.get(field) is not None:
                setattr(invoice, field, fields[field])

        invoice.ocr_text = text
        invoice.ocr_confidence = confidence
        invoice.status = "PENDING_REVIEW"
        invoice.save()
        ocr_changes = changed_fields(
            before_ocr,
            snapshot(invoice, INVOICE_AUDIT_FIELDS),
        )
        ocr_changes["ocr_confidence"] = {"from": None, "to": confidence}
        record_audit_event(
            actor=actor,
            entity_type="INVOICE",
            entity_id=invoice.pk,
            entity_label=invoice.invoice_number,
            action="OCR_PROCESSED",
            changes=ocr_changes,
        )
        invoice.line_items.all().delete()
        InvoiceLineItem.objects.bulk_create(
            [
                InvoiceLineItem(invoice=invoice, **line_item)
                for line_item in line_items
            ]
        )

        if has_duplicate_invoice(invoice):
            invoice.status = "PENDING_REVIEW"
            invoice.save()
            raise ValidationError({
                "duplicate_invoice": (
                    "A similar invoice already exists. "
                    "The uploaded invoice was saved for review."
                )
            })
        invoice.save()
    except ValidationError:
        raise
    except Exception as error:
        print(f"OCR processing failed: {error}")
    finally:
        if invoice.invoice_file:
            invoice.invoice_file.close()


class EmailInvoiceImportView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {"POST": {"AP Clerk"}}
    parser_classes = [MultiPartParser, FormParser]
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    max_email_size = 25 * 1024 * 1024

    @transaction.atomic
    def post(self, request):
        email_file = request.FILES.get("email_file")
        if email_file is None:
            raise ValidationError(
                {"email_file": "Attach an .eml email file to import."}
            )
        if email_file.size > self.max_email_size:
            raise ValidationError(
                {"email_file": "Email file must be no larger than 25 MB."}
            )
        if PurePath(email_file.name).suffix.lower() != ".eml":
            raise ValidationError(
                {"email_file": "Only .eml email files are supported."}
            )

        message = BytesParser(policy=policy.default).parsebytes(email_file.read())
        result = import_email_message(message, request.user)
        return Response(
            result,
            status=status.HTTP_201_CREATED,
        )


def import_email_message(message, actor, require_attachment=True):
    attachments = []
    unsupported = []
    for part in message.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        safe_name = PurePath(filename.replace("\\", "/")).name
        suffix = PurePath(safe_name).suffix.lower()
        if suffix not in EmailInvoiceImportView.allowed_extensions:
            unsupported.append(safe_name)
            continue
        content = part.get_payload(decode=True)
        if not content:
            unsupported.append(safe_name)
            continue
        attachments.append((safe_name, content))

    if not attachments and require_attachment:
        raise ValidationError({
            "email_file": (
                "No supported invoice attachments were found in this email."
            ),
            "unsupported_attachments": unsupported,
        })

    imported = []
    for filename, content in attachments[:20]:
        invoice = Invoice.objects.create(
            invoice_number=f"UPLOAD-{uuid4().hex[:12].upper()}",
            vendor_name="Pending extraction",
            currency="INR",
            status="UPLOADED",
        )
        invoice.invoice_file.save(
            filename,
            SimpleUploadedFile(filename, content),
            save=True,
        )
        record_audit_event(
            actor=actor,
            entity_type="INVOICE",
            entity_id=invoice.pk,
            entity_label=invoice.invoice_number,
            action="CREATED_FROM_EMAIL",
            changes={"attachment_name": filename},
        )
        try:
            process_invoice_file(invoice, actor)
        except ValidationError as error:
            imported.append({
                "id": invoice.pk,
                "filename": filename,
                "status": "PENDING_REVIEW",
                "warning": error.detail,
            })
            continue
        invoice.refresh_from_db()
        imported.append({
            "id": invoice.pk,
            "filename": filename,
            "status": invoice.status,
        })

    if len(attachments) > 20:
        unsupported.append(
            f"{len(attachments) - 20} additional attachments were not imported (20-file limit)."
        )
    return {
        "imported": imported,
        "unsupported_attachments": unsupported,
        "email_subject": str(message.get("subject", ""))[:255],
    }


class ApprovalNotificationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    serializer_class = ApprovalNotificationSerializer

    def get_queryset(self):
        return ApprovalNotification.objects.filter(
            recipient=self.request.user
        ).select_related("approval_step__invoice")


class ApprovalNotificationReadView(APIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]

    def post(self, request, pk):
        notification = get_object_or_404(
            ApprovalNotification,
            pk=pk,
            recipient=request.user,
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(ApprovalNotificationSerializer(notification).data)


class AuditEventListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    serializer_class = AuditEventSerializer

    def get_queryset(self):
        queryset = AuditEvent.objects.all()
        entity_type = self.request.query_params.get("entity_type")
        action = self.request.query_params.get("action")
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type.upper())
        if action:
            queryset = queryset.filter(action=action.upper())

        try:
            limit = int(self.request.query_params.get("limit", "200"))
        except ValueError as error:
            raise ValidationError({"limit": "Limit must be an integer."}) from error
        if limit < 1:
            raise ValidationError({"limit": "Limit must be at least 1."})
        return queryset[: min(limit, 500)]


class InvoiceListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {
        "POST": {"AP Clerk"},
    }
    queryset = Invoice.objects.select_related(
        "purchase_order",
    ).prefetch_related(
        "line_items",
        "purchase_order__line_items",
        "approval_history__actor",
    )
    serializer_class = InvoiceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):
        invoice = serializer.save()
        record_audit_event(
            actor=self.request.user,
            entity_type="INVOICE",
            entity_id=invoice.pk,
            entity_label=invoice.invoice_number,
            action="CREATED",
            changes=snapshot(invoice, INVOICE_AUDIT_FIELDS),
        )
        process_invoice_file(invoice, self.request.user)


class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, HasInvoiceRole]
    required_roles_by_method = {
        "PUT": {"AP Clerk"},
        "PATCH": {"AP Clerk"},
        "DELETE": {"AP Clerk"},
    }
    queryset = Invoice.objects.select_related(
        "purchase_order",
    ).prefetch_related(
        "line_items",
        "purchase_order__line_items",
        "approval_history__actor",
    )
    serializer_class = InvoiceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_update(self, serializer):
        fields = [
            "invoice_number",
            "vendor_name",
            "vendor_gst_number",
            "invoice_date",
            "due_date",
            "subtotal",
            "tax_amount",
            "total_amount",
            "currency",
            "purchase_order_id",
            "status",
        ]
        before = snapshot(serializer.instance, fields)
        invoice = serializer.save()
        changes = changed_fields(before, snapshot(invoice, fields))
        if changes:
            record_audit_event(
                actor=self.request.user,
                entity_type="INVOICE",
                entity_id=invoice.pk,
                entity_label=invoice.invoice_number,
                action="UPDATED",
                changes=changes,
            )

    def perform_destroy(self, instance):
        if instance.payments.exists():
            raise ValidationError(
                "Invoices with recorded payments cannot be deleted."
            )
        record_audit_event(
            actor=self.request.user,
            entity_type="INVOICE",
            entity_id=instance.pk,
            entity_label=instance.invoice_number,
            action="DELETED",
            changes=snapshot(
                instance,
                ["invoice_number", "vendor_name", "total_amount", "status"],
            ),
        )
        instance.delete()
