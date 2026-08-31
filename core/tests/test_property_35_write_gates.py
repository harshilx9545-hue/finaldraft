"""Feature: gym-saas-core, Property 35.

Two gates with the same shape and the same escape hatch:

* a Gym whose subscription is `past_due` or `cancelled` goes read-only (21.5);
* a Member who is not active goes read-only (20.8);

and in both cases the exception is the route that lets them pay. That exception is
the whole reason the gates are safe rather than a trap, so it is asserted as
carefully as the refusals: a gate with no way out would leave a lapsed tenant
permanently unable to become current.

Reads are asserted to keep working under every status, because a gate that also
blocked reads would lock a paying customer out of their own records over a billing
lapse.
"""
import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Payment
from core.tests import factories
from core.tests.endpoints import (
    PAYMENT_EXEMPT_ROUTES,
    ROUTE_ROLES,
    ROUTE_WRITE_ROLES,
    build_billed_tenant,
    client_for,
    own_pk,
    result_rows,
    snapshot_tenant_state,
    url_for,
)

pytestmark = pytest.mark.django_db

WRITE_PERMITTING = {"trialing", "active"}
READ_ONLY_STATUSES = ["past_due", "cancelled"]
ALL_STATUSES = ["trialing", "active", "past_due", "cancelled"]

#: Safe routes every role may read, so the "reads always work" clause is checked
#: across the surface rather than on one endpoint.
READ_ROUTES = [
    "core:me",
    "core:gym-detail",
    "core:membership-plan-list",
    "core:invoice-list",
]

#: (route, method, body) triples that are unsafe writes for an owner. `member-list`
#: is excluded on purpose: 5.7 gives that one route its own status (402), which
#: `test_a_lapsed_gym_cannot_add_members` asserts separately.
OWNER_WRITES = [
    ("core:gym-detail", "patch", {"name": "Renamed Under Gate"}),
    (
        "core:membership-plan-list",
        "post",
        {"name": "Gated Plan", "price": "500.00", "duration_days": 30},
    ),
    ("core:trainer-list", "post", {"email": None}),
    ("core:me", "patch", {"first_name": "Gated"}),
]


def set_subscription(tenant, status):
    subscription = tenant["gym"].subscription
    subscription.status = status
    # Keep the period in the future so the stored status is what is evaluated
    # rather than the derived past_due of an elapsed period.
    subscription.current_period_end = tenant["gym"].today() + datetime.timedelta(days=30)
    subscription.save(update_fields=["status", "current_period_end"])
    return subscription


def body_for(route, body):
    """Fill in the per-example unique values a create body needs."""
    if body.get("email", "sentinel") is None:
        filled = {**body, "email": factories.unique_email("gated")}
        if route == "core:membership-plan-list":
            filled["name"] = f"Gated Plan {filled['email']}"
        return filled
    if route == "core:membership-plan-list":
        return {**body, "name": f"{body['name']} {factories.unique('')}"}
    return body


# Feature: gym-saas-core, Property 35: For any SaasSubscription status and for any
# (endpoint, method) pair, requests from that Gym's Users succeed for safe methods and
# are refused with 403 for unsafe methods when the status is past_due or cancelled,
# except for that Gym's own SaaS Invoice view and pay endpoints; and for any inactive
# Member, requests are permitted only for safe methods the Member is otherwise authorized
# to make and for viewing and paying that Member's own Invoices.
# Validates: Requirements 21.5, 20.8
@settings(max_examples=100, deadline=None)
@given(
    status=st.sampled_from(ALL_STATUSES),
    write_index=st.integers(min_value=0, max_value=len(OWNER_WRITES) - 1),
)
def test_an_unpaid_gym_is_read_only_for_its_owner(status, write_index):
    tenant = build_billed_tenant()
    set_subscription(tenant, status)
    client = client_for(tenant, "owner")

    route, method, raw_body = OWNER_WRITES[write_index]
    before = snapshot_tenant_state()
    response = getattr(client, method)(url_for(route), body_for(route, raw_body), format="json")

    if status in WRITE_PERMITTING:
        assert response.status_code in {200, 201}, response.data
    else:
        assert response.status_code == 403, (
            f"{method.upper()} {route} with subscription {status} returned "
            f"{response.status_code}"
        )
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert snapshot_tenant_state() == before


@settings(max_examples=100, deadline=None)
@given(status=st.sampled_from(ALL_STATUSES), route=st.sampled_from(READ_ROUTES))
def test_reads_keep_working_under_every_subscription_status(status, route):
    """21.5 gates writes but never reads."""
    tenant = build_billed_tenant()
    set_subscription(tenant, status)

    for role in ("owner", "trainer", "member"):
        if role not in ROUTE_ROLES[route]:
            continue
        response = client_for(tenant, role).get(url_for(route))
        assert response.status_code == 200, (
            f"GET {route} as {role} with subscription {status} returned "
            f"{response.status_code}"
        )


@settings(max_examples=100, deadline=None)
@given(status=st.sampled_from(READ_ONLY_STATUSES))
def test_a_lapsed_gym_may_still_view_and_pay_its_own_invoices(status):
    """The escape hatch: without it a lapsed tenant could never become current."""
    tenant = build_billed_tenant()
    set_subscription(tenant, status)
    client = client_for(tenant, "owner")

    listed = client.get(url_for("core:invoice-list"))
    assert listed.status_code == 200, listed.data

    saas_invoice = factories.make_invoice(
        tenant["gym"],
        tenant["owner"].user,
        taxable="999.00",
        saas_subscription=tenant["gym"].subscription,
    )
    detail = client.get(url_for("core:invoice-detail", saas_invoice.pk))
    assert detail.status_code == 200, detail.data

    paid = client.post(url_for("core:invoice-pay", saas_invoice.pk), {}, format="json")
    assert paid.status_code == 201, paid.data
    assert Payment.objects.filter(invoice=saas_invoice, status="pending").exists()


@settings(max_examples=100, deadline=None)
@given(status=st.sampled_from(READ_ONLY_STATUSES))
def test_a_lapsed_gym_cannot_add_members(status):
    """5.7 gives this route its own status: 402, not the generic 403.

    Property 35's blanket "403 for unsafe methods" and requirement 5.7's explicit
    HTTP 402 both cover member creation. The specific rule wins, which is also what
    makes the refusal actionable — "payment required" tells the owner what to do,
    "forbidden" does not.
    """
    tenant = build_billed_tenant()
    set_subscription(tenant, status)

    from core.models import MemberProfile

    before = MemberProfile.all_objects.count()
    response = client_for(tenant, "owner").post(
        url_for("core:member-list"),
        {"email": factories.unique_email("lapsed"), "join_date": str(tenant["gym"].today())},
        format="json",
    )

    assert response.status_code == 402, response.data
    assert response.json()["error"]["code"] == "SUBSCRIPTION_REQUIRED"
    assert MemberProfile.all_objects.count() == before


def test_a_gym_with_no_subscription_at_all_gets_402_on_member_creation():
    """5.7: "you have not paid" rather than "forbidden", because it is actionable."""
    from core.models import MemberProfile

    gym = factories.make_gym(with_subscription=False)
    owner = factories.make_owner(gym)
    plan = factories.make_membership_plan(gym)

    from core.tests.factories import authenticate
    from rest_framework.test import APIClient

    client = APIClient()
    authenticate(client, owner.user)

    before = MemberProfile.all_objects.count()
    response = client.post(
        url_for("core:member-list"),
        {
            "email": factories.unique_email("nosub"),
            "plan": plan.pk,
            "join_date": str(gym.today()),
        },
        format="json",
    )

    assert response.status_code == 402, response.data
    assert response.json()["error"]["code"] == "SUBSCRIPTION_REQUIRED"
    assert MemberProfile.all_objects.count() == before


# ============ INACTIVE MEMBER GATE (20.8) ============

def inactive_member_tenant():
    """A tenant whose member holds no settled, in-period membership."""
    tenant = factories.make_tenant()
    from core.services.memberships import is_member_active

    assert not is_member_active(tenant["member"]), "fixture must start inactive"

    invoice = factories.make_invoice(
        tenant["gym"], tenant["member"].user, taxable="1500.00"
    )
    tenant["member_invoice"] = invoice
    return tenant


@settings(max_examples=100, deadline=None)
@given(route=st.sampled_from(["core:me", "core:membership-plan-list", "core:invoice-list"]))
def test_an_inactive_member_may_still_read(route):
    tenant = inactive_member_tenant()
    response = client_for(tenant, "member").get(url_for(route))
    assert response.status_code == 200, response.data


def test_an_inactive_member_may_view_and_pay_their_own_invoice():
    """20.8's exception, which is the only route out of the inactive state."""
    tenant = inactive_member_tenant()
    client = client_for(tenant, "member")
    invoice = tenant["member_invoice"]

    listed = client.get(url_for("core:invoice-list"))
    assert listed.status_code == 200
    assert invoice.pk in {row["id"] for row in result_rows(listed)}

    detail = client.get(url_for("core:invoice-detail", invoice.pk))
    assert detail.status_code == 200, detail.data

    paid = client.post(url_for("core:invoice-pay", invoice.pk), {}, format="json")
    assert paid.status_code == 201, paid.data


def test_an_inactive_member_cannot_write_anything_else():
    tenant = inactive_member_tenant()
    client = client_for(tenant, "member")
    before = snapshot_tenant_state()

    profile_write = client.patch(url_for("core:me"), {"first_name": "Inactive"}, format="json")
    assert profile_write.status_code == 403, profile_write.data
    assert profile_write.json()["error"]["code"] == "FORBIDDEN"

    plan_write = client.patch(
        url_for("core:membership-plan-detail", tenant["plan"].pk),
        {"name": "Inactive Renamed"},
        format="json",
    )
    assert plan_write.status_code == 403, plan_write.data

    assert snapshot_tenant_state() == before


def test_an_active_member_may_write_their_own_profile():
    """The control case: becoming active restores the writes 20.8 withheld."""
    tenant = build_billed_tenant()

    from core.services.memberships import is_member_active

    assert is_member_active(tenant["member"]), "fixture must be active"

    response = client_for(tenant, "member").patch(
        url_for("core:me"), {"first_name": "Active"}, format="json"
    )
    assert response.status_code == 200, response.data
    tenant["member"].user.refresh_from_db()
    assert tenant["member"].user.first_name == "Active"


def test_the_pay_route_is_the_only_declared_exemption():
    """The exemption is narrow by declaration, so it cannot widen by accident."""
    from core import urls as core_urls

    exempt = set()
    for pattern in core_urls.urlpatterns:
        view = getattr(pattern.callback, "cls", None) or getattr(
            pattern.callback, "view_class", None
        )
        if getattr(view, "subscription_exempt", False) or getattr(
            view, "inactive_member_exempt", False
        ):
            exempt.add(f"core:{pattern.name}")

    # The receipt route is read-only, so its inactive-member exemption grants no
    # write; the pay route is the only exemption that admits an unsafe method.
    writable_exempt = {
        route
        for route in exempt
        if ROUTE_WRITE_ROLES.get(route)
    }
    assert writable_exempt == set(PAYMENT_EXEMPT_ROUTES), writable_exempt
