"""Seat accounting.

Seat_Count is the number of non-soft-deleted MemberProfile rows in a Gym. The limit
is `max_members_allowed` on the Gym's current SaasPlan; null means unlimited.

Every operation that could *increase* Seat_Count takes a row lock on the Gym first.
Locking the Gym row rather than counting optimistically is what makes N concurrent
creates against K remaining seats produce exactly min(N, K) successes: the count and
the insert happen inside the same serialized critical section (5.1, Property 32).

Operations that cannot increase Seat_Count — updating an existing MemberProfile,
settling an Invoice, changing Membership dates — are deliberately not gated here at
all (D5, 5.8, 5.9).
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import ValidationError

from core.exceptions import Http402, PlanDowngradeBlocked, SeatLimitReached
from core.models import Gym, MemberProfile
from core.services import profiles as profile_service

logger = logging.getLogger("core.auth")

User = get_user_model()

#: Subscription statuses under which a Gym may add members.
LIVE_STATUSES = frozenset({"trialing", "active"})


def seat_count(gym):
    """Non-soft-deleted MemberProfile rows for this Gym."""
    return MemberProfile.objects.filter(gym=gym, deleted_at__isnull=True).count()


def seat_limit(gym):
    """The Gym's current seat limit, or None for unlimited."""
    subscription = getattr(gym, "subscription", None)
    if subscription is None:
        return None
    return subscription.plan.max_members_allowed


def remaining_seats(gym):
    """Seats left, or None when unlimited."""
    limit = seat_limit(gym)
    if limit is None:
        return None
    return max(0, limit - seat_count(gym))


def subscription_is_live(gym):
    subscription = getattr(gym, "subscription", None)
    return subscription is not None and subscription.status in LIVE_STATUSES


def assert_subscription_live(gym):
    """402 before any seat arithmetic: no subscription means no member creation."""
    if not subscription_is_live(gym):
        raise Http402(
            "This gym has no trialing or active subscription, so members cannot be "
            "added.",
            details={"gym": gym.slug, "field": "subscription"},
        )


def assert_seat_available(gym, *, additional=1):
    """409 naming both the current count and the limit (5.2)."""
    limit = seat_limit(gym)
    if limit is None:
        return
    current = seat_count(gym)
    if current + additional > limit:
        raise SeatLimitReached(current, limit)


@transaction.atomic
def create_member_atomically(
    gym,
    *,
    email,
    password,
    first_name="",
    last_name="",
    phone=None,
    join_date=None,
    plan=None,
    trainer=None,
    goal="",
    actor=None,
):
    """Create a User plus MemberProfile, or neither.

    Order matters and is checked twice over:

    1. Lock the Gym row, so no concurrent create can interleave with the count.
    2. Subscription check -> 402. Asked first because "you have not paid" is more
       actionable than "you are out of seats" for a Gym that is both.
    3. Seat check -> 409.
    4. Create the User and the MemberProfile.
    """
    from core.services.audit import record_create
    from core.services.memberships import today_for

    # select_for_update on the Gym is the serialization point for this tenant.
    locked_gym = Gym.objects.select_for_update().get(pk=gym.pk)

    assert_subscription_live(locked_gym)
    assert_seat_available(locked_gym)

    if plan is not None and plan.gym_id != locked_gym.pk:
        raise ValidationError(
            {"plan": "That membership plan belongs to a different gym.", "field": "plan"}
        )
    if trainer is not None and trainer.gym_id != locked_gym.pk:
        raise ValidationError(
            {"trainer": "That trainer belongs to a different gym.", "field": "trainer"}
        )

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name or "",
        last_name=last_name or "",
        phone=phone or None,
        role="member",
    )
    profile_service.assert_can_hold_profile(user, "member")

    profile = MemberProfile.objects.create(
        user=user,
        gym=locked_gym,
        plan=plan,
        trainer=trainer,
        join_date=join_date or today_for(locked_gym),
        goal=goal or "",
    )
    record_create(profile, actor=actor, gym=locked_gym)
    logger.info("member created gym_id=%s user_id=%s", locked_gym.pk, user.pk)
    return profile


@transaction.atomic
def restore_member(profile, *, actor=None):
    """Un-delete a member, refusing when that would exceed the limit (5.10).

    Refusal leaves the record soft-deleted rather than partially restored, so a
    retry after a downgrade or a seat freed elsewhere behaves predictably.
    """
    from core.services.audit import record_restore

    if profile.deleted_at is None:
        return profile

    locked_gym = Gym.objects.select_for_update().get(pk=profile.gym_id)
    assert_seat_available(locked_gym)

    previous = profile.deleted_at
    profile.deleted_at = None
    profile.save(update_fields=["deleted_at"])
    record_restore(profile, previous, actor=actor, gym=locked_gym)
    return profile


@transaction.atomic
def soft_delete_member(profile, *, actor=None):
    """Free a seat. Never gated: releasing capacity cannot break the invariant."""
    from core.services.audit import record_soft_delete

    if profile.deleted_at is not None:
        return profile
    profile.soft_delete()
    record_soft_delete(profile, actor=actor, gym=profile.gym)
    return profile


@transaction.atomic
def assert_plan_change_allowed(gym, new_plan):
    """A downgrade below the current head-count is refused with both numbers (5.5).

    Checked against the *current* Seat_Count rather than asking the owner to remove
    members first: the refusal message tells them exactly how many they are over.
    """
    limit = new_plan.max_members_allowed
    if limit is None:
        return
    locked_gym = Gym.objects.select_for_update().get(pk=gym.pk)
    current = seat_count(locked_gym)
    if current > limit:
        raise PlanDowngradeBlocked(current, limit)


@transaction.atomic
def change_saas_plan(gym, new_plan, *, actor=None):
    """Move a Gym to a different SaasPlan, subject to the seat check."""
    from core.services.audit import AuditedChange

    assert_plan_change_allowed(gym, new_plan)
    subscription = gym.subscription
    with AuditedChange(subscription, actor=actor, gym=gym, fields=["plan_id", "status"]):
        subscription.plan = new_plan
        subscription.save(update_fields=["plan"])
    return subscription
