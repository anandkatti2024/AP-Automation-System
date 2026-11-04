import hashlib
import imaplib
from email import policy
from email.parser import BytesParser

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from invoices.models import ImportedEmail
from invoices.views import EmailInvoiceImportView, import_email_message


class Command(BaseCommand):
    help = "Import supported invoice attachments from unread IMAP messages."
    max_email_size = EmailInvoiceImportView.max_email_size

    def handle(self, *args, **options):
        if not all((
            settings.IMAP_HOST,
            settings.IMAP_USERNAME,
            settings.IMAP_PASSWORD,
        )):
            raise CommandError(
                "Set AP_IMAP_HOST, AP_IMAP_USERNAME, and AP_IMAP_PASSWORD."
            )

        try:
            connection = imaplib.IMAP4_SSL(
                settings.IMAP_HOST,
                settings.IMAP_PORT,
                timeout=30,
            )
        except (OSError, imaplib.IMAP4.error) as error:
            raise CommandError("Could not connect to the configured IMAP server.") from error

        try:
            self._poll(connection)
        finally:
            try:
                connection.logout()
            except imaplib.IMAP4.error as error:
                self.stderr.write(f"Warning: could not close IMAP connection: {error}")

    def _poll(self, connection):
        mailbox_identity = "\0".join((
            settings.IMAP_HOST.casefold(),
            settings.IMAP_USERNAME.casefold(),
            settings.IMAP_MAILBOX.casefold(),
        ))
        mailbox_key = hashlib.sha256(
            mailbox_identity.encode("utf-8")
        ).hexdigest()
        try:
            status, _ = connection.login(
                settings.IMAP_USERNAME,
                settings.IMAP_PASSWORD,
            )
        except imaplib.IMAP4.error as error:
            raise CommandError("IMAP authentication failed.") from error
        if status != "OK":
            raise CommandError("IMAP authentication failed.")

        status, _ = connection.select(settings.IMAP_MAILBOX)
        if status != "OK":
            raise CommandError("Could not select the configured IMAP mailbox.")
        _, uid_validity_data = connection.response("UIDVALIDITY")
        if not uid_validity_data:
            raise CommandError(
                "The IMAP server did not provide a mailbox UID validity value."
            )
        uid_validity = uid_validity_data[0].decode("ascii")

        status, search_data = connection.uid("search", None, "UNSEEN")
        if status != "OK":
            raise CommandError("Could not search the IMAP mailbox.")

        uids = search_data[0].split() if search_data and search_data[0] else []
        imported_count = 0
        processed_count = 0
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii")
            receipt = ImportedEmail.objects.filter(
                mailbox=mailbox_key,
                uid_validity=uid_validity,
                uid=uid,
            ).first()
            if receipt:
                self._mark_seen(connection, uid_bytes)
                continue

            status, fetched = connection.uid(
                "fetch",
                uid_bytes,
                "(BODY.PEEK[] RFC822.SIZE)",
            )
            if status != "OK":
                self.stderr.write(f"Could not fetch unread message UID {uid}.")
                continue
            raw_message = next(
                (
                    part[1]
                    for part in fetched
                    if isinstance(part, tuple) and isinstance(part[1], bytes)
                ),
                None,
            )
            if raw_message is None:
                self.stderr.write(f"IMAP returned no message content for UID {uid}.")
                continue

            message = BytesParser(policy=policy.default).parsebytes(raw_message)
            if len(raw_message) > self.max_email_size:
                result = {
                    "imported": [],
                    "unsupported_attachments": [
                        "Email exceeds the 25 MB import limit."
                    ],
                    "email_subject": str(message.get("subject", ""))[:255],
                }
            else:
                with transaction.atomic():
                    result = import_email_message(
                        message,
                        actor=None,
                        require_attachment=False,
                    )
                    ImportedEmail.objects.create(
                        mailbox=mailbox_key,
                        uid_validity=uid_validity,
                        uid=uid,
                        message_id=str(message.get("Message-ID", ""))[:255],
                        invoice_ids=[
                            item["id"] for item in result["imported"]
                        ],
                    )
                imported_count += len(result["imported"])

            if len(raw_message) > self.max_email_size:
                ImportedEmail.objects.create(
                    mailbox=mailbox_key,
                    uid_validity=uid_validity,
                    uid=uid,
                    message_id=str(message.get("Message-ID", ""))[:255],
                )
            self._mark_seen(connection, uid_bytes)
            processed_count += 1
            if result["unsupported_attachments"]:
                self.stderr.write(
                    f"IMAP UID {uid}: skipped "
                    f"{len(result['unsupported_attachments'])} attachment(s)."
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {processed_count} unread email(s); "
                f"imported {imported_count} invoice attachment(s)."
            )
        )

    @staticmethod
    def _mark_seen(connection, uid):
        status, _ = connection.uid("store", uid, "+FLAGS", r"(\Seen)")
        if status != "OK":
            raise CommandError("Could not mark a processed email as read.")
