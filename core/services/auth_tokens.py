"""Authentication primitives: identifier login, JWT issue/revoke, one-shot tokens.

Two decisions worth stating:

* The phone branch of `authenticate_identifier` validates E.164 *before* touching
  the database. An identifier that cannot possibly be a stored phone number is
  rejected without a query, so the endpoint cannot be used to probe stored phone
  values by timing or by error shape (10.7).
* Email verification and password reset tokens are stored as SHA-256 hashes only.
  The raw token exists in exactly one place — the email that was sent — so a
  database leak yields nothing usable.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from core.exceptions import TokenConsumed
from core.models import EmailVerificationToken, PasswordResetToken
from core.validators import validate_e164

logger = logging.getLogger("core.auth")

User = get_user_model()

#: Lifetimes fixed by requirement 14.3.
EMAIL_TOKEN_LIFETIME = datetime.timedelta(hours=72)
RESET_TOKEN_LIFETIME = datetime.timedelta(minutes=60)

PURPOSE_EMAIL = "email_verification"
PURPOSE_RESET = "password_reset"

_TOKEN_MODELS = {
    PURPOSE_EMAIL: (EmailVerificationToken, EMAIL_TOKEN_LIFETIME),
    PURPOSE_RESET: (PasswordResetToken, RESET_TOKEN_LIFETIME),
}

#: Bytes of entropy per token. 32 bytes -> 43 url-safe characters.
TOKEN_BYTES = 32


# ============ IDENTIFIER AUTHENTICATION ============

def looks_like_email(identifier):
    return "@" in (identifier or "")


def authenticate_identifier(identifier, password):
    """Return the User for (identifier, password), or None.

    One return value for every failure mode on purpose: unknown identifier, wrong
    password, inactive account and malformed identifier are indistinguishable to
    the caller, which is what makes the 401 body identical across them (10.6).
    """
    identifier = (identifier or "").strip()
    user = _lookup_identifier(identifier)

    if user is None:
        # Hash a throwaway password anyway so a missing account and a wrong
        # password cost the same wall-clock time.
        User().set_password(password or "")
        return None

    if not user.check_password(password or ""):
        return None
    if not user.is_active:
        return None
    return user


def _lookup_identifier(identifier):
    if not identifier:
        return None

    if looks_like_email(identifier):
        # Case-insensitive: "Owner@Gym.com" and "owner@gym.com" are one account.
        return User.objects.filter(email__iexact=identifier).first()

    try:
        validate_e164(identifier)
    except DjangoValidationError:
        # Not an email and not a well-formed phone: no query is issued at all.
        return None
    return User.objects.filter(phone=identifier).first()


# ============ JWT ============

def issue_tokens(user):
    """Mint a refresh/access pair carrying user id, role, and gym id as claims.

    The claims are a client convenience. Authorization re-reads role and Gym from
    the database every request, so a stale or forged claim grants nothing (13.8).
    """
    from core.scoping import resolve_profile

    profile = resolve_profile(user)
    gym_id = getattr(profile, "gym_id", None)

    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["gym_id"] = gym_id

    access = refresh.access_token
    access["role"] = user.role
    access["gym_id"] = gym_id

    return {"access": str(access), "refresh": str(refresh)}


def rotate_tokens(raw_refresh):
    """Exchange a refresh token for a new pair, retiring the presented one.

    `ROTATE_REFRESH_TOKENS` plus `BLACKLIST_AFTER_ROTATION` make a refresh token
    single-use; blacklisting here is what enforces it rather than relying on the
    client to discard the old value (13.5, 13.6).
    """
    from rest_framework_simplejwt.exceptions import TokenError

    try:
        refresh = RefreshToken(raw_refresh)
    except TokenError as exc:
        raise TokenConsumed("Refresh token is invalid or expired.") from exc

    user = User.objects.filter(pk=refresh.get("user_id")).first()
    _blacklist(refresh)

    if user is None:
        raise TokenConsumed("Refresh token is invalid or expired.")
    return issue_tokens(user)


def revoke_refresh(raw_refresh):
    """Blacklist one refresh token. Used by logout (14.x)."""
    from rest_framework_simplejwt.exceptions import TokenError

    try:
        refresh = RefreshToken(raw_refresh)
    except TokenError as exc:
        raise TokenConsumed("Refresh token is invalid or expired.") from exc
    _blacklist(refresh)


def revoke_all_refresh(user):
    """Blacklist every outstanding refresh token for a user.

    Called on password reset: the point of a reset is that whoever held the old
    credentials is locked out, which an unexpired refresh token would otherwise
    defeat (14.5).
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:  # blacklist app not installed
        return 0

    count = 0
    for outstanding in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
        count += int(created)
    return count


def _blacklist(refresh):
    try:
        refresh.blacklist()
    except AttributeError:
        # token_blacklist not installed: rotation still issues a new pair, but
        # the old one stays valid until expiry. Logged so it is not silent.
        logger.warning("refresh token blacklisting unavailable; token not retired")


# ============ ONE-SHOT TOKENS ============

def hash_token(raw):
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _issue(user, purpose, now=None):
    model, lifetime = _TOKEN_MODELS[purpose]
    now = now or timezone.now()
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    model.objects.create(
        user=user,
        token_hash=hash_token(raw),
        expires_at=now + lifetime,
    )
    return raw


def issue_email_token(user, now=None):
    """72-hour email verification token. Returns the raw value, stores the hash."""
    return _issue(user, PURPOSE_EMAIL, now=now)


def issue_reset_token(user, now=None):
    """60-minute password reset token. Returns the raw value, stores the hash."""
    return _issue(user, PURPOSE_RESET, now=now)


def consume_token(raw, purpose, now=None):
    """Validate and burn a one-shot token, returning its User.

    Expired and already-consumed both raise the same `TOKEN_CONSUMED`: the client
    needs to request a new token in either case, and distinguishing them would
    tell an attacker that a given token value once existed (14.6).

    The consume is done with a conditional `UPDATE ... WHERE consumed_at IS NULL`
    so two concurrent redemptions of the same token cannot both succeed.
    """
    model, _ = _TOKEN_MODELS[purpose]
    now = now or timezone.now()

    with transaction.atomic():
        record = (
            model.objects.select_for_update()
            .filter(token_hash=hash_token(raw))
            .first()
        )
        if record is None or record.consumed_at is not None or record.expires_at < now:
            raise TokenConsumed()

        burned = model.objects.filter(pk=record.pk, consumed_at__isnull=True).update(
            consumed_at=now
        )
        if not burned:
            raise TokenConsumed()

    return record.user


def peek_token(raw, purpose, now=None):
    """True when the token would be accepted, without consuming it.

    Exists for the token-lifecycle property test, which needs to assert the
    accept/reject boundary at many clock offsets without burning a token per
    example.
    """
    model, _ = _TOKEN_MODELS[purpose]
    now = now or timezone.now()
    record = model.objects.filter(token_hash=hash_token(raw)).first()
    return bool(record and record.consumed_at is None and record.expires_at >= now)
