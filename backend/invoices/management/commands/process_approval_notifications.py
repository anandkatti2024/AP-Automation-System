from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from invoices.models import ApprovalNotification, InvoiceApprovalStep


class Command(BaseCommand):
    help = "Create in-app reminders and administrator escalations for overdue approvals."

    def handle(self, *args, **options):
        now = timezone.now()
        created = 0
        pending_steps = InvoiceApprovalStep.objects.filter(
            status="PENDING",
            invoice__status="PENDING_APPROVAL",
        ).select_related("invoice")

        for step in pending_steps:
            elapsed = now - step.created_at
            notifications = []
            if elapsed >= timedelta(hours=step.reminder_after_hours):
                notifications.append((
                    "REMINDER",
                    Group.objects.filter(name=step.role).values_list(
                        "user__id",
                        flat=True,
                    ),
                    f"Invoice {step.invoice.invoice_number} is awaiting "
                    f"your {step.role} approval.",
                ))
            if elapsed >= timedelta(hours=step.escalation_after_hours):
                notifications.append((
                    "ESCALATION",
                    Group.objects.filter(name="Administrator").values_list(
                        "user__id",
                        flat=True,
                    ),
                    f"Approval for invoice {step.invoice.invoice_number} "
                    f"has exceeded its escalation target.",
                ))

            for notification_type, recipient_ids, message in notifications:
                for user_id in recipient_ids:
                    _, was_created = ApprovalNotification.objects.get_or_create(
                        approval_step=step,
                        recipient_id=user_id,
                        notification_type=notification_type,
                        defaults={"message": message},
                    )
                    created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created} approval notification(s)."
            )
        )
