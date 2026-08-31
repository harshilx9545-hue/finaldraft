"""AuditRecord writer.

`changes` records before/after values for *exactly* the fields that changed, not
the whole row. A diff of everything makes it impossible to see at a glance what a
given operation actually did, and Property 25 asserts the narrow shape.

Records are append-only by manager (`AppendOnlyManager` raises on `update()` and
`delete()`), read-only in the admin, and exposed by no endpoint.
"""
from __future__ import annotations

import datetime
import decimal
import uuid

from core.models import AuditRecord

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_SOFT_DELETE = "soft_delete"
ACTION_RESTORE = "restore"
ACTION_SETTLE = "settle"
ACTION_REFUND = "refund"
ACTION_VOID = "void"
ACTION_ADMIN_WRITE = "admin_write"
#: An automated recovery discount amended an open invoice. Distinct from a plain
#: `update` because the recovery agent's one-discount-per-invoice guard counts these
#: records: it needs evidence written inside the tool's own transaction, not evidence
#: written by whoever happened to call the tool.
ACTION_RECOVERY_DISCOUNT = "recovery_discount"

#: Never written into `changes`, whatever the caller passes.
REDACTED_FIELDS = frozenset(
    {
        "password",
        "token_hash",
        "idempotency_key",
        "raw_payload",
        "gateway_signature",
    }
)


def _jsonable(value):
    """Coerce a field value into something JSONField can store losslessly enough."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, decimal.Decimal):
        # str, not float: an invoice total must not acquire binary rounding error
        # on its way into the audit trail.
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    # Model instance or anything else: record its primary key if it has one.
    pk = getattr(value, "pk", None)
    return pk if pk is not None else str(value)


def model_label(instance_or_model):
    model = (
        instance_or_model
        if isinstance(instance_or_model, type)
        else type(instance_or_model)
    )
    return f"{model._meta.app_label}.{model.__name__}"


def snapshot(instance, fields=None):
    """Current values of `fields` (or every concrete local field) on an instance."""
    if fields is None:
        fields = [
            field.attname
            for field in instance._meta.concrete_fields
            if field.attname not in REDACTED_FIELDS
        ]
    return {name: getattr(instance, name, None) for name in fields}


def diff(before, after):
    """`{field: [before, after]}` for the keys whose values differ."""
    changed = {}
    for name in set(before) | set(after):
        if name in REDACTED_FIELDS:
            continue
        old = _jsonable(before.get(name))
        new = _jsonable(after.get(name))
        if old != new:
            changed[name] = [old, new]
    return changed


def record(action, instance, *, actor=None, gym=None, changes=None, fields=None):
    """Write one AuditRecord. Returns it so callers can assert in tests.

    `gym` defaults to the instance's own Gym when it has one, so a caller cannot
    accidentally file a tenant record under no tenant.
    """
    if gym is None:
        gym = getattr(instance, "gym", None)
        if gym is None:
            member = getattr(instance, "member", None)
            gym = getattr(member, "gym", None)

    if changes is None:
        if action == ACTION_CREATE:
            changes = {
                name: [None, _jsonable(value)]
                for name, value in snapshot(instance, fields).items()
            }
        else:
            changes = {}

    return AuditRecord.objects.create(
        actor_user=actor if getattr(actor, "pk", None) else None,
        gym=gym,
        action=action,
        model_label=model_label(instance),
        object_id=str(instance.pk),
        changes=changes,
    )


def record_create(instance, *, actor=None, gym=None, fields=None):
    return record(ACTION_CREATE, instance, actor=actor, gym=gym, fields=fields)


def record_update(instance, before, *, actor=None, gym=None, fields=None):
    """Audit an update, recording only the fields that actually changed."""
    changes = diff(before, snapshot(instance, fields or list(before)))
    if not changes:
        return None
    return record(ACTION_UPDATE, instance, actor=actor, gym=gym, changes=changes)


def record_soft_delete(instance, *, actor=None, gym=None):
    return record(
        ACTION_SOFT_DELETE,
        instance,
        actor=actor,
        gym=gym,
        changes={"deleted_at": [None, _jsonable(instance.deleted_at)]},
    )


def record_restore(instance, previous_deleted_at, *, actor=None, gym=None):
    return record(
        ACTION_RESTORE,
        instance,
        actor=actor,
        gym=gym,
        changes={"deleted_at": [_jsonable(previous_deleted_at), None]},
    )


class AuditedChange:
    """Context manager that snapshots before, and audits the diff after.

        with AuditedChange(invoice, actor=request.user):
            invoice.status = "settled"
            invoice.save(update_fields=["status"])
    """

    def __init__(self, instance, *, actor=None, gym=None, fields=None, action=ACTION_UPDATE):
        self.instance = instance
        self.actor = actor
        self.gym = gym
        self.fields = fields
        self.action = action
        self.before = None
        self.audit = None

    def __enter__(self):
        self.before = snapshot(self.instance, self.fields)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            return False
        changes = diff(self.before, snapshot(self.instance, self.fields))
        if changes:
            self.audit = record(
                self.action,
                self.instance,
                actor=self.actor,
                gym=self.gym,
                changes=changes,
            )
        return False
