"""Membership periods, derived status, and renewal chaining.

Status is never stored. It is computed from the period dates and the Invoice, so
there is no window in which a stored flag disagrees with the calendar and no
"expire memberships" job to schedule (D3, 20.1, 20.4).

Every date comparison uses the current date **in the Gym's timezone**. Using the
server date would expire an Asia/Kolkata membership five and a half hours early on
a UTC host, which is a real bug and not a rounding detail.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import Membership

STATUS_UPCOMING = "upcoming"
STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"

MIN_DURATION_DAYS = 1
MAX_DURATION_DAYS = 3650


# ============ PURE DATE ARITHMETIC ============

def end_date_for(start, duration_days):
    """Inclusive period: a 30-day plan starting on the 1st ends on the 30th.

    Inclusive because that is how a gym counts a month: the member trains on both
    the first and the last day. `end - start == duration - 1` is the invariant
    Property 27 pins down.
    """
    duration = int(duration_days)
    if duration < MIN_DURATION_DAYS or duration > MAX_DURATION_DAYS:
        raise ValidationError(
            {
                "plan": (
                    f"duration_days must be between {MIN_DURATION_DAYS} and "
                    f"{MAX_DURATION_DAYS}; got {duration}."
                ),
                "field": "plan",
            }
        )
    return start + datetime.timedelta(days=duration - 1)


def status_of(membership, today):
    """`upcoming` before the start, `active` through the end inclusive, else `expired`."""
    if today < membership.start_date:
        return STATUS_UPCOMING
    if today <= membership.end_date:
        return STATUS_ACTIVE
    return STATUS_EXPIRED


def periods_overlap(a_start, a_end, b_start, b_end):
    """Closed intervals intersect when each starts on or before the other's end."""
    return a_start <= b_end and b_start <= a_end


def today_for(gym):
    if gym is not None:
        return gym.today()
    return timezone.now().date()


# ============ DERIVED MEMBER STATE ============

def _is_paid(membership):
    """A period counts as paid when its Invoice is settled, or the plan is free.

    A zero-price plan produces no Invoice at all, so "no invoice" is a legitimate
    paid state for it and a definitively unpaid state for a priced plan (20.5).
    """
    invoice = membership.invoices.filter(deleted_at__isnull=True).order_by("-issue_date").first()
    if invoice is None:
        return Decimal(membership.plan.price) <= Decimal("0.00")
    return invoice.status == "settled"


def active_membership(profile, today=None):
    """The member's currently-active, paid Membership, or None."""
    today = today or today_for(profile.gym)
    candidates = Membership.objects.filter(
        member=profile, start_date__lte=today, end_date__gte=today
    ).select_related("plan")
    for membership in candidates:
        if _is_paid(membership):
            return membership
    return None


def is_member_active(profile, today=None):
    """True exactly when the member holds an active period that is paid for."""
    return active_membership(profile, today) is not None


def latest_end_date(profile):
    """End date of the member's furthest-reaching Membership, or None.

    Returned by `/api/me` alongside the computed active state (20.10). Uses the
    latest end date rather than the latest start so a back-dated renewal does not
    appear to shorten the membership.
    """
    row = (
        Membership.objects.filter(member=profile)
        .order_by("-end_date")
        .values_list("end_date", flat=True)
        .first()
    )
    return row


def next_start_date(profile, settled_on):
    """Where a newly settled renewal begins.

    Chained when the member still holds a period ending today or later, so a renewal
    paid early does not throw away the days already bought (20.6). Otherwise it
    begins on the settlement date, in the Gym's timezone (20.7).
    """
    latest = (
        Membership.objects.filter(member=profile, end_date__gte=settled_on)
        .order_by("-end_date")
        .values_list("end_date", flat=True)
        .first()
    )
    if latest is None:
        return settled_on
    return latest + datetime.timedelta(days=1)


# ============ CREATION ============

def assert_no_overlap(profile, start, end, exclude_pk=None):
    """Overlap is rejected in validation: SQLite has no range-exclusion constraint."""
    clashing = Membership.objects.filter(
        member=profile, start_date__lte=end, end_date__gte=start
    )
    if exclude_pk is not None:
        clashing = clashing.exclude(pk=exclude_pk)
    existing = clashing.order_by("start_date").first()
    if existing is not None:
        raise ValidationError(
            {
                "start_date": (
                    f"This period overlaps an existing membership running "
                    f"{existing.start_date}..{existing.end_date}."
                ),
                "field": "start_date",
            }
        )


@transaction.atomic
def create_membership(profile, plan, start=None, *, actor=None, issue_invoice=True):
    """Create one Membership, plus an Invoice when the plan is priced.

    A zero-price plan produces a Membership and no Invoice; a priced plan produces
    both, and the member is not active until that Invoice settles (20.12).
    """
    from core.services.audit import record_create

    if plan.gym_id != profile.gym_id:
        raise ValidationError(
            {"plan": "That membership plan belongs to a different gym.", "field": "plan"}
        )

    start = start or today_for(profile.gym)
    end = end_date_for(start, plan.duration_days)
    assert_no_overlap(profile, start, end)

    membership = Membership(member=profile, plan=plan, start_date=start)
    membership.save()  # end_date is computed in Membership.save()
    record_create(membership, actor=actor, gym=profile.gym)

    invoice = None
    if issue_invoice and Decimal(plan.price) > Decimal("0.00"):
        from core.services.invoicing import issue_membership_invoice

        invoice = issue_membership_invoice(membership, actor=actor)

    return {"membership": membership, "invoice": invoice}


@transaction.atomic
def renew_on_settlement(membership, settled_on=None, *, actor=None):
    """Chain the next period after a renewal Invoice settles.

    Called by the settlement path rather than by a scheduler, so the chain point is
    exactly the moment money arrived.
    """
    profile = membership.member
    settled_on = settled_on or today_for(profile.gym)
    start = next_start_date(profile, settled_on)
    end = end_date_for(start, membership.plan.duration_days)
    assert_no_overlap(profile, start, end)

    from core.services.audit import record_create

    renewed = Membership(member=profile, plan=membership.plan, start_date=start)
    renewed.save()
    record_create(renewed, actor=actor, gym=profile.gym)
    return renewed


def switch_plan(profile, new_plan, *, actor=None):
    """Change plan without proration: the paid period is honoured in full.

    The existing Membership's dates and Invoice are left untouched and the new plan
    starts the day after the current end date. Proration would require refund
    arithmetic the requirements explicitly exclude (4.6, 4.7, 20.12).
    """
    today = today_for(profile.gym)
    current = active_membership(profile, today)
    start = today if current is None else current.end_date + datetime.timedelta(days=1)
    return create_membership(profile, new_plan, start=start, actor=actor)
