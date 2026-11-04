from io import StringIO
from datetime import date, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from .models import (
    ApprovalNotification,
    AuditEvent,
    GoodsReceipt,
    GoodsReceiptLineItem,
    InvoiceApprovalHistory,
    InvoiceApprovalRule,
    InvoiceApprovalStep,
    Invoice,
    IntegrationCredential,
    InvoiceLineItem,
    ImportedEmail,
    InvoicePayment,
    PaymentRequest,
    PurchaseOrder,
    PurchaseOrderLineItem,
    Vendor,
    VendorOnboardingHistory,
)
from .ocr import extract_line_items
from .matching import (
    compare_invoice_to_purchase_order,
    compare_invoice_to_purchase_order_and_receipts,
)
from .serializers import InvoiceSerializer
from .validation import (
    has_duplicate_invoice,
    normalize_invoice_number,
    normalize_vendor_name,
)


class APClerkTestCase(APITestCase):
    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_user(
            username="ap-clerk",
            password="test-password",
        )
        user.groups.add(Group.objects.get(name="AP Clerk"))
        self.test_user = user
        self.client.force_authenticate(user=user)


class AuthenticationAndRoleApiTests(APITestCase):
    def test_invoice_api_rejects_anonymous_requests(self):
        response = self.client.get("/api/invoices/")

        self.assertIn(response.status_code, (401, 403))

    def test_registration_creates_ap_clerk_and_starts_session(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/auth/session/")
        csrf_token = client.cookies["csrftoken"].value

        response = client.post(
            "/api/auth/register/",
            {
                "username": "new-ap-clerk",
                "password": "Strong-unique-password-947!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["username"], "new-ap-clerk")
        self.assertEqual(response.json()["roles"], ["AP Clerk"])
        user = get_user_model().objects.get(username="new-ap-clerk")
        self.assertTrue(user.check_password("Strong-unique-password-947!"))
        self.assertTrue(client.get("/api/auth/session/").json()["authenticated"])

    def test_registration_rejects_weak_password_and_duplicate_username(self):
        password_response = self.client.post(
            "/api/auth/register/",
            {"username": "new-clerk", "password": "123"},
            format="json",
        )
        self.assertEqual(password_response.status_code, 400)
        self.assertIn("password", password_response.json()["errors"])

        get_user_model().objects.create_user(
            username="existing-clerk",
            password="Strong-unique-password-947!",
        )
        duplicate_response = self.client.post(
            "/api/auth/register/",
            {
                "username": "existing-clerk",
                "password": "Strong-unique-password-947!",
            },
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertIn("already in use", duplicate_response.json()["detail"])

    def test_registration_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)

        response = client.post(
            "/api/auth/register/",
            {
                "username": "csrf-clerk",
                "password": "Strong-unique-password-947!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_login_requires_csrf_and_returns_user_roles(self):
        user = get_user_model().objects.create_user(
            username="login-clerk",
            password="secure-test-password",
        )
        user.groups.add(Group.objects.get(name="AP Clerk"))
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/auth/session/")
        csrf_token = client.cookies["csrftoken"].value

        blocked = client.post(
            "/api/auth/session/",
            {"username": "login-clerk", "password": "secure-test-password"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 403)

        response = client.post(
            "/api/auth/session/",
            {"username": "login-clerk", "password": "secure-test-password"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "login-clerk")
        self.assertIn("AP Clerk", response.json()["roles"])
        session_response = client.get("/api/auth/session/")
        self.assertTrue(session_response.json()["authenticated"])

    def test_login_rejects_accounts_without_an_ap_role(self):
        user = get_user_model().objects.create_user(
            username="unassigned-user",
            password="secure-test-password",
        )

        self.client.force_login(user)
        session_response = self.client.get("/api/auth/session/")
        self.assertFalse(session_response.json()["authenticated"])

        response = self.client.post(
            "/api/auth/session/",
            {"username": "unassigned-user", "password": "secure-test-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("no AP role assigned", response.json()["detail"])

    def test_role_permissions_block_approval_from_ap_clerk(self):
        user = get_user_model().objects.create_user(
            username="role-clerk",
            password="test-password",
        )
        user.groups.add(Group.objects.get(name="AP Clerk"))
        self.client.force_authenticate(user=user)
        invoice = Invoice.objects.create(
            invoice_number="ROLE-CHECK-1",
            vendor_name="Role Check Vendor",
            status="PENDING_APPROVAL",
        )
        InvoiceApprovalStep.objects.create(
            invoice=invoice,
            role="Approver",
        )

        response = self.client.post(
            f"/api/invoices/{invoice.pk}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_approver_cannot_record_payments(self):
        user = get_user_model().objects.create_user(
            username="role-approver",
            password="test-password",
        )
        user.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/invoices/1/payments/",
            {
                "amount": "10.00",
                "payment_date": "2025-08-20",
                "payment_reference": "ROLE-CHECK-1",
                "payment_method": "BANK_TRANSFER",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)


class AuditLogApiTests(APClerkTestCase):
    endpoint = "/api/invoices/audit-events/"

    def test_invoice_create_update_and_delete_are_audited(self):
        created = self.client.post(
            "/api/invoices/",
            {
                "invoice_number": "AUDIT-001",
                "vendor_name": "Audit Supplies",
                "subtotal": "100.00",
                "tax_amount": "18.00",
                "total_amount": "118.00",
                "currency": "INR",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        invoice_id = created.data["id"]
        create_event = AuditEvent.objects.get(
            entity_type="INVOICE",
            entity_id=str(invoice_id),
            action="CREATED",
        )
        self.assertEqual(create_event.actor_name, self.test_user.username)
        self.assertEqual(create_event.changes["invoice_number"], "AUDIT-001")

        updated = self.client.patch(
            f"/api/invoices/{invoice_id}/",
            {"invoice_number": "AUDIT-001-UPDATED"},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        update_event = AuditEvent.objects.get(
            entity_type="INVOICE",
            entity_id=str(invoice_id),
            action="UPDATED",
        )
        self.assertEqual(
            update_event.changes["invoice_number"],
            {"from": "AUDIT-001", "to": "AUDIT-001-UPDATED"},
        )

        deleted = self.client.delete(f"/api/invoices/{invoice_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertTrue(
            AuditEvent.objects.filter(
                entity_type="INVOICE",
                entity_id=str(invoice_id),
                action="DELETED",
            ).exists()
        )

    def test_audit_list_is_role_protected_and_never_contains_bank_numbers(self):
        vendor_response = self.client.post(
            "/api/invoices/vendors/",
            {
                "name": "Audit Bank Vendor",
                "bank_account_name": "Audit Bank Vendor",
                "bank_account_number": "987654321012",
                "bank_ifsc": "HDFC0001234",
            },
            format="json",
        )
        self.assertEqual(vendor_response.status_code, 201)

        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        audit_event = next(
            event for event in response.data
            if event["entity_label"] == "Audit Bank Vendor"
        )
        serialized_changes = str(audit_event["changes"])
        self.assertNotIn("987654321012", serialized_changes)
        self.assertEqual(audit_event["changes"]["bank_account_last4"], "1012")

        self.client.force_authenticate(user=None)
        anonymous_response = self.client.get(self.endpoint)
        self.assertIn(anonymous_response.status_code, (401, 403))


class EmailInvoiceImportTests(APClerkTestCase):
    def setUp(self):
        super().setUp()
        media_directory = TemporaryDirectory()
        self.addCleanup(media_directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def test_imports_supported_email_attachments_through_existing_ocr_flow(self):
        email_content = (
            b"MIME-Version: 1.0\r\n"
            b"Subject: Invoice from supplier\r\n"
            b"Content-Type: multipart/mixed; boundary=invoice-boundary\r\n"
            b"\r\n--invoice-boundary\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Please find the invoice attached.\r\n"
            b"--invoice-boundary\r\n"
            b"Content-Type: application/pdf; name=\"supplier-invoice.pdf\"\r\n"
            b"Content-Disposition: attachment; filename=\"supplier-invoice.pdf\"\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n"
            b"JVBERi0xLjQK\r\n"
            b"--invoice-boundary--\r\n"
        )
        with (
            patch(
                "invoices.views.extract_text_from_file",
                return_value="invoice text",
            ),
            patch(
                "invoices.views.calculate_file_confidence",
                return_value=91.0,
            ),
            patch(
                "invoices.views.extract_invoice_fields",
                return_value={
                    "invoice_number": "EMAIL-001",
                    "vendor_name": "Email Supplier",
                },
            ),
            patch("invoices.views.extract_line_items", return_value=[]),
        ):
            response = self.client.post(
                "/api/invoices/email-import/",
                {
                    "email_file": SimpleUploadedFile(
                        "invoice-email.eml",
                        email_content,
                        content_type="message/rfc822",
                    )
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email_subject"], "Invoice from supplier")
        self.assertEqual(len(response.data["imported"]), 1)
        imported = Invoice.objects.get(pk=response.data["imported"][0]["id"])
        self.assertEqual(imported.invoice_number, "EMAIL-001")
        self.assertEqual(imported.status, "PENDING_REVIEW")
        self.assertTrue(imported.invoice_file.name.endswith(".pdf"))

    def test_email_import_rejects_non_eml_and_unsupported_attachments(self):
        invalid_email = self.client.post(
            "/api/invoices/email-import/",
            {
                "email_file": SimpleUploadedFile(
                    "invoice.txt",
                    b"not an email",
                    content_type="text/plain",
                )
            },
            format="multipart",
        )
        self.assertEqual(invalid_email.status_code, 400)

        email_content = (
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: multipart/mixed; boundary=unsupported\r\n"
            b"\r\n--unsupported\r\n"
            b"Content-Type: text/plain; name=\"notes.txt\"\r\n"
            b"Content-Disposition: attachment; filename=\"notes.txt\"\r\n\r\n"
            b"not an invoice\r\n"
            b"--unsupported--\r\n"
        )
        response = self.client.post(
            "/api/invoices/email-import/",
            {
                "email_file": SimpleUploadedFile(
                    "message.eml",
                    email_content,
                    content_type="message/rfc822",
                )
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported_attachments", response.data)

    def test_imap_poller_imports_unread_messages_once(self):
        email_content = (
            b"MIME-Version: 1.0\r\n"
            b"Subject: Scheduled invoice\r\n"
            b"Message-ID: <imap-uid-101@example.test>\r\n"
            b"Content-Type: multipart/mixed; boundary=scheduled\r\n"
            b"\r\n--scheduled\r\n"
            b"Content-Type: application/pdf; name=\"scheduled.pdf\"\r\n"
            b"Content-Disposition: attachment; filename=\"scheduled.pdf\"\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n"
            b"JVBERi0xLjQK\r\n"
            b"--scheduled--\r\n"
        )

        class FakeImap:
            def __init__(self):
                self.seen_uids = []

            def login(self, username, password):
                return "OK", []

            def select(self, mailbox):
                return "OK", []

            def response(self, code):
                return code, [b"912345"]

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"101"]
                if command == "fetch":
                    return "OK", [(b"BODY[]", email_content)]
                if command == "store":
                    self.seen_uids.append(args[0])
                    return "OK", []
                raise AssertionError(f"Unexpected IMAP command: {command}")

            def logout(self):
                return "BYE", []

        connection = FakeImap()
        with (
            override_settings(
                IMAP_HOST="imap.example.test",
                IMAP_USERNAME="ap@example.test",
                IMAP_PASSWORD="not-a-real-password",
                IMAP_MAILBOX="INBOX",
            ),
            patch(
                "invoices.management.commands.poll_invoice_mailbox.imaplib.IMAP4_SSL",
                return_value=connection,
            ),
            patch("invoices.views.extract_text_from_file", return_value="invoice text"),
            patch("invoices.views.calculate_file_confidence", return_value=90.0),
            patch("invoices.views.extract_invoice_fields", return_value={}),
            patch("invoices.views.extract_line_items", return_value=[]),
        ):
            call_command("poll_invoice_mailbox", stdout=StringIO())
            call_command("poll_invoice_mailbox", stdout=StringIO())

        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(ImportedEmail.objects.count(), 1)
        self.assertEqual(ImportedEmail.objects.get().uid_validity, "912345")
        self.assertEqual(ImportedEmail.objects.get().invoice_ids, [Invoice.objects.get().pk])
        self.assertEqual(connection.seen_uids, [b"101", b"101"])


class ExternalIntegrationApiTests(APClerkTestCase):
    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.create(
            name="Integration Supplier",
            onboarding_status="ACTIVE",
            quickbooks_vendor_id="QBV-100",
            quickbooks_expense_account_id="QBA-200",
            stripe_connected_account_id="acct_test_connected",
        )

    def test_quickbooks_oauth_requires_administrator_and_uses_state(self):
        response = self.client.get(
            "/api/invoices/integrations/quickbooks/authorize/"
        )
        self.assertEqual(response.status_code, 403)

        user = self.test_user
        user.groups.add(Group.objects.get(name="Administrator"))
        with override_settings(
            QUICKBOOKS_CLIENT_ID="client-id",
            QUICKBOOKS_CLIENT_SECRET="client-secret",
            QUICKBOOKS_REDIRECT_URI="http://localhost/callback",
        ):
            response = self.client.get(
                "/api/invoices/integrations/quickbooks/authorize/"
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("state=", response.data["authorization_url"])
        self.assertTrue(self.client.session["quickbooks_oauth_state"])

    def test_quickbooks_oauth_callback_exchanges_code_and_returns_to_app(self):
        session = self.client.session
        session["quickbooks_oauth_state"] = "expected-state"
        session.save()

        with (
            override_settings(
                FRONTEND_URL="http://localhost:5173/",
                QUICKBOOKS_CLIENT_ID="client-id",
                QUICKBOOKS_CLIENT_SECRET="client-secret",
                QUICKBOOKS_REDIRECT_URI="http://localhost/callback",
            ),
            patch("invoices.integration_views.exchange_quickbooks_code") as exchange,
        ):
            response = self.client.get(
                "/api/invoices/integrations/quickbooks/callback/",
                {
                    "state": "expected-state",
                    "code": "authorization-code",
                    "realmId": "company-id",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "http://localhost:5173/?integration=quickbooks-connected",
        )
        exchange.assert_called_once_with("authorization-code", "company-id")
        self.assertNotIn("quickbooks_oauth_state", self.client.session)

    def test_quickbooks_pending_bill_sync_is_idempotent(self):
        payment_clerk = get_user_model().objects.create_user(
            username="quickbooks-clerk",
            password="secure-test-password",
        )
        payment_clerk.groups.add(Group.objects.get(name="Payment Clerk"))
        self.client.force_authenticate(user=payment_clerk)
        invoice = Invoice.objects.create(
            invoice_number="QBO-INV-100",
            vendor_name=self.vendor.name,
            total_amount=Decimal("125.00"),
            subtotal=Decimal("125.00"),
            status="APPROVED",
        )

        with patch(
            "invoices.integration_views.create_quickbooks_draft_bill",
            return_value="QBO-BILL-100",
        ) as create_bill:
            first = self.client.post(
                f"/api/invoices/{invoice.pk}/quickbooks-sync/",
                {},
                format="json",
            )
            second = self.client.post(
                f"/api/invoices/{invoice.pk}/quickbooks-sync/",
                {},
                format="json",
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["quickbooks_bill_id"], "QBO-BILL-100")
        self.assertEqual(create_bill.call_count, 1)

    def test_stripe_transfer_requires_confirmation_and_records_success(self):
        payment_clerk = get_user_model().objects.create_user(
            username="stripe-clerk",
            password="secure-test-password",
        )
        payment_clerk.groups.add(Group.objects.get(name="Payment Clerk"))
        self.client.force_authenticate(user=payment_clerk)
        invoice = Invoice.objects.create(
            invoice_number="STRIPE-INV-100",
            vendor_name=self.vendor.name,
            total_amount=Decimal("500.00"),
            status="APPROVED",
        )
        request = PaymentRequest.objects.create(
            invoice=invoice,
            requested_amount=Decimal("500.00"),
            requested_by=payment_clerk,
            requested_by_name=payment_clerk.username,
        )
        url = f"/api/invoices/payment-requests/{request.pk}/stripe-transfer/"

        with patch(
            "invoices.integration_views.create_stripe_connect_transfer",
            return_value="tr_test_transfer",
        ) as create_transfer:
            unconfirmed = self.client.post(
                url,
                {"confirm": False},
                format="json",
            )
            self.assertEqual(unconfirmed.status_code, 400)
            create_transfer.assert_not_called()

            response = self.client.post(
                url,
                {"confirm": True},
                format="json",
            )
            replay = self.client.post(
                url,
                {"confirm": True},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(create_transfer.call_count, 1)
        self.assertEqual(
            InvoicePayment.objects.get().payment_reference,
            "STRIPE-tr_test_transfer",
        )
        request.refresh_from_db()
        self.assertEqual(request.status, "PAID")
        self.assertEqual(request.stripe_transfer_id, "tr_test_transfer")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "PAID")

    def test_quickbooks_tokens_are_encrypted_in_database(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode("ascii")
        with override_settings(INTEGRATION_ENCRYPTION_KEY=key):
            from invoices.integrations import save_quickbooks_tokens

            save_quickbooks_tokens(
                {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "expires_in": 3600,
                },
                "realm-test",
            )

        credential = IntegrationCredential.objects.get(provider="QUICKBOOKS")
        self.assertNotIn("access-secret", credential.access_token_encrypted)
        self.assertNotIn("refresh-secret", credential.refresh_token_encrypted)
        self.assertEqual(credential.realm_id, "realm-test")

    def test_quickbooks_bill_payload_and_stripe_transfer_use_provider_apis(self):
        import json

        from cryptography.fernet import Fernet

        from invoices.integrations import (
            create_quickbooks_draft_bill,
            create_stripe_connect_transfer,
            save_quickbooks_tokens,
        )

        class FakeResponse:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return self.content

        key = Fernet.generate_key().decode("ascii")
        invoice = Invoice.objects.create(
            invoice_number="EXT-INV-100",
            vendor_name=self.vendor.name,
            invoice_date=date(2026, 10, 10),
            due_date=date(2026, 11, 10),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("18.00"),
            total_amount=Decimal("118.00"),
            currency="INR",
            status="APPROVED",
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            line_number=1,
            description="Consulting",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("100.00"),
        )
        payment_request = PaymentRequest.objects.create(
            invoice=invoice,
            requested_amount=Decimal("118.00"),
            requested_by=self.test_user,
            requested_by_name=self.test_user.username,
        )

        with override_settings(
            INTEGRATION_ENCRYPTION_KEY=key,
            QUICKBOOKS_CLIENT_ID="client-id",
            QUICKBOOKS_CLIENT_SECRET="client-secret",
            QUICKBOOKS_REDIRECT_URI="http://localhost/callback",
            QUICKBOOKS_SANDBOX=True,
        ):
            save_quickbooks_tokens(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
                "realm-test",
            )
            with patch(
                "invoices.integrations.urlopen",
                return_value=FakeResponse(b'{"Bill":{"Id":"QBO-EXT-100"}}'),
            ) as qbo_call:
                bill_id = create_quickbooks_draft_bill(invoice, self.vendor)

        self.assertEqual(bill_id, "QBO-EXT-100")
        qbo_request = qbo_call.call_args.args[0]
        self.assertIn("sandbox-quickbooks.api.intuit.com", qbo_request.full_url)
        payload = json.loads(qbo_request.data.decode("utf-8"))
        self.assertEqual(payload["TxnStatus"], "Pending")
        self.assertEqual(payload["Line"][0]["Amount"], 100.0)
        self.assertEqual(payload["Line"][1]["Amount"], 18.0)

        with override_settings(
            STRIPE_SECRET_KEY="sk_test_unit_test",
            STRIPE_API_BASE_URL="https://api.stripe.test/v1",
        ):
            with patch(
                "invoices.integrations.urlopen",
                return_value=FakeResponse(b'{"id":"tr_test_unit"}'),
            ) as stripe_call:
                transfer_id = create_stripe_connect_transfer(
                    invoice,
                    self.vendor,
                    payment_request,
                )

        self.assertEqual(transfer_id, "tr_test_unit")
        stripe_request = stripe_call.call_args.args[0]
        transfer_payload = parse_qs(stripe_request.data.decode("utf-8"))
        self.assertEqual(transfer_payload["amount"], ["11800"])
        self.assertEqual(
            transfer_payload["destination"],
            ["acct_test_connected"],
        )
        self.assertEqual(
            stripe_request.get_header("Idempotency-key"),
            f"ap-payment-request-{payment_request.pk}",
        )


class DuplicateInvoiceValidationTests(TestCase):
    def setUp(self):
        Invoice.objects.create(
            invoice_number="INV-001",
            vendor_name="acmecorp.",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

    def test_normalizes_invoice_number_punctuation_and_case(self):
        self.assertEqual(
            normalize_invoice_number("INV001"),
            normalize_invoice_number("inv-001"),
        )

    def test_normalizes_vendor_punctuation_suffix_and_repeated_ocr_text(self):
        expected = normalize_vendor_name("acmecorp.")
        self.assertEqual(normalize_vendor_name("Acme Corp."), expected)
        self.assertEqual(normalize_vendor_name("Acme Corporation"), expected)
        self.assertEqual(
            normalize_vendor_name("Acme Corporation Acme Corporation"),
            expected,
        )

    def test_flags_same_invoice_and_equivalent_vendor(self):
        candidate = Invoice(
            invoice_number="inv001",
            vendor_name="Acme Corporation Acme Corporation",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        errors = InvoiceSerializer(candidate).get_validation_errors(candidate)

        self.assertTrue(any("Possible duplicate" in error for error in errors))

    def test_does_not_flag_when_invoice_number_differs(self):
        candidate = Invoice(
            invoice_number="INV-002",
            vendor_name="Acme Corporation",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        self.assertFalse(has_duplicate_invoice(candidate))

    def test_does_not_flag_when_vendor_differs(self):
        candidate = Invoice(
            invoice_number="INV-001",
            vendor_name="Other Company",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        self.assertFalse(has_duplicate_invoice(candidate))

    def test_invoice_matches_active_vendor_by_normalized_name(self):
        Vendor.objects.create(
            name="Acme Corp.",
            onboarding_status="ACTIVE",
        )
        candidate = Invoice(
            invoice_number="INV-100",
            vendor_name="Acme Corporation Acme Corporation",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        errors = InvoiceSerializer(candidate).get_validation_errors(candidate)

        self.assertFalse(
            any("not registered in the vendor master" in error for error in errors)
        )
        self.assertFalse(
            any("onboarding is not complete" in error for error in errors)
        )

    def test_invoice_with_unknown_vendor_requires_vendor_master_review(self):
        candidate = Invoice(
            invoice_number="INV-100",
            vendor_name="Unknown Supplier",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        errors = InvoiceSerializer(candidate).get_validation_errors(candidate)

        self.assertIn(
            "Vendor is not registered in the vendor master.",
            errors,
        )

    def test_invalid_ocr_gstin_falls_back_to_name_and_is_flagged(self):
        Vendor.objects.create(
            name="Acme Corp.",
            onboarding_status="ACTIVE",
        )
        candidate = Invoice(
            invoice_number="INV-100",
            vendor_name="Acme Corporation",
            vendor_gst_number="20123456789",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1250.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1250.00"),
        )

        errors = InvoiceSerializer(candidate).get_validation_errors(candidate)

        self.assertTrue(
            any("15-character Indian GSTIN format" in error for error in errors)
        )
        self.assertFalse(
            any("not registered in the vendor master" in error for error in errors)
        )


class InvoiceLineItemExtractionTests(TestCase):
    def test_extracts_numbered_rows_with_currency_and_thousands_separators(self):
        text = """
        # Description Qty Unit Price Total
        1 Consulting Services 10 $100.00 $1,000.00
        2 Software License 1 $250.00 $250.00
        Subtotal $1,250.00
        """

        items = extract_line_items(text)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["description"], "Consulting Services")
        self.assertEqual(items[0]["line_number"], 1)
        self.assertEqual(items[0]["quantity"], Decimal("10"))
        self.assertEqual(items[0]["unit_price"], Decimal("100.00"))
        self.assertEqual(items[0]["line_total"], Decimal("1000.00"))
        self.assertEqual(items[1]["description"], "Software License")
        self.assertEqual(items[1]["line_total"], Decimal("250.00"))

    def test_extracts_decimal_quantity_and_defaults_missing_line_number(self):
        text = """
        Description Quantity Rate Amount
        Steel sheets 2.5 INR 80.00 INR 200.00
        """

        items = extract_line_items(text)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["line_number"], 1)
        self.assertEqual(items[0]["quantity"], Decimal("2.5"))
        self.assertEqual(items[0]["unit_price"], Decimal("80.00"))
        self.assertEqual(items[0]["line_total"], Decimal("200.00"))

    def test_returns_empty_list_when_no_line_item_table_exists(self):
        self.assertEqual(
            extract_line_items("Invoice total: $100.00"),
            [],
        )

    def test_extracts_items_from_repeated_tables_across_pages(self):
        text = """
        # Description Qty Unit Price Total
        1 Consulting Services 10 $100.00 $1,000.00
        Subtotal $1,000.00
        # Description Qty Unit Price Total
        2 Software License 1 $250.00 $250.00
        Total $1,250.00
        """

        items = extract_line_items(text)

        self.assertEqual([item["description"] for item in items], [
            "Consulting Services",
            "Software License",
        ])


class VendorManagementApiTests(APClerkTestCase):
    endpoint = "/api/invoices/vendors/"

    def test_create_vendor_validates_gstin_and_masks_bank_account(self):
        response = self.client.post(
            self.endpoint,
            {
                "name": "Acme Supplies",
                "gstin": "27abcde1234f1z5",
                "tax_id": "TIN-123",
                "contact_email": "ap@acme.example",
                "bank_account_name": "Acme Supplies",
                "bank_account_number": "123456789012",
                "bank_ifsc": "hdfc0001234",
                "onboarding_status": "UNDER_REVIEW",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["gstin"], "27ABCDE1234F1Z5")
        self.assertEqual(response.data["bank_ifsc"], "HDFC0001234")
        self.assertEqual(response.data["bank_account_last4"], "9012")
        self.assertEqual(response.data["onboarding_status"], "PENDING")
        self.assertNotIn("bank_account_number", response.data)

    def test_vendor_onboarding_requires_separate_review_actions(self):
        created = self.client.post(
            self.endpoint,
            {"name": "Workflow Vendor", "onboarding_status": "ACTIVE"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        vendor_id = created.data["id"]
        self.assertEqual(created.data["onboarding_status"], "PENDING")

        bypass = self.client.patch(
            f"{self.endpoint}{vendor_id}/",
            {"onboarding_status": "ACTIVE"},
            format="json",
        )
        self.assertEqual(bypass.status_code, 200)
        self.assertEqual(bypass.data["onboarding_status"], "PENDING")

        submitted = self.client.post(
            f"{self.endpoint}{vendor_id}/submit-for-review/",
            {"comment": "Documents collected"},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["onboarding_status"], "UNDER_REVIEW")

        locked_update = self.client.patch(
            f"{self.endpoint}{vendor_id}/",
            {"name": "Changed during review"},
            format="json",
        )
        self.assertEqual(locked_update.status_code, 400)
        self.assertIn("cannot be changed", str(locked_update.data))

        forbidden_approval = self.client.post(
            f"{self.endpoint}{vendor_id}/approve/",
            {},
            format="json",
        )
        self.assertEqual(forbidden_approval.status_code, 403)

        approver = get_user_model().objects.create_user(
            username="vendor-approver",
            password="secure-test-password",
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=approver)
        approved = self.client.post(
            f"{self.endpoint}{vendor_id}/approve/",
            {"comment": "Verified"},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["onboarding_status"], "ACTIVE")
        self.assertEqual(
            [entry["action"] for entry in approved.data["onboarding_history"]],
            ["SUBMITTED", "APPROVED"],
        )
        self.assertEqual(
            VendorOnboardingHistory.objects.filter(vendor_id=vendor_id).count(),
            2,
        )

    def test_vendor_rejection_requires_a_reason_and_can_be_resubmitted(self):
        vendor = Vendor.objects.create(name="Resubmission Vendor")
        VendorOnboardingHistory.objects.create(
            vendor=vendor,
            action="SUBMITTED",
            actor=self.test_user,
            actor_name=self.test_user.username,
        )
        vendor.onboarding_status = "UNDER_REVIEW"
        vendor.save(update_fields=["onboarding_status"])

        approver = get_user_model().objects.create_user(
            username="vendor-rejector",
            password="secure-test-password",
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=approver)
        rejected_without_reason = self.client.post(
            f"{self.endpoint}{vendor.pk}/reject/",
            {},
            format="json",
        )
        self.assertEqual(rejected_without_reason.status_code, 400)
        rejected = self.client.post(
            f"{self.endpoint}{vendor.pk}/reject/",
            {"comment": "Please provide a valid tax certificate."},
            format="json",
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.data["onboarding_status"], "REJECTED")

        self.client.force_authenticate(user=self.test_user)
        resubmitted = self.client.post(
            f"{self.endpoint}{vendor.pk}/submit-for-review/",
            {"comment": "Updated tax certificate provided"},
            format="json",
        )
        self.assertEqual(resubmitted.status_code, 200)
        self.assertEqual(resubmitted.data["onboarding_status"], "UNDER_REVIEW")

    def test_rejects_invalid_gstin(self):
        response = self.client.post(
            self.endpoint,
            {"name": "Invalid GST vendor", "gstin": "not-a-gstin"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("gstin", response.data)

    def test_rejects_duplicate_gstin_case_insensitively(self):
        self.client.post(
            self.endpoint,
            {"name": "First vendor", "gstin": "27ABCDE1234F1Z5"},
            format="json",
        )

        response = self.client.post(
            self.endpoint,
            {"name": "Second vendor", "gstin": "27abcde1234f1z5"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("gstin", response.data)

    def test_requires_bank_account_number_and_ifsc_together(self):
        response = self.client.post(
            self.endpoint,
            {
                "name": "Incomplete bank vendor",
                "bank_account_number": "123456789",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("bank_details", response.data)


class InvoiceLineItemApiTests(APClerkTestCase):
    def test_upload_saves_extracted_line_items(self):
        extracted_items = [
            {
                "line_number": 1,
                "description": "Consulting Services",
                "quantity": Decimal("10"),
                "unit_price": Decimal("100.00"),
                "line_total": Decimal("1000.00"),
            }
        ]

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                with (
                    patch(
                        "invoices.views.extract_text_from_file",
                        return_value="sample OCR text",
                    ),
                    patch(
                        "invoices.views.calculate_file_confidence",
                        return_value=90.0,
                    ),
                    patch(
                        "invoices.views.extract_invoice_fields",
                        return_value={},
                    ),
                    patch(
                        "invoices.views.extract_line_items",
                        return_value=extracted_items,
                    ),
                ):
                    response = self.client.post(
                        "/api/invoices/",
                        {
                            "invoice_number": "INV-UPLOAD-LINES",
                            "vendor_name": "Line Item Supplier",
                            "invoice_file": SimpleUploadedFile(
                                "sample.png",
                                b"fake image data",
                                content_type="image/png",
                            ),
                        },
                        format="multipart",
                    )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["line_items"]), 1)
        self.assertEqual(
            response.data["line_items"][0]["description"],
            "Consulting Services",
        )


class TwoWayPurchaseOrderMatchingTests(APClerkTestCase):
    endpoint = "/api/invoices/purchase-orders/"

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.create(
            name="Acme Corp.",
            gstin="27ABCDE1234F1Z5",
            onboarding_status="ACTIVE",
        )
        self.purchase_order = PurchaseOrder.objects.create(
            po_number="PO-100",
            vendor=self.vendor,
            currency="INR",
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            line_number=1,
            description="Consulting Services",
            quantity=Decimal("10"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("1000.00"),
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            line_number=2,
            description="Software License",
            quantity=Decimal("1"),
            unit_price=Decimal("250.00"),
            line_total=Decimal("250.00"),
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-PO-100",
            vendor_name="Acme Corporation",
            vendor_gst_number="27ABCDE1234F1Z5",
            subtotal=Decimal("1250.00"),
            total_amount=Decimal("1250.00"),
            currency="INR",
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            description="consulting services",
            quantity=Decimal("10"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("1000.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=2,
            description="Software License",
            quantity=Decimal("1"),
            unit_price=Decimal("250.00"),
            line_total=Decimal("250.00"),
        )

    def test_exact_invoice_and_po_lines_are_matched(self):
        result = compare_invoice_to_purchase_order(
            self.invoice,
            self.purchase_order,
        )

        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(result["discrepancies"], [])

    def test_reports_line_and_currency_discrepancies(self):
        invoice_line = self.invoice.line_items.first()
        invoice_line.quantity = Decimal("9")
        invoice_line.save()
        self.invoice.currency = "USD"
        self.invoice.subtotal = Decimal("1150.00")
        self.invoice.save()

        result = compare_invoice_to_purchase_order(
            self.invoice,
            self.purchase_order,
        )
        discrepancy_types = {
            item["type"] for item in result["discrepancies"]
        }

        self.assertEqual(result["status"], "MISMATCH")
        self.assertIn("quantity_mismatch", discrepancy_types)
        self.assertIn("currency_mismatch", discrepancy_types)
        self.assertIn("subtotal_mismatch", discrepancy_types)

    def test_linking_invoice_returns_match_result_and_rejects_other_vendor(self):
        response = self.client.patch(
            f"/api/invoices/{self.invoice.pk}/",
            {"purchase_order": self.purchase_order.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["two_way_match"]["status"], "MATCHED")

        other_vendor = Vendor.objects.create(
            name="Other Vendor",
            onboarding_status="ACTIVE",
        )
        other_order = PurchaseOrder.objects.create(
            po_number="PO-OTHER",
            vendor=other_vendor,
        )
        response = self.client.patch(
            f"/api/invoices/{self.invoice.pk}/",
            {"purchase_order": other_order.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("purchase_order", response.data)

    def test_creates_purchase_order_with_nested_lines(self):
        response = self.client.post(
            self.endpoint,
            {
                "po_number": "PO-CREATED",
                "vendor": self.vendor.pk,
                "currency": "INR",
                "line_items": [
                    {
                        "line_number": 1,
                        "description": "Office Chairs",
                        "quantity": "2",
                        "unit_price": "500.00",
                        "line_total": "1000.00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total_amount"], Decimal("1000.00"))
        self.assertEqual(response.data["line_items"][0]["description"], "Office Chairs")
        audit_event = AuditEvent.objects.get(
            entity_type="PURCHASE_ORDER",
            entity_label="PO-CREATED",
            action="CREATED",
        )
        self.assertEqual(audit_event.changes["line_count"], 1)

    def test_rejects_purchase_order_for_inactive_vendor(self):
        self.vendor.onboarding_status = "PENDING"
        self.vendor.save()
        response = self.client.post(
            self.endpoint,
            {
                "po_number": "PO-INACTIVE",
                "vendor": self.vendor.pk,
                "currency": "INR",
                "line_items": [
                    {
                        "line_number": 1,
                        "description": "Office Chairs",
                        "quantity": "2",
                        "unit_price": "500.00",
                        "line_total": "1000.00",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("vendor", response.data)

    def test_invoice_detail_includes_saved_line_items(self):
        invoice = Invoice.objects.create(
            invoice_number="INV-LINES",
            vendor_name="Line Item Supplier",
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            line_number=1,
            description="Consulting Services",
            quantity=Decimal("10"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("1000.00"),
        )

        response = self.client.get(f"/api/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["line_items"]), 1)
        self.assertEqual(
            response.data["line_items"][0]["description"],
            "Consulting Services",
        )


class ThreeWayPurchaseOrderMatchingTests(APClerkTestCase):
    receipt_endpoint = "/api/invoices/goods-receipts/"

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.create(
            name="Acme Corp.",
            onboarding_status="ACTIVE",
        )
        self.purchase_order = PurchaseOrder.objects.create(
            po_number="PO-RECEIPT-100",
            vendor=self.vendor,
            currency="INR",
        )
        self.consulting_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            line_number=1,
            description="Consulting Services",
            quantity=Decimal("10"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("1000.00"),
        )
        self.software_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            line_number=2,
            description="Software License",
            quantity=Decimal("1"),
            unit_price=Decimal("250.00"),
            line_total=Decimal("250.00"),
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-RECEIPT-100",
            vendor_name="Acme Corporation",
            subtotal=Decimal("1250.00"),
            total_amount=Decimal("1250.00"),
            currency="INR",
            purchase_order=self.purchase_order,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            description="Consulting Services",
            quantity=Decimal("10"),
            unit_price=Decimal("100.00"),
            line_total=Decimal("1000.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=2,
            description="Software License",
            quantity=Decimal("1"),
            unit_price=Decimal("250.00"),
            line_total=Decimal("250.00"),
        )

    def create_receipt(self, consulting_quantity, software_quantity):
        receipt = GoodsReceipt.objects.create(
            receipt_number="GRN-TEST-100",
            purchase_order=self.purchase_order,
        )
        GoodsReceiptLineItem.objects.create(
            goods_receipt=receipt,
            purchase_order_line=self.consulting_line,
            quantity_received=consulting_quantity,
        )
        GoodsReceiptLineItem.objects.create(
            goods_receipt=receipt,
            purchase_order_line=self.software_line,
            quantity_received=software_quantity,
        )

    def test_missing_receipt_is_reported(self):
        result = compare_invoice_to_purchase_order_and_receipts(
            self.invoice,
            self.purchase_order,
        )

        self.assertEqual(result["status"], "MISMATCH")
        self.assertIn(
            "goods_receipt_missing",
            {item["type"] for item in result["discrepancies"]},
        )

    def test_fully_received_invoice_is_three_way_matched(self):
        response = self.client.post(
            self.receipt_endpoint,
            {
                "receipt_number": "GRN-API-100",
                "purchase_order": self.purchase_order.pk,
                "receipt_date": "2025-08-20",
                "line_items": [
                    {
                        "purchase_order_line": self.consulting_line.pk,
                        "quantity_received": "10",
                    },
                    {
                        "purchase_order_line": self.software_line.pk,
                        "quantity_received": "1",
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["line_items"]), 2)
        receipt_audit = AuditEvent.objects.get(
            entity_type="GOODS_RECEIPT",
            entity_label="GRN-API-100",
            action="CREATED",
        )
        self.assertEqual(receipt_audit.changes["line_count"], 2)

        invoice_response = self.client.get(
            f"/api/invoices/{self.invoice.pk}/"
        )
        self.assertEqual(
            invoice_response.data["three_way_match"]["status"],
            "THREE_WAY_MATCHED",
        )

        receipt_list = self.client.get(self.receipt_endpoint)
        self.assertEqual(receipt_list.status_code, 200)
        self.assertEqual(receipt_list.data[0]["receipt_number"], "GRN-API-100")

    def test_partial_receipt_flags_invoice_quantity_exceeding_received(self):
        self.create_receipt(Decimal("5"), Decimal("1"))

        result = compare_invoice_to_purchase_order_and_receipts(
            self.invoice,
            self.purchase_order,
        )

        self.assertIn(
            "received_quantity_too_low",
            {item["type"] for item in result["discrepancies"]},
        )

    def test_excess_receipt_flags_quantity_above_po(self):
        self.create_receipt(Decimal("11"), Decimal("1"))

        result = compare_invoice_to_purchase_order_and_receipts(
            self.invoice,
            self.purchase_order,
        )

        self.assertIn(
            "received_quantity_exceeds_po",
            {item["type"] for item in result["discrepancies"]},
        )

    def test_receipt_rejects_line_from_another_purchase_order(self):
        other_order = PurchaseOrder.objects.create(
            po_number="PO-OTHER-RECEIPT",
            vendor=self.vendor,
        )
        other_line = PurchaseOrderLineItem.objects.create(
            purchase_order=other_order,
            line_number=1,
            description="Other item",
            quantity=Decimal("1"),
            unit_price=Decimal("1.00"),
            line_total=Decimal("1.00"),
        )

        response = self.client.post(
            self.receipt_endpoint,
            {
                "receipt_number": "GRN-INVALID",
                "purchase_order": self.purchase_order.pk,
                "line_items": [
                    {
                        "purchase_order_line": other_line.pk,
                        "quantity_received": "1",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            GoodsReceipt.objects.filter(receipt_number="GRN-INVALID").exists()
        )

    def test_receipt_rejects_zero_received_quantity(self):
        response = self.client.post(
            self.receipt_endpoint,
            {
                "receipt_number": "GRN-ZERO",
                "purchase_order": self.purchase_order.pk,
                "line_items": [
                    {
                        "purchase_order_line": self.consulting_line.pk,
                        "quantity_received": "0",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class InvoiceApprovalWorkflowTests(APClerkTestCase):
    endpoint = "/api/invoices/"

    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.create(
            name="Approval Vendor",
            gstin="27ABCDE1234F1Z5",
            onboarding_status="ACTIVE",
        )
        self.purchase_order = PurchaseOrder.objects.create(
            po_number="PO-APPROVAL-1",
            vendor=self.vendor,
            currency="INR",
        )
        self.po_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            line_number=1,
            description="Office Chairs",
            quantity=Decimal("2"),
            unit_price=Decimal("500.00"),
            line_total=Decimal("1000.00"),
        )
        self.invoice = Invoice.objects.create(
            invoice_number="INV-APPROVAL-1",
            vendor_name="Approval Vendor",
            vendor_gst_number="27ABCDE1234F1Z5",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1000.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("1000.00"),
            currency="INR",
            purchase_order=self.purchase_order,
            status="PENDING_REVIEW",
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            description="Office Chairs",
            quantity=Decimal("2"),
            unit_price=Decimal("500.00"),
            line_total=Decimal("1000.00"),
        )
        receipt = GoodsReceipt.objects.create(
            receipt_number="GRN-APPROVAL-1",
            purchase_order=self.purchase_order,
        )
        GoodsReceiptLineItem.objects.create(
            goods_receipt=receipt,
            purchase_order_line=self.po_line,
            quantity_received=Decimal("2"),
        )

    def submit(self):
        return self.client.post(
            f"{self.endpoint}{self.invoice.pk}/submit-for-approval/",
            {"comment": "Reviewed and ready."},
            format="json",
        )

    def test_submit_requires_valid_invoice_and_three_way_match(self):
        self.invoice.total_amount = Decimal("1200.00")
        self.invoice.save()
        response = self.submit()

        self.assertEqual(response.status_code, 400)
        self.assertIn("validation_errors", response.data)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PENDING_REVIEW")
        self.assertFalse(
            InvoiceApprovalHistory.objects.filter(invoice=self.invoice).exists()
        )

    def test_submit_requires_purchase_order_and_receipt(self):
        self.invoice.purchase_order = None
        self.invoice.save()
        response = self.submit()

        self.assertEqual(response.status_code, 400)
        self.assertIn("three_way_match", response.data)

    def test_submit_for_approval_records_history_and_changes_status(self):
        response = self.submit()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "PENDING_APPROVAL")
        self.assertEqual(len(response.data["approval_history"]), 1)
        self.assertEqual(
            response.data["approval_history"][0]["action"],
            "SUBMITTED",
        )
        self.assertEqual(
            response.data["approval_history"][0]["comment"],
            "Reviewed and ready.",
        )
        self.assertEqual(
            response.data["approval_history"][0]["actor_name"],
            "ap-clerk",
        )
        audit_event = AuditEvent.objects.get(
            entity_type="INVOICE",
            entity_id=str(self.invoice.pk),
            action="APPROVAL_SUBMITTED",
        )
        self.assertEqual(
            audit_event.changes["status"],
            {"from": "PENDING_REVIEW", "to": "PENDING_APPROVAL"},
        )

    def test_approval_is_rechecked_and_records_authenticated_actor(self):
        self.submit()
        user = get_user_model().objects.create_user(username="ap-reviewer")
        user.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=user)
        response = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/approve/",
            {"comment": "All documents verified."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "APPROVED")
        self.assertEqual(response.data["approval_history"][-1]["action"], "APPROVED")
        self.assertEqual(
            response.data["approval_history"][-1]["actor_name"],
            "ap-reviewer",
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "APPROVED")

    def test_all_matching_approval_roles_must_approve(self):
        InvoiceApprovalRule.objects.create(
            name="Additional payment clerk review",
            minimum_amount=Decimal("1000.00"),
            maximum_amount=None,
            approver_roles=["Payment Clerk"],
            reminder_after_hours=12,
            escalation_after_hours=48,
        )
        submitted = self.submit()
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(
            set(
                self.invoice.approval_steps.values_list("role", flat=True)
            ),
            {"Approver", "Payment Clerk"},
        )

        approver = get_user_model().objects.create_user(
            username="parallel-approver"
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=approver)
        first_approval = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/approve/",
            {"comment": "Approval role one completed."},
            format="json",
        )
        self.assertEqual(first_approval.status_code, 200)
        self.assertEqual(first_approval.data["status"], "PENDING_APPROVAL")

        payment_clerk = get_user_model().objects.create_user(
            username="parallel-payment-clerk"
        )
        payment_clerk.groups.add(Group.objects.get(name="Payment Clerk"))
        self.client.force_authenticate(user=payment_clerk)
        second_approval = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/approve/",
            {"comment": "Approval role two completed."},
            format="json",
        )
        self.assertEqual(second_approval.status_code, 200)
        self.assertEqual(second_approval.data["status"], "APPROVED")
        self.assertEqual(
            {step["status"] for step in second_approval.data["approval_steps"]},
            {"APPROVED"},
        )

    def test_reminder_and_escalation_command_is_idempotent(self):
        self.submit()
        step = InvoiceApprovalStep.objects.get(
            invoice=self.invoice,
            role="Approver",
        )
        step.created_at = timezone.now() - timedelta(hours=80)
        step.save(update_fields=["created_at"])

        approver = get_user_model().objects.create_user(
            username="reminder-approver"
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        administrator = get_user_model().objects.create_user(
            username="reminder-admin"
        )
        administrator.groups.add(Group.objects.get(name="Administrator"))

        call_command("process_approval_notifications", stdout=StringIO())
        call_command("process_approval_notifications", stdout=StringIO())

        self.assertEqual(
            ApprovalNotification.objects.filter(approval_step=step).count(),
            2,
        )
        self.client.force_authenticate(user=approver)
        approver_notices = self.client.get(
            "/api/invoices/approval-notifications/"
        )
        self.assertEqual(approver_notices.status_code, 200)
        self.assertEqual(
            [notice["notification_type"] for notice in approver_notices.data],
            ["REMINDER"],
        )
        read_response = self.client.post(
            f"/api/invoices/approval-notifications/{approver_notices.data[0]['id']}/read/",
            {},
            format="json",
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertIsNotNone(read_response.data["read_at"])

        self.client.force_authenticate(user=administrator)
        admin_notices = self.client.get(
            "/api/invoices/approval-notifications/"
        )
        self.assertEqual(
            [notice["notification_type"] for notice in admin_notices.data],
            ["ESCALATION"],
        )

    def test_approval_rechecks_receipt_quantities_after_submission(self):
        self.submit()
        receipt_line = GoodsReceiptLineItem.objects.get(
            goods_receipt__receipt_number="GRN-APPROVAL-1"
        )
        receipt_line.quantity_received = Decimal("1")
        receipt_line.save()
        approver = get_user_model().objects.create_user(
            username="ap-approver-check"
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=approver)

        response = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/approve/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("validation_errors", response.data)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PENDING_APPROVAL")

    def test_rejection_requires_reason_and_is_logged(self):
        self.submit()
        approver = get_user_model().objects.create_user(
            username="ap-rejector"
        )
        approver.groups.add(Group.objects.get(name="Approver"))
        self.client.force_authenticate(user=approver)
        missing_reason = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/reject/",
            {"comment": "  "},
            format="json",
        )
        self.assertEqual(missing_reason.status_code, 400)

        response = self.client.post(
            f"{self.endpoint}{self.invoice.pk}/reject/",
            {"comment": "Quantity differs from delivery note."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "REJECTED")
        self.assertEqual(response.data["approval_history"][-1]["action"], "REJECTED")

    def test_invoice_fields_and_direct_status_updates_are_locked_in_queue(self):
        self.submit()
        update_response = self.client.patch(
            f"{self.endpoint}{self.invoice.pk}/",
            {"total_amount": "1200.00"},
            format="json",
        )
        status_response = self.client.patch(
            f"{self.endpoint}{self.invoice.pk}/",
            {"status": "APPROVED"},
            format="json",
        )

        self.assertEqual(update_response.status_code, 400)
        self.assertEqual(status_response.status_code, 400)


class InvoicePaymentWorkflowTests(APClerkTestCase):
    endpoint = "/api/invoices/"
    payment_list_endpoint = "/api/invoices/payments/"

    def setUp(self):
        super().setUp()
        self.test_user.groups.add(Group.objects.get(name="Payment Clerk"))
        self.invoice = Invoice.objects.create(
            invoice_number="INV-PAY-100",
            vendor_name="Payment Vendor",
            invoice_date=date(2025, 8, 10),
            subtotal=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            status="APPROVED",
        )

    def record_payment(self, **overrides):
        data = {
            "amount": "400.00",
            "payment_date": "2025-08-20",
            "payment_reference": "UTR-PAY-100",
            "payment_method": "BANK_TRANSFER",
            "notes": "First installment",
        }
        data.update(overrides)
        return self.client.post(
            f"{self.endpoint}{self.invoice.pk}/payments/",
            data,
            format="json",
        )

    def test_payment_request_is_generated_once_and_closed_after_payment(self):
        endpoint = "/api/invoices/payment-requests/"
        response = self.client.post(
            endpoint,
            {"invoice": self.invoice.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["requested_amount"], "1000.00")
        self.assertEqual(response.data["status"], "REQUESTED")
        self.assertEqual(PaymentRequest.objects.count(), 1)
        payment_request = PaymentRequest.objects.get(pk=response.data["id"])

        duplicate = self.client.post(
            endpoint,
            {"invoice": self.invoice.pk},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)

        payment = self.record_payment(
            amount="1000.00",
            payment_reference="UTR-PAY-REQUESTED",
        )
        self.assertEqual(payment.status_code, 201)
        payment_request.refresh_from_db()
        self.assertEqual(payment_request.status, "PAID")

    def test_partial_payment_records_history_and_keeps_invoice_approved(self):
        response = self.record_payment()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["amount"], "400.00")
        self.assertEqual(response.data["invoice"], self.invoice.pk)
        self.assertEqual(response.data["actor_name"], "ap-clerk")
        payment_audit = AuditEvent.objects.get(
            entity_type="PAYMENT",
            entity_label="UTR-PAY-100",
            action="RECORDED",
        )
        self.assertEqual(payment_audit.changes["amount"], "400.00")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "APPROVED")

    def test_full_payment_marks_invoice_paid_and_appears_in_invoice_data(self):
        response = self.record_payment(
            amount="1000.00",
            payment_reference="UTR-PAY-FULL",
        )

        self.assertEqual(response.status_code, 201)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PAID")
        self.assertTrue(
            AuditEvent.objects.filter(
                entity_type="INVOICE",
                entity_id=str(self.invoice.pk),
                action="STATUS_CHANGED",
            ).exists()
        )

        invoice_response = self.client.get(
            f"{self.endpoint}{self.invoice.pk}/"
        )
        self.assertEqual(len(invoice_response.data["payments"]), 1)
        self.assertEqual(
            invoice_response.data["payments"][0]["payment_reference"],
            "UTR-PAY-FULL",
        )

    def test_multiple_partial_payments_mark_paid_only_when_fully_settled(self):
        first = self.record_payment()
        second = self.record_payment(
            amount="600.00",
            payment_reference="UTR-PAY-101",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PAID")
        self.assertEqual(InvoicePayment.objects.filter(invoice=self.invoice).count(), 2)

    def test_rejects_overpayment_and_duplicate_reference(self):
        self.record_payment()
        overpayment = self.record_payment(
            amount="601.00",
            payment_reference="UTR-PAY-OVER",
        )
        duplicate = self.record_payment(
            amount="100.00",
            payment_reference="UTR-PAY-100",
        )

        self.assertEqual(overpayment.status_code, 400)
        self.assertIn("amount", overpayment.data)
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("payment_reference", duplicate.data)
        self.assertEqual(InvoicePayment.objects.filter(invoice=self.invoice).count(), 1)

    def test_rejects_payment_for_invoice_not_approved(self):
        self.invoice.status = "PENDING_APPROVAL"
        self.invoice.save()

        response = self.record_payment()

        self.assertEqual(response.status_code, 400)
        self.assertIn("invoice", response.data)

    def test_rejects_zero_and_future_dated_payments(self):
        zero_payment = self.record_payment(
            amount="0",
            payment_reference="UTR-PAY-ZERO",
        )
        future_payment = self.record_payment(
            payment_date="2099-01-01",
            payment_reference="UTR-PAY-FUTURE",
        )

        self.assertEqual(zero_payment.status_code, 400)
        self.assertIn("amount", zero_payment.data)
        self.assertEqual(future_payment.status_code, 400)
        self.assertIn("payment_date", future_payment.data)

    def test_lists_payments_and_records_authenticated_user(self):
        user = get_user_model().objects.create_user(username="ap-payments")
        user.groups.add(Group.objects.get(name="Payment Clerk"))
        self.client.force_authenticate(user=user)
        response = self.record_payment()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["actor_name"], "ap-payments")
        list_response = self.client.get(self.payment_list_endpoint)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)

    def test_invoice_with_payments_cannot_be_deleted(self):
        self.record_payment()

        response = self.client.delete(
            f"{self.endpoint}{self.invoice.pk}/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=self.invoice.pk).exists())
