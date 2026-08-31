"""Feature: gym-saas-core, Property 23.

Idempotency has two independent layers and they guard different things, so both are
driven here:

* `WebhookEvent.event_id` is unique, which makes a *retry of the same delivery* a
  no-op. That is a database uniqueness guarantee and holds on every backend.
* `select_for_update()` on the Payment row serialises two *different* deliveries
  that touch the same payment. Row locking cannot be demonstrated on SQLite, so the
  threaded clause is gated on PostgreSQL exactly as the design's testing strategy
  states; the same-order-different-event-id case is checked sequentially on every
  backend, which is the state that clause protects against.
"""
import datetime
import itertools

import pytest
from django.db import connection
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from core.models import Membership, Payment, WebhookEvent
from core.services.gateway import EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_FAILED, get_adapter
from core.services.payments import create_order
from core.tests import factories
from core.tests.fakes import build_event_payload, signed_body
from core.tests.strategies import delivery_counts, gateway_events

pytestmark = pytest.mark.django_db

IS_POSTGRES = connection.vendor == "postgresql"

WEBHOOK_URL = "core:razorpay-webhook"

_ids = itertools.count(1)

TERMINAL_STATUSES = {"succeeded", "failed", "refunded", "cancelled"}


def post_webhook(client, payload, *, adapter=None, secret=None, tamper=False):
    adapter = adapter or get_adapter()
    raw, signature = signed_body(adapter, payload, secret=secret, tamper=tamper)
    return client.post(
        reverse(WEBHOOK_URL),
        data=raw,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
    )


def payable_world(*, membership_start_offset_days=0, duration_days=30):
    """A member with one open membership invoice and a live gateway order."""
    from core.services.memberships import create_membership

    gym = factories.make_gym()
    factories.make_owner(gym)
    plan = factories.make_membership_plan(
        gym, price="1500.00", duration_days=duration_days
    )
    member = factories.make_member(gym, plan=plan)

    start = gym.today() + datetime.timedelta(days=membership_start_offset_days)
    result = create_membership(member, plan, start=start)
    invoice = result["invoice"]
    order = create_order(invoice, actor=member.user)

    return {
        "gym": gym,
        "member": member,
        "plan": plan,
        "membership": result["membership"],
        "invoice": invoice,
        "payment": order["payment"],
        "order_ref": order["order"].order_ref,
        "client": APIClient(),
    }


# Feature: gym-saas-core, Property 23: For any verified gateway event and for any
# delivery count N >= 1, including concurrent deliveries, processing that event N times
# produces exactly one Payment record in a terminal status, the same Invoice settlement
# state as processing it once, and the same Membership chain as processing it once; and
# for any event referencing an order that matches no Payment, the response is 200, the
# event is recorded for reconciliation, and no Payment is created.
# Validates: Requirements 18.6, 18.4, 18.5, 18.7, 18.9, 17.7
@settings(max_examples=100)
@given(
    deliveries=delivery_counts(),
    kind=st.sampled_from([EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_FAILED]),
    method=st.sampled_from(["upi", "card", "netbanking", "wallet"]),
)
def test_n_deliveries_of_one_event_produce_one_terminal_payment(deliveries, kind, method):
    world = payable_world()
    payload = build_event_payload(
        event_id=f"evt_p23_{next(_ids):08d}",
        kind=kind,
        order_ref=world["order_ref"],
        payment_ref=f"pay_p23_{next(_ids):08d}",
        method=method,
    )

    outcomes = []
    for _ in range(deliveries):
        response = post_webhook(world["client"], payload)
        # 18.8: the gateway must never see an error for a well-formed event.
        assert response.status_code == 200, response.data
        outcomes.append(response.json()["outcome"])

    assert outcomes[0] == "processed"
    # 18.9: a repeated event id is already processed.
    assert all(outcome == "duplicate" for outcome in outcomes[1:])

    payments = list(Payment.all_objects.filter(gateway_order_ref=world["order_ref"]))
    assert len(payments) == 1
    payment = payments[0]
    assert payment.status in TERMINAL_STATUSES

    world["invoice"].refresh_from_db()
    if kind == EVENT_PAYMENT_CAPTURED:
        # 18.4
        assert payment.status == "succeeded"
        assert payment.gateway_payment_ref == payload["entity"]["id"]
        assert world["invoice"].status == "settled"
        # 17.7: the method the gateway reported is recorded, normalised to the
        # three the model stores.
        assert payment.method == {"wallet": "upi"}.get(method, method)
    else:
        # 18.5
        assert payment.status == "failed"
        assert world["invoice"].status == "open"

    # One WebhookEvent row, whatever the delivery count.
    assert WebhookEvent.objects.filter(event_id=payload["id"]).count() == 1


@settings(max_examples=100)
@given(deliveries=delivery_counts())
def test_repeated_settlement_does_not_extend_the_membership_chain(deliveries):
    """18.6: the Membership chain after N deliveries equals the chain after one."""
    # A membership that has already ended, so settling its invoice is a renewal and
    # the chaining branch is actually taken.
    world = payable_world(membership_start_offset_days=-60, duration_days=30)
    member = world["member"]
    before = Membership.objects.filter(member=member).count()

    payload = build_event_payload(
        event_id=f"evt_p23_chain_{next(_ids):08d}",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=world["order_ref"],
        payment_ref=f"pay_p23_chain_{next(_ids):08d}",
    )

    for _ in range(deliveries):
        assert post_webhook(world["client"], payload).status_code == 200

    after = Membership.objects.filter(member=member).count()
    assert after == before + 1, "settlement must chain exactly one renewal"

    periods = list(
        Membership.objects.filter(member=member)
        .order_by("start_date")
        .values_list("start_date", "end_date")
    )
    # No two periods intersect, however many times the event arrived.
    for (a_start, a_end), (b_start, b_end) in zip(periods, periods[1:]):
        assert a_end < b_start, periods


def test_a_second_distinct_event_for_a_settled_payment_is_a_duplicate():
    """The layer `select_for_update` protects: same order, different event id."""
    world = payable_world()
    client = world["client"]

    first = post_webhook(
        client,
        build_event_payload(
            event_id="evt_p23_first",
            kind=EVENT_PAYMENT_CAPTURED,
            order_ref=world["order_ref"],
            payment_ref="pay_p23_first",
        ),
    )
    assert first.json()["outcome"] == "processed"

    second = post_webhook(
        client,
        build_event_payload(
            event_id="evt_p23_second",
            kind=EVENT_PAYMENT_CAPTURED,
            order_ref=world["order_ref"],
            payment_ref="pay_p23_second",
        ),
    )
    assert second.status_code == 200
    assert second.json()["outcome"] == "duplicate"

    payments = list(Payment.all_objects.filter(gateway_order_ref=world["order_ref"]))
    assert len(payments) == 1
    assert payments[0].status == "succeeded"
    # The first reference wins; the second delivery does not overwrite it.
    assert payments[0].gateway_payment_ref == "pay_p23_first"


@settings(max_examples=100)
@given(payload=gateway_events())
def test_an_event_matching_no_payment_is_recorded_for_reconciliation(payload):
    """18.7: 200 with a reconciliation flag, and no Payment invented."""
    client = APIClient()
    payload = dict(payload)
    # A fresh event identity per example: the generated ids repeat, and a repeat is
    # legitimately a duplicate rather than an unmatched event. What varies here is
    # the payload shape, not the identity.
    payload["id"] = f"evt_p23_unmatched_{next(_ids):08d}"
    payload["entity"] = dict(payload["entity"], order_id="order_never_created")
    payload["payload"] = {"payment": {"entity": payload["entity"]}}

    before = Payment.all_objects.count()
    response = post_webhook(client, payload)

    assert response.status_code == 200, response.data
    body = response.json()
    assert body["outcome"] == "unmatched"
    assert body["reconciliation_required"] is True

    stored = WebhookEvent.objects.get(event_id=payload["id"])
    assert stored.reconciliation_required is True
    assert stored.processed_at is not None
    assert stored.matched_payment_id is None
    assert Payment.all_objects.count() == before


def test_an_event_with_no_order_reference_is_flagged_not_matched():
    client = APIClient()
    payload = build_event_payload(
        event_id="evt_p23_no_order", kind=EVENT_PAYMENT_CAPTURED, order_ref=None
    )
    response = post_webhook(client, payload)

    assert response.status_code == 200
    assert response.json()["outcome"] == "unmatched"
    assert WebhookEvent.objects.get(event_id="evt_p23_no_order").reconciliation_required


def test_an_unrecognised_event_kind_changes_nothing():
    """A verified event the platform does not act on is recorded and ignored."""
    world = payable_world()
    payload = build_event_payload(
        event_id="evt_p23_refund_kind",
        kind="refund.created",
        order_ref=world["order_ref"],
        payment_ref="pay_p23_refund_kind",
    )

    response = post_webhook(world["client"], payload)
    assert response.status_code == 200
    assert response.json()["outcome"] == "ignored"

    world["payment"].refresh_from_db()
    world["invoice"].refresh_from_db()
    assert world["payment"].status == "pending"
    assert world["invoice"].status == "open"


@pytest.mark.slow
@pytest.mark.skipif(
    not IS_POSTGRES,
    reason=(
        "SQLite takes a database-level lock rather than a row-level one, so "
        "select_for_update() cannot be shown to serialise concurrent deliveries "
        "and a passing test would prove nothing. The sequential clauses above "
        "cover the same states on every backend."
    ),
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_deliveries_of_one_event_settle_once():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    world = payable_world()
    payload = build_event_payload(
        event_id="evt_p23_concurrent",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=world["order_ref"],
        payment_ref="pay_p23_concurrent",
    )

    def deliver(_):
        try:
            return post_webhook(APIClient(), payload).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(deliver, range(5)))

    assert set(statuses) == {200}
    payments = list(Payment.all_objects.filter(gateway_order_ref=world["order_ref"]))
    assert len(payments) == 1
    assert payments[0].status == "succeeded"
    world["invoice"].refresh_from_db()
    assert world["invoice"].status == "settled"
    assert WebhookEvent.objects.filter(event_id="evt_p23_concurrent").count() == 1
