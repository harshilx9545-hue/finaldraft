"""Razorpay sandbox integration tests (task 16.6).

Validates: Requirements 17.1, 18.4, 18.5

Marked `@pytest.mark.integration` and excluded from the default run by `pytest.ini`,
because these are the only tests that open a socket. Run them deliberately:

    pytest -q -m integration

They verify *wiring*, not logic: the amount conversion, idempotency and settlement
rules are all property-tested against `FakeRazorpayAdapter`, so three examples are
enough here. What cannot be checked against a fake is that the real client accepts
the payload shape, that a real order reference looks the way the code assumes, and
that a genuine signature verifies.

Credentials come from the environment only. There is no fallback and nothing
sandbox-specific is committed: without `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and
`RAZORPAY_WEBHOOK_SECRET` in the environment these skip, which is the correct
outcome rather than a silent pass.
"""
import json
import os
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Payment
from core.services.gateway import (
    EVENT_PAYMENT_CAPTURED,
    EVENT_PAYMENT_FAILED,
    RazorpayAdapter,
)
from core.services.money import to_minor_units
from core.services.payments import create_order, process_event
from core.tests import factories
from core.tests.fakes import build_event_payload

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

#: Environment variables the sandbox run needs. Absent means skip, never fake.
REQUIRED_ENV = ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET")

#: The smallest chargeable INR amount, so a real sandbox order costs as little as
#: possible.
SMALL_AMOUNT = Decimal("1.00")


#: Markers that identify a value copied from `.env.example` rather than a real
#: sandbox credential. `.env.example` ships placeholders on purpose, and
#: `config.load_dotenv` puts whatever is in `.env` into the environment, so a
#: presence check alone would try to reach Razorpay with a fake key and fail in a
#: way that looks like a gateway outage.
PLACEHOLDER_MARKERS = ("placeholder", "replace", "changeme", "example", "your-", "xxxx")


def looks_like_a_placeholder(value):
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def sandbox_credentials():
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(
            "Razorpay sandbox credentials absent from the environment: "
            f"{', '.join(missing)}. These tests never fall back to a fake or a "
            "committed key."
        )

    placeholders = [
        name for name in REQUIRED_ENV if looks_like_a_placeholder(os.environ[name])
    ]
    if placeholders:
        pytest.skip(
            "Razorpay credentials are still placeholders: "
            f"{', '.join(placeholders)}. Set real sandbox values to run these."
        )

    key_id = os.environ["RAZORPAY_KEY_ID"]
    if not key_id.startswith("rzp_test_"):
        pytest.skip(
            f"RAZORPAY_KEY_ID is {key_id[:8]}..., which is not a test key. Refusing "
            "to run integration tests against a live account."
        )
    return {
        "key_id": key_id,
        "key_secret": os.environ["RAZORPAY_KEY_SECRET"],
        "webhook_secret": os.environ["RAZORPAY_WEBHOOK_SECRET"],
    }


@pytest.fixture
def sandbox_adapter(settings):
    credentials = sandbox_credentials()
    adapter = RazorpayAdapter(
        key_id=credentials["key_id"],
        key_secret=credentials["key_secret"],
        webhook_secret=credentials["webhook_secret"],
        account_currency="INR",
    )
    # Override the autouse fake for this test only.
    settings.PAYMENT_GATEWAY_ADAPTER = adapter
    settings.RAZORPAY_KEY_ID = credentials["key_id"]
    settings.RAZORPAY_WEBHOOK_SECRET = credentials["webhook_secret"]
    return adapter


@pytest.fixture
def payable_invoice():
    from core.services.memberships import create_membership

    gym = factories.make_gym(timezone_name="Asia/Kolkata")
    factories.make_owner(gym)
    plan = factories.make_membership_plan(
        gym, price=str(SMALL_AMOUNT), duration_days=30, currency="INR"
    )
    member = factories.make_member(gym, plan=plan)
    result = create_membership(member, plan, start=gym.today())
    return {"gym": gym, "member": member, "invoice": result["invoice"]}


def test_a_real_sandbox_order_is_created_with_the_expected_shape(
    sandbox_adapter, payable_invoice
):
    """17.1: the live client accepts the payload and returns a usable reference."""
    invoice = payable_invoice["invoice"]

    result = create_order(
        invoice, actor=payable_invoice["member"].user, adapter=sandbox_adapter
    )
    order = result["order"]
    payment = result["payment"]

    # Razorpay order ids are `order_` followed by an alphanumeric suffix.
    assert order.order_ref.startswith("order_"), order.order_ref
    assert len(order.order_ref) > len("order_")
    assert order.currency == "INR"
    assert order.amount_minor == to_minor_units(invoice.total_amount, "INR")
    assert order.receipt == invoice.number
    # The public key is what reaches the browser; the secret never does.
    assert order.public_key == sandbox_adapter.public_key
    assert sandbox_adapter._key_secret not in json.dumps(
        {"order_ref": order.order_ref, "key_id": order.public_key}
    )

    payment.refresh_from_db()
    assert payment.status == "pending"
    assert payment.gateway_order_ref == order.order_ref
    assert payment.gateway == "razorpay"


def test_a_genuinely_signed_webhook_settles_the_payment(sandbox_adapter, payable_invoice):
    """18.4: a real HMAC over real bytes verifies and drives settlement."""
    invoice = payable_invoice["invoice"]
    order = create_order(
        invoice, actor=payable_invoice["member"].user, adapter=sandbox_adapter
    )["order"]

    payload = build_event_payload(
        event_id="evt_integration_captured",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=order.order_ref,
        payment_ref="pay_integration_captured",
        amount_minor=order.amount_minor,
    )
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    # Signed with the configured webhook secret, exactly as Razorpay would.
    import hashlib
    import hmac

    signature = hmac.new(
        os.environ["RAZORPAY_WEBHOOK_SECRET"].encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()

    response = APIClient().post(
        reverse("core:razorpay-webhook"),
        data=raw,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
    )

    assert response.status_code == 200, response.data
    assert response.json()["outcome"] == "processed"

    invoice.refresh_from_db()
    payment = Payment.objects.get(gateway_order_ref=order.order_ref)
    assert payment.status == "succeeded"
    assert payment.paid_at is not None
    assert invoice.status == "settled"


def test_a_sandbox_failure_event_leaves_the_invoice_open(sandbox_adapter, payable_invoice):
    """18.5: a failed payment must not settle anything."""
    invoice = payable_invoice["invoice"]
    order = create_order(
        invoice, actor=payable_invoice["member"].user, adapter=sandbox_adapter
    )["order"]

    payload = build_event_payload(
        event_id="evt_integration_failed",
        kind=EVENT_PAYMENT_FAILED,
        order_ref=order.order_ref,
        payment_ref="pay_integration_failed",
        amount_minor=order.amount_minor,
    )
    process_event(sandbox_adapter.parse_event(payload), payload)

    invoice.refresh_from_db()
    payment = Payment.objects.get(gateway_order_ref=order.order_ref)
    assert payment.status == "failed"
    assert payment.paid_at is None
    assert invoice.status == "open"


def test_the_real_adapter_refuses_a_forged_signature(sandbox_adapter):
    """18.3 against the real verifier, not the fake one."""
    from core.exceptions import SignatureInvalid

    raw = b'{"event":"payment.captured"}'

    with pytest.raises(SignatureInvalid):
        sandbox_adapter.verify_webhook(raw, None)
    with pytest.raises(SignatureInvalid):
        sandbox_adapter.verify_webhook(raw, "0" * 64)

    # And the control: a correct signature verifies and parses.
    import hashlib
    import hmac

    good = hmac.new(
        os.environ["RAZORPAY_WEBHOOK_SECRET"].encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    assert sandbox_adapter.verify_webhook(raw, good) == {"event": "payment.captured"}
