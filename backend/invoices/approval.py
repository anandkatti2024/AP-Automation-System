from .models import InvoiceApprovalRule


def approval_requirements_for_invoice(invoice):
    rules = InvoiceApprovalRule.objects.filter(
        active=True,
        minimum_amount__lte=invoice.total_amount,
    )
    rules = rules.filter(
        models_q_maximum(invoice.total_amount)
    )
    matched_rules = list(rules)
    if not matched_rules:
        return {
            "roles": ["Approver"],
            "reminder_after_hours": 24,
            "escalation_after_hours": 72,
        }

    roles = sorted({
        role
        for rule in matched_rules
        for role in rule.approver_roles
    })
    if not roles:
        raise ValueError(
            "At least one active approval rule must define an approver role."
        )
    return {
        "roles": roles,
        "reminder_after_hours": min(
            rule.reminder_after_hours for rule in matched_rules
        ),
        "escalation_after_hours": min(
            rule.escalation_after_hours for rule in matched_rules
        ),
    }


def models_q_maximum(amount):
    from django.db.models import Q

    return Q(maximum_amount__isnull=True) | Q(maximum_amount__gte=amount)
