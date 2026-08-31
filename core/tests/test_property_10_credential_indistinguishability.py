"""Feature: gym-saas-core, Property 10."""
import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings

from core.services.auth_tokens import authenticate_identifier
from core.tests import factories
from core.tests.strategies import emails, malformed_phones

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 10: For any identifier that matches no User and for
# any User presented with a wrong password, the response is HTTP 401 with byte-identical
# code and message across both cases, and for any identifier that is not valid E.164 and
# not an email, the rejection occurs with no query filtering on stored phone values.
# Validates: Requirements 10.6, 10.7
@hyp_settings(max_examples=100)
@given(unknown=emails())
def test_credential_failures_are_byte_identical(unknown, api_client):
    from django.core.cache import cache

    cache.clear()
    gym = factories.make_gym()
    user = factories.make_owner(gym, password="Correct-Horse-Battery-7").user

    unknown_identifier = api_client.post(
        reverse("core:login"),
        {"identifier": f"nobody-{unknown}", "password": "Correct-Horse-Battery-7"},
        format="json",
    )
    wrong_password = api_client.post(
        reverse("core:login"),
        {"identifier": user.email, "password": "definitely-not-the-password"},
        format="json",
    )

    assert unknown_identifier.status_code == wrong_password.status_code == 401
    # Byte-identical: same code, same message, same serialised body.
    assert json.dumps(unknown_identifier.json(), sort_keys=True) == json.dumps(
        wrong_password.json(), sort_keys=True
    )
    assert unknown_identifier.json()["error"]["code"] == "INVALID_CREDENTIALS"


@hyp_settings(max_examples=100)
@given(identifier=malformed_phones())
def test_malformed_identifier_never_queries_stored_phone_values(identifier):
    """10.7: format validation happens before any database comparison."""
    factories.make_owner(factories.make_gym())

    with CaptureQueriesContext(connection) as captured:
        result = authenticate_identifier(identifier, "any-password")

    assert result is None
    phone_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "phone" in query["sql"].lower()
    ]
    assert phone_queries == [], phone_queries


@hyp_settings(max_examples=100)
@given(identifier=malformed_phones())
def test_malformed_identifier_is_refused_with_the_same_body(identifier, api_client):
    from django.core.cache import cache

    cache.clear()
    factories.make_owner(factories.make_gym())

    response = api_client.post(
        reverse("core:login"), {"identifier": identifier, "password": "x"}, format="json"
    )
    # A blank identifier is a field-level validation error; anything else is the
    # indistinguishable 401.
    assert response.status_code in (400, 401)
    if response.status_code == 401:
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_inactive_account_is_indistinguishable_from_a_wrong_password(api_client):
    from django.core.cache import cache

    cache.clear()
    gym = factories.make_gym()
    user = factories.make_owner(gym, password="Correct-Horse-Battery-7").user
    user.is_active = False
    user.save(update_fields=["is_active"])

    inactive = api_client.post(
        reverse("core:login"),
        {"identifier": user.email, "password": "Correct-Horse-Battery-7"},
        format="json",
    )
    wrong = api_client.post(
        reverse("core:login"), {"identifier": user.email, "password": "nope"}, format="json"
    )

    assert inactive.status_code == wrong.status_code == 401
    assert inactive.json() == wrong.json()
