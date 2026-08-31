"""Feature: gym-saas-core, Property 39."""
import logging

import pytest
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models import Gym, User
from core.services import email as email_service
from core.tests import factories
from core.tests.strategies import e164_phones

pytestmark = pytest.mark.django_db

#: Transport failures a mail backend can realistically raise.
TRANSPORT_ERRORS = [
    ("SMTPException", Exception("smtp refused")),
    ("ConnectionRefusedError", ConnectionRefusedError("no listener")),
    ("TimeoutError", TimeoutError("timed out")),
    ("OSError", OSError("network unreachable")),
]

WEAK_PASSWORDS = ["short", "password", "12345678", "aaaaaaaa", "gym"]


# Feature: gym-saas-core, Property 39: For any operation that sends email not required
# to complete it, when the mail backend raises a transport error the API response remains
# successful, the originating record is persisted, and a log record contains the
# recipient address and the message type; and for any password submitted at registration,
# reset, or change, the configured validators are applied.
# Validates: Requirements 8.6, 14.8, 14.1
@hyp_settings(max_examples=100)
@given(
    error_index=st.integers(min_value=0, max_value=len(TRANSPORT_ERRORS) - 1),
    phone=e164_phones(),
)
def test_registration_succeeds_when_mail_transport_fails(
    error_index, phone, api_client, monkeypatch, caplog
):
    from django.core.cache import cache

    cache.clear()
    # Gyms as well as users: hypothesis examples share one transaction, and the
    # business name here is constant, so retained gyms exhaust the 50-attempt slug
    # suffix budget and registration starts answering 400 instead of 201.
    Gym.objects.all().delete()
    User.objects.all().delete()
    _, error = TRANSPORT_ERRORS[error_index]

    def exploding_send(self, fail_silently=False):
        raise error

    monkeypatch.setattr(
        "django.core.mail.EmailMultiAlternatives.send", exploding_send, raising=True
    )
    # The production logger intentionally does not propagate (to avoid duplicate
    # console records), while caplog captures root-propagated records by default.
    monkeypatch.setattr(logging.getLogger("core.auth"), "propagate", True)

    email = f"owner{abs(hash((error_index, phone))) % 10**9}@example.com"
    before = Gym.objects.count()

    with caplog.at_level(logging.ERROR, logger="core.auth"):
        response = api_client.post(
            reverse("core:register-owner"),
            {
                "email": email,
                "password": "Correct-Horse-Battery-7",
                "password_confirm": "Correct-Horse-Battery-7",
                "business_name": "Mail Failure Gym",
                "contact_phone": phone,
            },
            format="json",
        )

    # The operation succeeds and the record is persisted.
    assert response.status_code == 201, response.content
    assert Gym.objects.count() == before + 1
    assert User.objects.filter(email__iexact=email).exists()

    # The log record names the recipient and the message type.
    records = [record.getMessage() for record in caplog.records]
    assert any(email in message for message in records), records
    assert any(email_service.VERIFY_EMAIL in message for message in records), records


@hyp_settings(max_examples=100)
@given(error_index=st.integers(min_value=0, max_value=len(TRANSPORT_ERRORS) - 1))
def test_password_reset_request_still_returns_202_when_mail_fails(
    error_index, api_client, monkeypatch, caplog
):
    from django.core.cache import cache

    cache.clear()
    _, error = TRANSPORT_ERRORS[error_index]
    monkeypatch.setattr(
        "django.core.mail.EmailMultiAlternatives.send",
        lambda self, fail_silently=False: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(logging.getLogger("core.auth"), "propagate", True)

    gym = factories.make_gym()
    user = factories.make_owner(gym).user

    with caplog.at_level(logging.ERROR, logger="core.auth"):
        response = api_client.post(
            reverse("core:password-reset"), {"email": user.email}, format="json"
        )

    assert response.status_code == 202
    records = [record.getMessage() for record in caplog.records]
    assert any(user.email in message for message in records)
    assert any(email_service.PASSWORD_RESET in message for message in records)


@hyp_settings(max_examples=100)
@given(weak=st.sampled_from(WEAK_PASSWORDS), phone=e164_phones())
def test_password_validators_are_applied_at_registration(weak, phone, api_client):
    """14.1, 14.8: the configured validators run, and report against `password`."""
    from django.core.cache import cache

    cache.clear()
    response = api_client.post(
        reverse("core:register-owner"),
        {
            "email": f"weak{abs(hash((weak, phone))) % 10**9}@example.com",
            "password": weak,
            "password_confirm": weak,
            "business_name": "Weak Password Gym",
            "contact_phone": phone,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "password"


@hyp_settings(max_examples=100)
@given(weak=st.sampled_from(WEAK_PASSWORDS))
def test_password_validators_are_applied_at_reset_confirmation(weak, api_client):
    from core.services.auth_tokens import issue_reset_token

    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    raw = issue_reset_token(user)

    response = api_client.post(
        reverse("core:password-reset-confirm"),
        {"token": raw, "password": weak, "password_confirm": weak},
        format="json",
    )

    assert response.status_code == 400
    user.refresh_from_db()
    assert not user.check_password(weak)


def test_send_optional_never_raises():
    """The helper's contract, asserted directly."""
    assert email_service.send_optional(None, "s", "b", "type") is False
