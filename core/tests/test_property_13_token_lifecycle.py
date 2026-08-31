"""Feature: gym-saas-core, Property 13."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.exceptions import TokenConsumed
from core.models import EmailVerificationToken, PasswordResetToken
from core.services import auth_tokens
from core.tests import factories
from core.tests.strategies import clock_offsets

pytestmark = pytest.mark.django_db

LIFETIMES = {
    auth_tokens.PURPOSE_EMAIL: auth_tokens.EMAIL_TOKEN_LIFETIME,
    auth_tokens.PURPOSE_RESET: auth_tokens.RESET_TOKEN_LIFETIME,
}


# Feature: gym-saas-core, Property 13: For any User and for any clock offset, a refresh
# token can be exchanged exactly once before being invalidated, a logged-out refresh
# token is refused with 401, a password reset revokes every outstanding refresh token of
# that User, and a verification or reset token is accepted if and only if it has not
# been consumed and the offset since issue is within 72 hours for verification and 60
# minutes for reset.
# Validates: Requirements 13.5, 13.6, 14.1, 14.2, 14.3, 14.5, 14.6
@hyp_settings(max_examples=100)
@given(
    purpose=st.sampled_from(list(LIFETIMES)),
    offset=clock_offsets(),
    already_consumed=st.booleans(),
)
def test_one_shot_token_acceptance_boundary(purpose, offset, already_consumed):
    gym = factories.make_gym()
    user = factories.make_owner(gym).user

    issued_at = timezone.now()
    raw = auth_tokens._issue(user, purpose, now=issued_at)

    if already_consumed:
        auth_tokens.consume_token(raw, purpose, now=issued_at)

    checked_at = issued_at + offset
    within_lifetime = offset <= LIFETIMES[purpose]
    should_accept = within_lifetime and not already_consumed

    assert auth_tokens.peek_token(raw, purpose, now=checked_at) is should_accept

    if should_accept:
        assert auth_tokens.consume_token(raw, purpose, now=checked_at).pk == user.pk
    else:
        with pytest.raises(TokenConsumed):
            auth_tokens.consume_token(raw, purpose, now=checked_at)


@hyp_settings(max_examples=100)
@given(purpose=st.sampled_from(list(LIFETIMES)))
def test_a_one_shot_token_is_accepted_exactly_once(purpose):
    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    raw = auth_tokens._issue(user, purpose)

    assert auth_tokens.consume_token(raw, purpose).pk == user.pk
    with pytest.raises(TokenConsumed):
        auth_tokens.consume_token(raw, purpose)


def test_expiries_are_72_hours_and_60_minutes():
    """14.3: the two lifetimes are fixed, not configurable."""
    assert auth_tokens.EMAIL_TOKEN_LIFETIME == datetime.timedelta(hours=72)
    assert auth_tokens.RESET_TOKEN_LIFETIME == datetime.timedelta(minutes=60)


def test_only_hashes_are_stored():
    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    raw = auth_tokens.issue_reset_token(user)

    stored = PasswordResetToken.objects.get(user=user)
    assert stored.token_hash != raw
    assert stored.token_hash == auth_tokens.hash_token(raw)
    assert raw not in stored.token_hash


def test_refresh_token_is_single_use(api_client):
    """13.5, 13.6: rotation plus blacklisting retires the presented token."""
    gym = factories.make_gym()
    user = factories.make_owner(gym, password="Correct-Horse-Battery-7").user
    tokens = auth_tokens.issue_tokens(user)

    first = api_client.post(
        reverse("core:token-refresh"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert first.status_code == 200
    assert first.json()["refresh"] != tokens["refresh"]

    replay = api_client.post(
        reverse("core:token-refresh"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert replay.status_code in (400, 401)


def test_logged_out_refresh_token_is_refused(api_client):
    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    tokens = auth_tokens.issue_tokens(user)

    factories.authenticate(api_client, user)
    logout = api_client.post(
        reverse("core:logout"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert logout.status_code == 204

    api_client.credentials()
    replay = api_client.post(
        reverse("core:token-refresh"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert replay.status_code in (400, 401)


def test_password_reset_revokes_every_outstanding_refresh_token(api_client):
    """14.5: the point of a reset is that the old holder is locked out."""
    gym = factories.make_gym()
    user = factories.make_owner(gym, password="Correct-Horse-Battery-7").user

    outstanding = [auth_tokens.issue_tokens(user)["refresh"] for _ in range(3)]
    raw_reset = auth_tokens.issue_reset_token(user)

    response = api_client.post(
        reverse("core:password-reset-confirm"),
        {
            "token": raw_reset,
            "password": "Brand-New-Passphrase-42",
            "password_confirm": "Brand-New-Passphrase-42",
        },
        format="json",
    )
    assert response.status_code == 200

    for token in outstanding:
        replay = api_client.post(
            reverse("core:token-refresh"), {"refresh": token}, format="json"
        )
        assert replay.status_code in (400, 401), "a pre-reset refresh token still works"


def test_email_verification_marks_the_user_verified(api_client):
    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    assert user.email_verified is False

    raw = auth_tokens.issue_email_token(user)
    response = api_client.post(
        reverse("core:verify-email"), {"token": raw}, format="json"
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email_verified is True
    assert EmailVerificationToken.objects.get(user=user).consumed_at is not None
