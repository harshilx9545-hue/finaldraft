"""Auth edge behaviour (task 8.14).

Validates: Requirements 11.2, 13.4, 14.7
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from core.models import User
from core.services import auth_tokens
from core.tests import factories

pytestmark = pytest.mark.django_db


def test_createsuperuser_produces_a_role_within_the_choice_set():
    """11.2: `role` is meaningless for staff, but it must still be a valid choice."""
    staff = User.objects.create_superuser(
        email="operator@example.com", password="Correct-Horse-Battery-7"
    )
    valid = {value for value, _ in User._meta.get_field("role").choices}

    assert staff.role in valid
    assert staff.is_staff and staff.is_superuser
    # D6: a platform operator holds no profile and no Gym.
    from core.scoping import resolve_profile

    assert resolve_profile(staff) is None


def test_expired_and_invalid_access_tokens_use_distinct_codes(api_client, settings):
    """13.4: expiry and bad signature are different problems for the client."""
    gym = factories.make_gym()
    user = factories.make_owner(gym).user

    # Expired: mint a token then move its expiry into the past.
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now() - datetime.timedelta(hours=2), lifetime=datetime.timedelta(seconds=1))
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    expired = api_client.get(reverse("core:me"))

    # Bad signature: keep the shape, corrupt the trailing signature bytes.
    good = str(AccessToken.for_user(user))
    header, payload, signature = good.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}xxxx"
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered}")
    invalid = api_client.get(reverse("core:me"))

    assert expired.status_code == 401
    assert invalid.status_code == 401
    assert expired.json()["error"]["code"] == "TOKEN_EXPIRED"
    assert invalid.json()["error"]["code"] == "TOKEN_INVALID"
    assert expired.json()["error"]["code"] != invalid.json()["error"]["code"]


def test_reset_request_and_confirmation_return_contrasting_shapes(api_client):
    """14.7: request is deliberately uninformative; confirmation is explicit."""
    gym = factories.make_gym()
    user = factories.make_owner(gym).user

    known = api_client.post(reverse("core:password-reset"), {"email": user.email}, format="json")
    unknown = api_client.post(
        reverse("core:password-reset"), {"email": "nobody@example.com"}, format="json"
    )

    # Request: 202 and identical for both, so nothing is disclosed (14.4).
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()

    # Confirmation: an explicit 400 with a machine-readable code (14.6).
    bad_token = api_client.post(
        reverse("core:password-reset-confirm"),
        {
            "token": "not-a-real-token",
            "password": "Brand-New-Passphrase-42",
            "password_confirm": "Brand-New-Passphrase-42",
        },
        format="json",
    )
    assert bad_token.status_code == 400
    assert bad_token.json()["error"]["code"] == "TOKEN_CONSUMED"


def test_auth_service_failure_is_500_not_401(api_client, monkeypatch):
    """10.8: an internal failure must not be reported as rejected credentials."""
    monkeypatch.setattr(
        "core.views.auth.auth_tokens.authenticate_identifier",
        lambda identifier, password: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    response = api_client.post(
        reverse("core:login"), {"identifier": "a@b.com", "password": "x"}, format="json"
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "AUTH_UNAVAILABLE"


def test_logout_requires_authentication(api_client):
    gym = factories.make_gym()
    user = factories.make_owner(gym).user
    tokens = auth_tokens.issue_tokens(user)

    unauthenticated = api_client.post(
        reverse("core:logout"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert unauthenticated.status_code == 401
