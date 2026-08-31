"""Endpoint plumbing shared by the tenant-isolation and authorization properties.

Properties 1, 2, 4, 14, 15 and 35 all need the same three things: a URL for a named
route, the model that route serves, and a valid primary key inside a given tenant.
Keeping that in one table means a new endpoint is picked up by all six properties at
once, which is the same reasoning behind having one tenant-filtering component.

Not a `test_*` module, so pytest does not collect it.
"""
from __future__ import annotations

from django.urls import reverse

from core.models import (
    Gym,
    Invoice,
    MembershipPlan,
    MemberProfile,
    Payment,
    TrainerProfile,
)

#: List endpoints: route name -> (model, queryset for a gym). The queryset is the
#: full tenant set; per-role narrowing (payer scope, trainer assignment) is applied
#: by `expected_visible_ids`.
LIST_ENDPOINTS = {
    "core:trainer-list": TrainerProfile,
    "core:member-list": MemberProfile,
    "core:membership-plan-list": MembershipPlan,
    "core:invoice-list": Invoice,
}

#: Detail endpoints: route name -> model whose primary key the path carries.
DETAIL_ENDPOINTS = {
    "core:member-detail": MemberProfile,
    "core:membership-plan-detail": MembershipPlan,
    "core:invoice-detail": Invoice,
    "core:invoice-pay": Invoice,
    "core:payment-receipt": Payment,
}

#: Roles each route admits at all. A role outside the set is refused with 403 by
#: `RoleAllowed` before any lookup happens.
ROUTE_ROLES = {
    "core:me": {"owner", "trainer", "member"},
    "core:gym-detail": {"owner", "trainer", "member"},
    "core:trainer-list": {"owner"},
    "core:member-list": {"owner", "trainer"},
    "core:member-detail": {"owner", "trainer", "member"},
    "core:membership-plan-list": {"owner", "trainer", "member"},
    "core:membership-plan-detail": {"owner", "trainer", "member"},
    "core:invoice-list": {"owner", "trainer", "member"},
    "core:invoice-detail": {"owner", "trainer", "member"},
    "core:invoice-pay": {"owner", "member"},
    "core:payment-receipt": {"owner", "member"},
}

#: Roles each route admits for unsafe methods.
ROUTE_WRITE_ROLES = {
    "core:me": {"owner", "trainer", "member"},
    "core:gym-detail": {"owner"},
    "core:trainer-list": {"owner"},
    "core:member-list": {"owner", "trainer"},
    "core:member-detail": {"owner", "trainer"},
    "core:membership-plan-list": {"owner"},
    "core:membership-plan-detail": {"owner"},
    "core:invoice-pay": {"owner", "member"},
}

#: The two routes a lapsed Gym or an inactive Member may still reach with an unsafe
#: method, because they are how the money gets paid (D5, 20.8, 21.5).
PAYMENT_EXEMPT_ROUTES = frozenset({"core:invoice-pay"})

#: A primary key that matches no row on the platform.
MISSING_PK = 987_654_321

#: The method that actually reaches a detail route's lookup. Everything is GET
#: except the pay route, which is POST-only and answers 405 to anything else.
DETAIL_LOOKUP_METHOD = {"core:invoice-pay": "post"}


def lookup_method(route):
    return DETAIL_LOOKUP_METHOD.get(route, "get")


def url_for(name, pk=None):
    return reverse(name) if pk is None else reverse(name, kwargs={"pk": pk})


def profile_for(tenant, role):
    return {"owner": tenant["owner"], "trainer": tenant["trainer"], "member": tenant["member"]}[
        role
    ]


def user_for(tenant, role):
    return profile_for(tenant, role).user


def client_for(tenant, role):
    """A fresh authenticated APIClient carrying a real access token."""
    from rest_framework.test import APIClient

    from core.tests.factories import authenticate

    client = APIClient()
    authenticate(client, user_for(tenant, role))
    return client


def anonymous_client():
    from rest_framework.test import APIClient

    return APIClient()


def own_pk(tenant, route, role="owner"):
    """A primary key belonging to `tenant` that `route` would legitimately serve."""
    if route == "core:member-detail":
        return tenant["member"].pk
    if route == "core:membership-plan-detail":
        return tenant["plan"].pk
    if route in {"core:invoice-detail", "core:invoice-pay"}:
        invoice = tenant.get("member_invoice")
        return invoice.pk if invoice is not None else None
    if route == "core:payment-receipt":
        payment = tenant.get("member_payment")
        return payment.pk if payment is not None else None
    return None


def expected_visible_ids(tenant, route, role):
    """The identifiers a given role may legitimately see from a list route.

    Encodes the per-role narrowing on top of the tenant filter: a trainer sees only
    their assigned members (15.3), and a non-owner sees only invoices they are the
    payer of (15.8).
    """
    gym = tenant["gym"]
    model = LIST_ENDPOINTS[route]

    if model is Invoice:
        rows = Invoice.objects.filter(gym=gym, deleted_at__isnull=True)
        if role != "owner":
            rows = rows.filter(payer_user=user_for(tenant, role))
        return set(rows.values_list("pk", flat=True))

    if model is MemberProfile:
        rows = MemberProfile.objects.filter(gym=gym)
        if role == "trainer":
            rows = rows.filter(trainer=tenant["trainer"])
        return set(rows.values_list("pk", flat=True))

    return set(model.objects.filter(gym=gym).values_list("pk", flat=True))


def result_rows(response):
    """The list payload, whether or not pagination wrapped it."""
    body = response.json()
    if isinstance(body, dict) and "results" in body:
        return body["results"]
    return body if isinstance(body, list) else [body]


def snapshot_tenant_state():
    """Every tenant-scoped row a request could plausibly change, with its fields.

    Compared before and after a denied request, so "left every stored record
    unchanged" is checked against the data rather than inferred from a status code.
    """
    return {
        "gyms": sorted(Gym.objects.values_list("pk", "name", "slug", "is_active", "gstin")),
        "trainers": sorted(
            TrainerProfile.all_objects.values_list("pk", "gym_id", "specialization", "status")
        ),
        "members": sorted(
            MemberProfile.all_objects.values_list(
                "pk", "gym_id", "plan_id", "trainer_id", "join_date", "goal"
            )
        ),
        "plans": sorted(
            MembershipPlan.objects.values_list("pk", "gym_id", "name", "price", "duration_days")
        ),
        "invoices": sorted(
            Invoice.all_objects.values_list("pk", "gym_id", "status", "total_amount")
        ),
        "payments": sorted(
            Payment.all_objects.values_list("pk", "gym_id", "status", "amount")
        ),
        "counts": {
            "users": _user_count(),
            "members": MemberProfile.all_objects.count(),
            "trainers": TrainerProfile.all_objects.count(),
            "plans": MembershipPlan.objects.count(),
            "invoices": Invoice.all_objects.count(),
            "payments": Payment.all_objects.count(),
        },
    }


def _user_count():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.count()


def build_billed_tenant(**kwargs):
    """A tenant plus one open member invoice and one succeeded member payment.

    The billing routes need a real payer-owned Invoice and Payment to be reachable
    at all, and both isolation properties need them to exist in *both* tenants so a
    cross-tenant id is a genuine id rather than a nonexistent one.
    """
    from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
    from core.services.memberships import create_membership
    from core.services.payments import create_order, process_event
    from core.tests import factories
    from core.tests.fakes import build_event_payload

    tenant = factories.make_tenant(**kwargs)
    member = tenant["member"]

    # A settled period, so the member is active and a receipt exists.
    settled = create_membership(member, tenant["plan"], start=member.gym.today())
    order = create_order(settled["invoice"], actor=member.user)
    payload = build_event_payload(
        event_id=f"evt_iso_{settled['invoice'].pk}",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=order["order"].order_ref,
        payment_ref=f"pay_iso_{settled['invoice'].pk}",
    )
    process_event(get_adapter().parse_event(payload), payload)

    paid_payment = order["payment"]
    paid_payment.refresh_from_db()

    # A second, still-open invoice so the pay route has something to act on.
    open_invoice = factories.make_invoice(
        tenant["gym"],
        member.user,
        taxable="750.00",
        membership=settled["membership"],
    )

    tenant["member_invoice"] = open_invoice
    tenant["member_payment"] = paid_payment
    tenant["settled_invoice"] = settled["invoice"]
    tenant["membership"] = settled["membership"]
    return tenant
