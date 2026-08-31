"""Feature: gym-saas-core, Property 22.

Order creation is the one place where a database write and an external call share a
transaction, so the failure clause is the interesting one: *every* way the gateway
can fail must leave no `pending` Payment behind. The fake adapter enumerates those
modes rather than having them monkeypatched, so the property runs over all of them
including `error_after_order`, where the remote order really was created and only
the response failed.

Both the service and the HTTP endpoint are exercised. The endpoint matters
separately because it is where the payer scope, the card-data screen and the error
envelope live.
"""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from core.exceptions import CurrencyMismatch, GatewayError, InvoiceAlreadyPaid
from core.models import Payment
from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
from core.services.money import to_minor_units
from core.services.payments import create_order, order_response, process_event
from core.tests import factories
from core.tests.fakes import (
    FAKE_KEY_SECRET,
    FAKE_WEBHOOK_SECRET,
    FakeRazorpayAdapter,
    build_event_payload,
)
from core.tests.strategies import gateway_failure_modes, two_dp_decimals

pytestmark = pytest.mark.django_db

PAY_URL = "core:invoice-pay"


def membership_world(*, price="1500.00", currency="INR"):
    """A member holding one open membership Invoice, ready to pay."""
    from core.services.memberships import create_membership

    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    plan = factories.make_membership_plan(
        gym, price=price, currency=currency, duration_days=30
    )
    member = factories.make_member(gym, plan=plan)
    result = create_membership(member, plan, start=gym.today())

    client = APIClient()
    factories.authenticate(client, member.user)
    return {
        "gym": gym,
        "owner": owner,
        "plan": plan,
        "member": member,
        "membership": result["membership"],
        "invoice": result["invoice"],
        "client": client,
    }


def pay(client, invoice, body=None):
    return client.post(
        reverse(PAY_URL, kwargs={"pk": invoice.pk}), body or {}, format="json"
    )


# Feature: gym-saas-core, Property 22: For any open Invoice, requesting payment creates
# exactly one Payment with status pending, a unique Idempotency_Key, and the gateway
# order reference, and returns the order reference and the public gateway key; for any
# gateway failure mode, the response is 502 and no Payment row remains for that attempt;
# for any Invoice already holding a succeeded Payment the request is refused with 409;
# and for any currency differing from the gateway account currency the request is
# refused.
# Validates: Requirements 17.1, 17.2, 17.5, 17.6, 17.8, 16.3, 16.4
@settings(max_examples=100)
@given(taxable=two_dp_decimals(min_value="0.01", max_value="500000.00"))
def test_paying_an_open_invoice_creates_exactly_one_pending_payment(taxable):
    world = membership_world()
    invoice = world["invoice"]
    # Re-price through a fresh invoice so the generated amount is the one charged.
    invoice = factories.make_invoice(
        world["gym"],
        world["member"].user,
        taxable=str(taxable),
        membership=world["membership"],
    )

    response = pay(world["client"], invoice)
    assert response.status_code == 201, response.data
    body = response.json()

    payments = list(Payment.all_objects.filter(invoice=invoice))
    assert len(payments) == 1
    payment = payments[0]

    assert payment.status == "pending"
    assert payment.amount == invoice.total_amount
    assert payment.currency == invoice.currency
    assert payment.gateway_order_ref == body["order_ref"]
    assert payment.idempotency_key
    # 17.1: the client gets the order reference and the *public* key, nothing else.
    assert body["key_id"] == get_adapter().public_key
    assert body["amount_minor"] == to_minor_units(invoice.total_amount, invoice.currency)
    assert body["currency"] == invoice.currency
    assert body["receipt"] == invoice.number
    assert set(body) == {"order_ref", "amount_minor", "currency", "key_id", "receipt"}


@settings(max_examples=100)
@given(fail_mode=gateway_failure_modes())
def test_every_gateway_failure_mode_leaves_no_payment_row(fail_mode):
    """17.6: 502, and nothing persisted — including when the remote order succeeded."""
    world = membership_world()
    invoice = world["invoice"]
    broken = FakeRazorpayAdapter(fail_mode=fail_mode)

    with override_settings(PAYMENT_GATEWAY_ADAPTER=broken):
        response = pay(world["client"], invoice)

    assert response.status_code == 502, response.data
    assert response.json()["error"]["code"] == "GATEWAY_ERROR"
    # all_objects, so a soft-deleted leftover would still be caught.
    assert not Payment.all_objects.filter(invoice=invoice).exists()
    invoice.refresh_from_db()
    assert invoice.status == "open"


@settings(max_examples=100)
@given(fail_mode=gateway_failure_modes())
def test_the_service_raises_gateway_error_and_rolls_back(fail_mode):
    """The same guarantee at the service boundary, independent of the view."""
    world = membership_world()
    invoice = world["invoice"]
    broken = FakeRazorpayAdapter(fail_mode=fail_mode)

    with pytest.raises(GatewayError):
        create_order(invoice, actor=world["member"].user, adapter=broken)

    assert not Payment.all_objects.filter(invoice=invoice).exists()


def test_a_settled_invoice_refuses_a_new_order_with_409():
    """17.5: once money has arrived, no second order may be created."""
    world = membership_world()
    invoice = world["invoice"]

    first = pay(world["client"], invoice)
    assert first.status_code == 201
    order_ref = first.json()["order_ref"]

    adapter = get_adapter()
    payload = build_event_payload(
        event_id="evt_p22_settle", kind=EVENT_PAYMENT_CAPTURED, order_ref=order_ref
    )
    process_event(adapter.parse_event(payload), payload)

    invoice.refresh_from_db()
    assert invoice.status == "settled"

    second = pay(world["client"], invoice)
    assert second.status_code == 409, second.data
    assert second.json()["error"]["code"] == "INVOICE_ALREADY_PAID"
    assert Payment.all_objects.filter(invoice=invoice).count() == 1

    with pytest.raises(InvoiceAlreadyPaid):
        create_order(invoice, actor=world["member"].user)


def test_a_voided_invoice_cannot_be_paid():
    world = membership_world()
    invoice = world["invoice"]
    invoice.status = "void"
    invoice.save(update_fields=["status"])

    response = pay(world["client"], invoice)
    assert response.status_code == 409, response.data
    assert not Payment.all_objects.filter(invoice=invoice).exists()


@settings(max_examples=100)
@given(currency=st.sampled_from(["USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD"]))
def test_a_currency_the_gateway_account_cannot_settle_is_refused(currency):
    """17.8: refused before any row is written."""
    world = membership_world(currency=currency)
    invoice = world["invoice"]
    assert invoice.currency == currency

    response = pay(world["client"], invoice)
    assert response.status_code == 400, response.data
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"
    assert not Payment.all_objects.filter(invoice=invoice).exists()

    with pytest.raises(CurrencyMismatch):
        create_order(invoice, actor=world["member"].user)


def test_idempotency_keys_are_unique_across_the_platform():
    """16.3: the key is what stops one logical operation becoming two Payments."""
    world = membership_world()
    first_invoice = world["invoice"]
    second_invoice = factories.make_invoice(
        world["gym"],
        world["member"].user,
        taxable="900.00",
        membership=world["membership"],
    )

    a = create_order(first_invoice, actor=world["member"].user)["payment"]
    b = create_order(second_invoice, actor=world["member"].user)["payment"]
    assert a.idempotency_key != b.idempotency_key

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Payment.objects.create(
                invoice=second_invoice,
                gym=world["gym"],
                amount=Decimal("10.00"),
                currency="INR",
                status="pending",
                idempotency_key=a.idempotency_key,
                recorded_on=world["gym"].today(),
            )


def test_gateway_payment_reference_is_unique_only_when_present():
    """16.4: two null references are fine; two identical real ones are not."""
    world = membership_world()
    invoice = world["invoice"]

    first = factories.make_payment(invoice, payment_ref=None)
    second = factories.make_payment(invoice, payment_ref=None)
    assert first.gateway_payment_ref is None and second.gateway_payment_ref is None

    first.gateway_payment_ref = "pay_shared_reference"
    first.save(update_fields=["gateway_payment_ref"])

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            second.gateway_payment_ref = "pay_shared_reference"
            second.save(update_fields=["gateway_payment_ref"])


def test_order_response_never_carries_a_secret():
    """23.5: only the public key id crosses the boundary."""
    world = membership_world()
    result = create_order(world["invoice"], actor=world["member"].user)
    body = order_response(result["order"])

    serialised = str(body)
    assert FAKE_KEY_SECRET not in serialised
    assert FAKE_WEBHOOK_SECRET not in serialised
    assert body["key_id"] == get_adapter().public_key


def test_a_failed_attempt_can_be_retried():
    """18.5 plus 17.6 together: a failure leaves the invoice payable."""
    world = membership_world()
    invoice = world["invoice"]

    with override_settings(PAYMENT_GATEWAY_ADAPTER=FakeRazorpayAdapter(fail_mode="timeout")):
        assert pay(world["client"], invoice).status_code == 502

    retry = pay(world["client"], invoice)
    assert retry.status_code == 201, retry.data
    assert Payment.all_objects.filter(invoice=invoice).count() == 1
