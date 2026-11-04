from datetime import date, datetime
from decimal import Decimal

from .models import AuditEvent


def audit_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def snapshot(instance, fields):
    return {
        field: audit_value(getattr(instance, field))
        for field in fields
    }


def changed_fields(before, after):
    return {
        field: {"from": before.get(field), "to": after.get(field)}
        for field in after
        if before.get(field) != after.get(field)
    }


def record_audit_event(
    *,
    actor,
    entity_type,
    entity_id,
    entity_label,
    action,
    changes=None,
):
    authenticated_actor = actor if actor and actor.is_authenticated else None
    actor_name = (
        authenticated_actor.get_username()
        if authenticated_actor
        else "System"
    )
    return AuditEvent.objects.create(
        entity_type=entity_type,
        entity_id=str(entity_id),
        entity_label=str(entity_label)[:255],
        action=action,
        changes=changes or {},
        actor=authenticated_actor,
        actor_name=actor_name,
    )
