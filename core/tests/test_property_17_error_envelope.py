"""Feature: gym-saas-core, Property 17."""
import pytest
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st

from core.exceptions import ALL_ERROR_CODES
from core.models import Invoice, Payment, SaasSubscription, User
from core.tests import factories

pytestmark = pytest.mark.django_db


def assert_envelope(response):
    """The documented shape: error.code non-empty, error.message non-empty."""
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert error.get("code"), body
    assert error["code"] in ALL_ERROR_CODES, error["code"]
    assert isinstance(error.get("message"), str) and error["message"].strip(), body
    if "details" in error:
        assert isinstance(error["details"], dict)


# Feature: gym-saas-core, Property 17: For any request that produces a non-2xx
# response, the response body matches the documented error envelope with a non-empty
# machine-readable code and a non-empty human-readable message, and for any model field
# declaring a restricted choice set, a value outside that set is rejected.
# Validates: Requirements 24.9, 11.1, 16.2, 19.2, 21.2
@settings(max_examples=100)
@given(
    case=st.sampled_from(
        [
            "unauthenticated",
            "not_found",
            "validation",
            "forbidden_role",
            "bad_method",
            "malformed_login",
        ]
    )
)
def test_uniform_error_envelope(case, api_client):
    tenant = factories.make_tenant()

    if case == "unauthenticated":
        response = api_client.get(reverse("core:member-list"))
    elif case == "not_found":
        factories.authenticate(api_client, tenant["owner"].user)
        response = api_client.get(reverse("core:member-detail", args=[10_000_000]))
    elif case == "validation":
        factories.authenticate(api_client, tenant["owner"].user)
        response = api_client.post(
            reverse("core:member-list"), {"email": "not-an-email"}, format="json"
        )
    elif case == "forbidden_role":
        factories.authenticate(api_client, tenant["member"].user)
        response = api_client.post(
            reverse("core:trainer-list"), {"email": "t@example.com"}, format="json"
        )
    elif case == "bad_method":
        factories.authenticate(api_client, tenant["owner"].user)
        response = api_client.delete(reverse("core:me"))
    else:
        response = api_client.post(reverse("core:login"), {}, format="json")

    assert response.status_code >= 400
    assert_envelope(response)


CHOICE_FIELDS = [
    (User, "role", "supreme-leader"),
    (Invoice, "status", "half-paid"),
    (Payment, "status", "maybe"),
    (SaasSubscription, "status", "lapsing"),
]


# Second clause: a value outside a declared choice set is rejected (11.1, 16.2, 19.2,
# 21.2).
@settings(max_examples=100)
@given(index=st.integers(min_value=0, max_value=len(CHOICE_FIELDS) - 1))
def test_choice_sets_reject_values_outside_them(index):
    from django.core.exceptions import ValidationError as DjangoValidationError

    model, field_name, bad_value = CHOICE_FIELDS[index]
    field = model._meta.get_field(field_name)
    valid = {value for value, _ in field.choices}
    assert bad_value not in valid

    with pytest.raises(DjangoValidationError):
        field.clean(bad_value, None)


def test_details_names_the_field_for_validation_errors(api_client):
    """Many criteria require the error to *name* the offending field."""
    tenant = factories.make_tenant()
    factories.authenticate(api_client, tenant["owner"].user)

    response = api_client.post(
        reverse("core:member-list"), {"email": "definitely-not-an-email"}, format="json"
    )
    assert response.status_code == 400
    assert_envelope(response)
    assert response.json()["error"]["details"]["field"] == "email"
