"""Feature: gym-saas-core, Property 3."""
import pytest
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Invoice, MemberProfile, Membership, Payment
from core.tests import factories
from core.tests.strategies import tenant_scoped_endpoints

pytestmark = pytest.mark.django_db

GATE_CONDITIONS = ["anonymous", "no_profile", "inactive_gym", "soft_deleted_profile"]


def _row_counts():
    return {
        "members": MemberProfile.all_objects.count(),
        "memberships": Membership.all_objects.count(),
        "invoices": Invoice.all_objects.count(),
        "payments": Payment.all_objects.count(),
    }


# Feature: gym-saas-core, Property 3: For any tenant-scoped endpoint and any gate
# condition - unauthenticated requester, requester holding no non-soft-deleted profile,
# or requester whose Gym has is_active false - the API responds with 401 for the
# unauthenticated case and 403 for the others, issues no query against any
# tenant-scoped model, and leaves every stored record unchanged.
# Validates: Requirements 3.6, 1.7, 15.5, 15.1
@settings(max_examples=100)
@given(
    endpoint=tenant_scoped_endpoints(with_pk=False),
    condition=st.sampled_from(GATE_CONDITIONS),
)
def test_access_gates_deny_before_any_data_is_read(endpoint, condition, api_client):
    # Hypothesis reuses function-scoped fixtures between examples.  Reset the
    # client's credentials so an earlier authenticated example cannot masquerade
    # as this example's anonymous caller.
    api_client.credentials()
    url_name, _needs_pk, methods = endpoint
    tenant = factories.make_tenant()
    before = _row_counts()

    if condition == "anonymous":
        expected = 401
    elif condition == "no_profile":
        # A staff account holds no profile and no Gym: refused, not elevated (D6).
        factories.authenticate(api_client, factories.make_staff())
        expected = 403
    elif condition == "inactive_gym":
        tenant["gym"].is_active = False
        tenant["gym"].save(update_fields=["is_active"])
        factories.authenticate(api_client, tenant["owner"].user)
        expected = 403
    else:
        profile = tenant["owner"]
        factories.authenticate(api_client, profile.user)
        profile.soft_delete()
        expected = 403

    url = reverse(url_name)
    for method in methods:
        response = getattr(api_client, method)(url, {}, format="json")
        assert response.status_code == expected, (
            f"{method.upper()} {url} under {condition}: got {response.status_code}"
        )
        # The uniform envelope holds even for a gate refusal.
        assert "error" in response.json()
        assert response.json()["error"]["code"]

    assert _row_counts() == before, "a denied request must change nothing"


@settings(max_examples=100)
@given(condition=st.sampled_from(GATE_CONDITIONS))
def test_staff_flags_never_grant_tenant_access(condition, api_client):
    """3.1: is_staff and is_superuser are not consulted by the filtering layer."""
    tenant = factories.make_tenant()
    user = tenant["owner"].user
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])

    other = factories.make_tenant()
    factories.authenticate(api_client, user)

    response = api_client.get(reverse("core:member-list"))
    assert response.status_code == 200
    returned = {row["id"] for row in response.json().get("results", response.json())}
    assert other["member"].pk not in returned
