"""SaaS subscription lifecycle: trial, renewal, lapse, and invoice lead time.

`past_due` is *derived*, not written by a scheduler: a subscription whose period has
ended with no settled next-period Invoice is past due the moment the date rolls
over. Nothing has to run for that to become true, which is the same
derived-over-stored choice made for membership status (D3).

The stored `status` column still exists and is written on settlement, because the
billing history and gateway reference live on that row. `effective_status()` is what
the authorization layer reads.
"""
from __future__ import annotations

import calendar
import datetime
import logging

from django.conf import settings
from django.db import transaction

from core.models import Invoice, SaasPlan, SaasSubscription

logger = logging.getLogger("core.payments")

STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELLED = "cancelled"

DEFAULT_TRIAL_DAYS = 14
DEFAULT_INVOICE_LEAD_DAYS = 7


def trial_days():
    return int(getattr(settings, "SAAS_TRIAL_DAYS", DEFAULT_TRIAL_DAYS))


def invoice_lead_days():
    return int(getattr(settings, "SAAS_INVOICE_LEAD_DAYS", DEFAULT_INVOICE_LEAD_DAYS))


# ============ CALENDAR ARITHMETIC ============

def add_months(day, months):
    """Advance a date by whole months, clamping to the end of the target month.

    Billing on the 31st must not skip February. Clamping to the 28th/29th/30th is
    the standard subscription convention and keeps the anniversary stable for every
    month that is long enough.
    """
    months = int(months)
    zero_based = day.month - 1 + months
    year = day.year + zero_based // 12
    month = zero_based % 12 + 1
    day_of_month = min(day.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day_of_month)


# ============ CREATION ============

@transaction.atomic
def start_trial(gym, plan=None, *, actor=None, start=None):
    """Put a new Gym on a trialing subscription (21.3).

    Falls back to the cheapest active SaasPlan when none is named. Absence of a
    seeded catalogue is not a registration failure: the Gym is created without a
    subscription and simply cannot add members until one is attached, which the seat
    gate already enforces with a 402.
    """
    from core.services.audit import record_create

    if plan is None:
        plan = SaasPlan.objects.filter(is_active=True).order_by("price").first()
    if plan is None:
        logger.warning("no active SaasPlan; gym_id=%s created without a subscription", gym.pk)
        return None

    start = start or gym.today()
    subscription = SaasSubscription.objects.create(
        gym=gym,
        plan=plan,
        status=STATUS_TRIALING,
        start_date=start,
        current_period_end=start + datetime.timedelta(days=trial_days()),
    )
    record_create(subscription, actor=actor, gym=gym)
    return subscription


# ============ RENEWAL ============

@transaction.atomic
def advance_period(subscription, *, actor=None):
    """Settlement moves the subscription to `active` and rolls the period forward.

    Advancing from the stored `current_period_end` rather than from today keeps the
    billing anniversary stable even when an invoice is paid late (21.4).
    """
    from core.services.audit import AuditedChange

    with AuditedChange(
        subscription,
        actor=actor,
        gym=subscription.gym,
        fields=["status", "current_period_end"],
    ):
        subscription.status = STATUS_ACTIVE
        subscription.current_period_end = add_months(
            subscription.current_period_end, subscription.plan.billing_interval_months
        )
        subscription.save(update_fields=["status", "current_period_end"])
    return subscription


# ============ DERIVED STATE ============

def has_settled_invoice_for_next_period(subscription):
    """True when the period after `current_period_end` is already paid for."""
    return Invoice.objects.filter(
        saas_subscription=subscription,
        status="settled",
        issue_date__gt=subscription.current_period_end,
        deleted_at__isnull=True,
    ).exists()


def effective_status(subscription, today=None):
    """The status the authorization layer should act on (21.6).

    A cancelled subscription stays cancelled. Anything else whose period has ended
    without a settled next-period Invoice is `past_due`, computed rather than
    scheduled.
    """
    if subscription is None:
        return None
    if subscription.status == STATUS_CANCELLED:
        return STATUS_CANCELLED

    today = today or subscription.gym.today()
    if today > subscription.current_period_end and not has_settled_invoice_for_next_period(
        subscription
    ):
        return STATUS_PAST_DUE
    return subscription.status


@transaction.atomic
def mark_past_due_if_lapsed(subscription, *, actor=None, today=None):
    """Persist the derived `past_due` so the stored row stops disagreeing.

    Optional: `effective_status()` is already correct without it. Called on the
    read path so the database converges without a scheduled job.
    """
    from core.services.audit import AuditedChange

    derived = effective_status(subscription, today)
    if derived == subscription.status:
        return subscription

    with AuditedChange(subscription, actor=actor, gym=subscription.gym, fields=["status"]):
        subscription.status = derived
        subscription.save(update_fields=["status"])
    return subscription


def cancel(subscription, *, actor=None):
    from core.services.audit import AuditedChange

    with AuditedChange(subscription, actor=actor, gym=subscription.gym, fields=["status"]):
        subscription.status = STATUS_CANCELLED
        subscription.save(update_fields=["status"])
    return subscription


# ============ INVOICE LEAD TIME ============

def invoice_due_date(subscription):
    """The date the next period's Invoice should be issued (21.7)."""
    return subscription.current_period_end - datetime.timedelta(days=invoice_lead_days())


def should_issue_invoice(subscription, today=None):
    """True once the lead window has opened and no open/settled Invoice exists yet."""
    if subscription is None or subscription.status == STATUS_CANCELLED:
        return False

    today = today or subscription.gym.today()
    if today < invoice_due_date(subscription):
        return False

    return not Invoice.objects.filter(
        saas_subscription=subscription,
        status__in=["open", "settled"],
        issue_date__gte=invoice_due_date(subscription),
        deleted_at__isnull=True,
    ).exists()


@transaction.atomic
def ensure_period_invoice(subscription, *, actor=None, today=None):
    """Issue the upcoming period's Invoice when the lead window has opened.

    Called from the read path (the owner's invoice list, `/api/me`) rather than from
    a scheduler, so Phase 1 needs no Celery beat.
    """
    from core.services.invoicing import issue_saas_invoice

    if not should_issue_invoice(subscription, today):
        return None
    return issue_saas_invoice(subscription, actor=actor)
