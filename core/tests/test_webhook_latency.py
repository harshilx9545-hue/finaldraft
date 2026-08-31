"""Webhook response budget (task 13.9).

Validates: Requirements 18.8

Razorpay treats a slow endpoint as an unavailable one, so the handler has a hard
10-second ceiling. The measurement is wall clock across the full request cycle —
signature verification, the `WebhookEvent` insert, the locked Payment update, the
Invoice settlement and the Membership chain — because that is what the gateway
experiences, not the cost of any one step.

Three deliveries are measured rather than one: the first pays for connection and
import warm-up, and the budget has to hold for a *replay* too, which takes the
duplicate short-circuit rather than the settlement path.
"""
import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
from core.services.payments import create_order
from core.tests import factories
from core.tests.fakes import build_event_payload, signed_body

pytestmark = pytest.mark.django_db

#: The ceiling requirement 18.8 states.
BUDGET_SECONDS = 10.0


def settle_and_time(client, payload):
    adapter = get_adapter()
    raw, signature = signed_body(adapter, payload)

    started = time.perf_counter()
    response = client.post(
        reverse("core:razorpay-webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
    )
    elapsed = time.perf_counter() - started
    return response, elapsed


def test_a_verified_event_is_answered_inside_the_ten_second_budget():
    """The full settlement path, including the Membership chain, stays in budget."""
    from core.services.memberships import create_membership
    import datetime

    gym = factories.make_gym()
    factories.make_owner(gym)
    plan = factories.make_membership_plan(gym, price="1500.00", duration_days=30)
    member = factories.make_member(gym, plan=plan)
    # An already-ended period, so settling chains a renewal and the slowest branch
    # is the one being measured.
    result = create_membership(
        member, plan, start=gym.today() - datetime.timedelta(days=60)
    )
    order = create_order(result["invoice"], actor=member.user)["order"]

    client = APIClient()
    payload = build_event_payload(
        event_id="evt_latency_settle",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=order.order_ref,
        payment_ref="pay_latency_settle",
    )

    measurements = []
    for _ in range(3):
        response, elapsed = settle_and_time(client, payload)
        assert response.status_code == 200, response.data
        measurements.append(elapsed)

    assert measurements[0] < BUDGET_SECONDS, (
        f"settlement took {measurements[0]:.3f}s, budget is {BUDGET_SECONDS}s"
    )
    for elapsed in measurements[1:]:
        assert elapsed < BUDGET_SECONDS, (
            f"replay took {elapsed:.3f}s, budget is {BUDGET_SECONDS}s"
        )


def test_an_unmatched_event_is_answered_inside_the_budget():
    """The reconciliation path answers 200 fast rather than making the gateway wait."""
    client = APIClient()
    payload = build_event_payload(
        event_id="evt_latency_unmatched",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref="order_that_does_not_exist",
    )
    response, elapsed = settle_and_time(client, payload)

    assert response.status_code == 200
    assert response.json()["reconciliation_required"] is True
    assert elapsed < BUDGET_SECONDS


def test_a_rejected_signature_is_answered_inside_the_budget():
    """A forged request must not be able to hold the endpoint open either."""
    client = APIClient()
    payload = build_event_payload(event_id="evt_latency_forged", order_ref="order_x")
    raw, _ = signed_body(get_adapter(), payload)

    started = time.perf_counter()
    response = client.post(
        reverse("core:razorpay-webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE="not-a-valid-signature",
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 400
    assert elapsed < BUDGET_SECONDS
