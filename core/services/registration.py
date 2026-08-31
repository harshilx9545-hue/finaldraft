"""Tenant onboarding.

`register_owner` creates a Gym, a User with role `owner`, and an OwnerProfile in
one `transaction.atomic()` block. All three or none: a partial result would leave
either an owner who belongs to no gym or a gym nobody can administer, and both are
states no later request can repair (1.2, 1.8).

Self-service registration only ever produces an owner. Trainers and members exist
by invitation, which is why any `role`, `gym`, `is_staff` or `is_superuser` value
in the payload is ignored rather than validated — there is no code path that reads
it (11.3, 12.6).
"""
from __future__ import annotations

import logging
import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from core.models import Gym, OwnerProfile
from core.services import email as email_service
from core.services import profiles as profile_service
from core.services.audit import record_create
from core.services.slugs import SlugExhausted, derive_unique_slug

logger = logging.getLogger("core.auth")

User = get_user_model()

#: Payload keys a client might send hoping they are honoured. They are dropped.
IGNORED_INPUT_KEYS = frozenset(
    {"role", "gym", "gym_id", "is_staff", "is_superuser", "is_active", "email_verified"}
)


def strip_privileged_input(payload):
    """Drop the keys that must never influence account creation."""
    return {key: value for key, value in payload.items() if key not in IGNORED_INPUT_KEYS}


def slug_taken(candidate):
    # Case-insensitive: "IronPit" and "ironpit" are the same tenant address.
    return Gym.objects.filter(slug__iexact=candidate).exists()


def derive_gym_slug(name):
    """Derive a free slug, or raise a field-named validation error.

    Exhausting the 50-attempt budget is a rejection of the registration, not a
    silent fallback to a random string: the slug appears in every invoice number,
    so an unpredictable one is worse than asking for a different name (1.12).
    """
    try:
        return derive_unique_slug(name, slug_taken)
    except SlugExhausted as exc:
        raise ValidationError(
            {
                "gym_name": (
                    "Too many gyms already use this name. Please choose a different "
                    "one."
                )
            }
        ) from exc


@transaction.atomic
def register_owner(
    *,
    email,
    password,
    business_name,
    contact_phone,
    gym_name=None,
    contact_email=None,
    timezone_name="Asia/Kolkata",
    gstin=None,
    first_name="",
    last_name="",
    phone=None,
    send_verification=True,
    trial=True,
):
    """Create Gym + owner User + OwnerProfile atomically. Returns a dict.

    `Gym.name` is the single source of truth for the gym's name.
    `OwnerProfile.business_name` is the legal/business name and is deliberately a
    separate value: renaming the gym must not rewrite it (1.6, 1.13).
    """
    gym_name = (gym_name or business_name or "").strip()
    if not gym_name:
        raise ValidationError({"business_name": "A business name is required."})

    gym = Gym(
        name=gym_name,
        slug=derive_gym_slug(gym_name),
        contact_email=contact_email or email,
        contact_phone=contact_phone,
        timezone=timezone_name or "Asia/Kolkata",
        gstin=gstin or None,
    )
    gym.full_clean()
    try:
        gym.save()
    except IntegrityError as exc:
        # Lost a race between derivation and insert. The client retries; the
        # transaction has rolled back so nothing partial survives.
        raise ValidationError(
            {"gym_name": "That gym name was just taken. Please try again."}
        ) from exc

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name or "",
        last_name=last_name or "",
        phone=phone or None,
        role="owner",
    )

    owner_profile = OwnerProfile.objects.create(
        user=user, gym=gym, business_name=business_name
    )
    profile_service.assert_consistent(user)

    record_create(gym, actor=user, gym=gym)
    record_create(owner_profile, actor=user, gym=gym)

    subscription = None
    if trial:
        from core.services.subscriptions import start_trial

        subscription = start_trial(gym)

    raw_token = None
    if send_verification:
        from core.services.auth_tokens import issue_email_token

        raw_token = issue_email_token(user)
        # Mail is sent inside the transaction but cannot fail it: the helper
        # swallows transport errors (8.6).
        email_service.send_verification_email(user, raw_token)

    logger.info("owner registered gym_id=%s user_id=%s", gym.pk, user.pk)
    return {
        "gym": gym,
        "user": user,
        "owner_profile": owner_profile,
        "subscription": subscription,
    }


# ============ INVITATION ============

def generate_temporary_password():
    """Long random password; the invitee resets it on first sign-in."""
    return secrets.token_urlsafe(12)


@transaction.atomic
def invite_trainer(*, gym, email, first_name="", last_name="", phone=None, specialization="", actor=None):
    """Create a trainer User plus TrainerProfile in the inviting owner's Gym.

    The Gym is taken from the invitation context, never from the payload: an
    invited user inherits the inviting owner's Gym by construction (12.7).
    """
    from core.models import TrainerProfile

    raw_password = generate_temporary_password()
    user = User.objects.create_user(
        email=email,
        password=raw_password,
        first_name=first_name or "",
        last_name=last_name or "",
        phone=phone or None,
        role="trainer",
    )
    profile_service.assert_can_hold_profile(user, "trainer")
    profile = TrainerProfile.objects.create(
        user=user, gym=gym, specialization=specialization or ""
    )
    record_create(profile, actor=actor, gym=gym)
    email_service.send_invite_email(user, gym, raw_password, email_service.TRAINER_INVITE)
    return {"user": user, "profile": profile, "temporary_password": raw_password}


def reject_self_service_role(role):
    """Trainers and members cannot self-register (11.3, 12.6)."""
    if role in {"trainer", "member"}:
        raise ValidationError(
            {
                "role": (
                    f"{role.capitalize()} accounts are created by a gym owner, not "
                    "by self-service registration."
                )
            }
        )
