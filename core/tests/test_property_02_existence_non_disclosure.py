"""Feature: gym-saas-core, Property 2.

The test is a comparison, not a status-code check. For every detail route and every
method, the response to *another tenant's real id* is compared byte for byte against
the response to an id that matches nothing on the platform. Equal status and equal
body means the API cannot be used to discover that a record exists.

Checking only "returns 404" would miss the leaks that matter in practice: a
different message, a different code, or a `details` key naming the model.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.tests.endpoints import (
    DETAIL_ENDPOINTS,
    MISSING_PK,
    ROUTE_ROLES,
    build_billed_tenant,
    client_for,
    lookup_method,
    own_pk,
    snapshot_tenant_state,
    url_for,
)

pytestmark = pytest.mark.django_db

ROLES = ["owner", "trainer", "member"]
METHODS = ["get", "post", "patch", "put", "delete"]


def probe(client, route, pk, method):
    url = url_for(route, pk)
    if method == "get":
        return client.get(url)
    if method == "delete":
        return client.delete(url)
    return getattr(client, method)(url, {}, format="json")


# Feature: gym-saas-core, Property 2: For any tenant-scoped record type and any request
# method, a request from a User of Gym A naming a record of Gym B produces the same HTTP
# status code and the same response body structure as the same request naming an
# identifier that matches no record on the Platform, and leaves every stored record
# unchanged.
# Validates: Requirements 3.5, 3.2, 3.3
@settings(max_examples=100, deadline=None)
@given(
    route=st.sampled_from(sorted(DETAIL_ENDPOINTS)),
    role=st.sampled_from(ROLES),
    method=st.sampled_from(METHODS),
)
def test_another_tenants_id_is_indistinguishable_from_a_nonexistent_id(route, role, method):
    a = build_billed_tenant()
    b = build_billed_tenant()

    foreign_pk = own_pk(b, route)
    assert foreign_pk is not None, f"fixture must supply a real {route} id in Gym B"

    client = client_for(a, role)
    before = snapshot_tenant_state()

    foreign = probe(client, route, foreign_pk, method)
    missing = probe(client, route, MISSING_PK, method)

    assert foreign.status_code == missing.status_code, (
        f"{method.upper()} {route} as {role}: other-tenant id gave "
        f"{foreign.status_code}, nonexistent id gave {missing.status_code}"
    )
    assert foreign.json() == missing.json(), (
        f"{method.upper()} {route} as {role}: response bodies differ, which "
        "discloses that the record exists"
    )

    # 3.3: nothing changed, whichever id was named.
    assert snapshot_tenant_state() == before

    # No attribute of the foreign record may appear in the body (3.2).
    serialised = foreign.content.decode()
    assert str(b["gym"].name) not in serialised
    assert str(b["gym"].slug) not in serialised


@settings(max_examples=100, deadline=None)
@given(route=st.sampled_from(sorted(DETAIL_ENDPOINTS)), role=st.sampled_from(ROLES))
def test_a_cross_tenant_read_is_404_not_403_where_the_role_is_admitted(route, role):
    """The distinction the requirement draws: 403 is a role refusal, 404 hides data."""
    a = build_billed_tenant()
    b = build_billed_tenant()

    # The pay route is POST-only; anything else answers 405 before the lookup.
    response = probe(client_for(a, role), route, own_pk(b, route), lookup_method(route))

    if role in ROUTE_ROLES[route]:
        assert response.status_code == 404, response.data
        assert response.json()["error"]["code"] == "NOT_FOUND"
    else:
        # Refused on role grounds before any lookup, so no existence question arises.
        assert response.status_code == 403, response.data


def test_a_members_own_id_still_works_so_the_404s_mean_something():
    """The control case: the same routes succeed for an id inside the tenant."""
    a = build_billed_tenant()
    client = client_for(a, "member")

    own_member = client.get(url_for("core:member-detail", a["member"].pk))
    assert own_member.status_code == 200, own_member.data
    assert own_member.json()["id"] == a["member"].pk

    own_invoice = client.get(url_for("core:invoice-detail", a["member_invoice"].pk))
    assert own_invoice.status_code == 200, own_invoice.data

    own_receipt = client.get(url_for("core:payment-receipt", a["member_payment"].pk))
    assert own_receipt.status_code == 200, own_receipt.data


def test_another_members_record_in_the_same_gym_is_also_404():
    """15.8/15.11: non-disclosure applies within a tenant, not only across tenants."""
    a = build_billed_tenant()
    from core.tests import factories

    other_member = factories.make_member(a["gym"], plan=a["plan"])
    client = client_for(a, "member")

    foreign = client.get(url_for("core:member-detail", other_member.pk))
    missing = client.get(url_for("core:member-detail", MISSING_PK))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()

    # And the same for that member's financial records.
    other_invoice = factories.make_invoice(a["gym"], other_member.user, taxable="500.00")
    foreign_invoice = client.get(url_for("core:invoice-detail", other_invoice.pk))
    missing_invoice = client.get(url_for("core:invoice-detail", MISSING_PK))
    assert foreign_invoice.status_code == missing_invoice.status_code == 404
    assert foreign_invoice.json() == missing_invoice.json()


def test_paying_another_tenants_invoice_creates_nothing():
    """3.3 for the one route that would move money if the filter failed."""
    from core.models import Payment

    a = build_billed_tenant()
    b = build_billed_tenant()

    before = Payment.all_objects.count()
    response = client_for(a, "member").post(
        url_for("core:invoice-pay", b["member_invoice"].pk), {}, format="json"
    )

    assert response.status_code == 404, response.data
    assert Payment.all_objects.count() == before
    b["member_invoice"].refresh_from_db()
    assert b["member_invoice"].status == "open"
