"""Feature: gym-saas-core, Property 24.

The ordering claim is the substance here: verification happens over the raw bytes
*before* anything parses them. A test that only checked "bad signature gives 400"
would pass even on an implementation that parsed first, so the decisive case is
garbage bytes:

* garbage + wrong signature -> 400 SIGNATURE_INVALID (the signature was checked
  first, so the parse never happened)
* garbage + *correct* signature -> 502 GATEWAY_ERROR (verification passed, and only
  then did parsing fail)

If parsing came first, the first case would report a parse error instead.
"""
import pytest
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from core.models import Invoice, Membership, Payment, WebhookEvent
from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
from core.services.payments import create_order
from core.tests import factories
from core.tests.fakes import build_event_payload, signed_body
from core.tests.strategies import gateway_events

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "core:razorpay-webhook"

#: Secrets that are not the configured one. A signature computed with any of these
#: must be refused. The empty string is deliberately absent: the signing helper
#: treats a falsy secret as "use the configured one", so passing it would produce a
#: genuinely valid signature and test the opposite of what is intended. The
#: unconfigured-secret case has its own test at the bottom of this module.
WRONG_SECRETS = [
    "wrong_secret",
    "fake_webhook_secre",       # one character short of the real value
    "fake_webhook_secrets",     # one character long
    "FAKE_WEBHOOK_SECRET",      # right characters, wrong case
    "0" * 32,
]


def snapshot_financial_state():
    """Every row that a webhook is capable of touching, plus its mutable fields."""
    return {
        "payments": sorted(
            Payment.all_objects.values_list(
                "pk", "status", "gateway_payment_ref", "method", "paid_at"
            )
        ),
        "invoices": sorted(Invoice.all_objects.values_list("pk", "status")),
        "memberships": sorted(
            Membership.all_objects.values_list("pk", "start_date", "end_date")
        ),
    }


def world_with_live_order():
    from core.services.memberships import create_membership

    gym = factories.make_gym()
    factories.make_owner(gym)
    plan = factories.make_membership_plan(gym, price="1500.00", duration_days=30)
    member = factories.make_member(gym, plan=plan)
    result = create_membership(member, plan, start=gym.today())
    order = create_order(result["invoice"], actor=member.user)
    return {
        "gym": gym,
        "member": member,
        "invoice": result["invoice"],
        "payment": order["payment"],
        "order_ref": order["order"].order_ref,
        "client": APIClient(),
    }


def post_raw(client, raw, signature):
    headers = {}
    if signature is not None:
        headers["HTTP_X_RAZORPAY_SIGNATURE"] = signature
    return client.post(
        reverse(WEBHOOK_URL), data=raw, content_type="application/json", **headers
    )


# Feature: gym-saas-core, Property 24: For any request body and for any signature that
# is absent, computed with a wrong secret, or computed over different bytes, the
# Webhook_Handler responds 400 with the signature error rather than a parse error, and
# every Payment, Invoice, and Membership row is unchanged.
# Validates: Requirements 18.2, 18.3
@settings(max_examples=100)
@given(
    payload=gateway_events(),
    failure=st.sampled_from(["absent", "empty", "wrong_secret", "tampered", "garbage"]),
    wrong_secret=st.sampled_from(WRONG_SECRETS),
)
def test_an_unverified_webhook_is_refused_and_changes_nothing(
    payload, failure, wrong_secret
):
    world = world_with_live_order()
    adapter = get_adapter()
    # The event names a real order, so a *verified* delivery would settle it. Any
    # change at all therefore means verification failed to stop the request.
    payload = dict(payload)
    payload["entity"] = dict(payload["entity"], order_id=world["order_ref"])
    payload["payload"] = {"payment": {"entity": payload["entity"]}}

    raw, valid_signature = signed_body(adapter, payload)
    before = snapshot_financial_state()

    if failure == "absent":
        response = post_raw(world["client"], raw, None)
    elif failure == "empty":
        response = post_raw(world["client"], raw, "")
    elif failure == "wrong_secret":
        _, forged = signed_body(adapter, payload, secret=wrong_secret)
        response = post_raw(world["client"], raw, forged)
    elif failure == "tampered":
        _, over_other_bytes = signed_body(adapter, payload, tamper=True)
        response = post_raw(world["client"], raw, over_other_bytes)
    else:
        # Bytes that are not JSON at all, signed for a different body.
        response = post_raw(world["client"], b"\x00not-json-at-all", valid_signature)

    assert response.status_code == 400, response.data
    body = response.json()
    assert body["error"]["code"] == "SIGNATURE_INVALID"
    assert body["error"]["message"]

    assert snapshot_financial_state() == before
    # A refused request is not even recorded as an event: nothing was verified.
    assert not WebhookEvent.objects.filter(event_id=payload["id"]).exists()


def test_a_signature_over_a_prefix_of_the_body_is_refused():
    """Truncation must not verify: the HMAC covers the whole body."""
    world = world_with_live_order()
    adapter = get_adapter()
    payload = build_event_payload(
        event_id="evt_p24_prefix",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=world["order_ref"],
    )
    raw, _ = signed_body(adapter, payload)
    prefix_signature = adapter.sign(raw[:-1])

    before = snapshot_financial_state()
    response = post_raw(world["client"], raw, prefix_signature)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SIGNATURE_INVALID"
    assert snapshot_financial_state() == before


def test_verification_precedes_parsing():
    """Garbage that verifies reaches parsing; garbage that does not, never does."""
    world = world_with_live_order()
    adapter = get_adapter()
    garbage = b"{not valid json"

    unsigned = post_raw(world["client"], garbage, "deadbeef")
    assert unsigned.status_code == 400
    assert unsigned.json()["error"]["code"] == "SIGNATURE_INVALID"

    signed = post_raw(world["client"], garbage, adapter.sign(garbage))
    # Verified, so parsing was reached and failed there instead.
    assert signed.status_code == 502
    assert signed.json()["error"]["code"] == "GATEWAY_ERROR"

    assert not Payment.all_objects.filter(status="succeeded").exists()


def test_a_correctly_signed_event_is_accepted_so_the_refusals_mean_something():
    """The control case: the same fixture settles when the signature is genuine."""
    world = world_with_live_order()
    adapter = get_adapter()
    payload = build_event_payload(
        event_id="evt_p24_control",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=world["order_ref"],
        payment_ref="pay_p24_control",
    )
    raw, signature = signed_body(adapter, payload)

    response = post_raw(world["client"], raw, signature)
    assert response.status_code == 200, response.data

    world["payment"].refresh_from_db()
    world["invoice"].refresh_from_db()
    assert world["payment"].status == "succeeded"
    assert world["invoice"].status == "settled"


def test_the_webhook_endpoint_has_no_authenticator_and_is_csrf_exempt():
    """18.1/18.10: the signature is the only credential this endpoint accepts."""
    from core.views.webhooks import RazorpayWebhookView

    assert RazorpayWebhookView.authentication_classes == []
    assert getattr(RazorpayWebhookView.as_view(), "csrf_exempt", False) is True

    # A bearer token grants nothing here: an unsigned request is still refused.
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    client = APIClient()
    factories.authenticate(client, owner.user)

    payload = build_event_payload(event_id="evt_p24_authed", order_ref="order_missing")
    response = post_raw(client, signed_body(get_adapter(), payload)[0], None)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SIGNATURE_INVALID"


def test_a_missing_webhook_secret_refuses_every_delivery(settings):
    """With no secret configured, refusing is the only safe answer.

    Signing the body with the real adapter's own (empty) secret is the strongest
    version of this: even a caller who guessed the configuration correctly is
    refused, because an unset secret is treated as "cannot verify", not as
    "verifies against the empty string".
    """
    import hashlib
    import hmac

    from core.services.gateway import RazorpayAdapter

    world = world_with_live_order()
    payload = build_event_payload(
        event_id="evt_p24_nosecret",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=world["order_ref"],
    )
    raw, genuine_signature = signed_body(get_adapter(), payload)

    # Both the setting and the adapter must be cleared: the adapter falls back to
    # the setting when constructed with an empty value.
    settings.RAZORPAY_WEBHOOK_SECRET = ""
    settings.PAYMENT_GATEWAY_ADAPTER = RazorpayAdapter()

    before = snapshot_financial_state()
    empty_secret_signature = hmac.new(b"", raw, hashlib.sha256).hexdigest()

    for signature in (genuine_signature, empty_secret_signature, "anything"):
        response = post_raw(world["client"], raw, signature)
        assert response.status_code == 400, response.data
        assert response.json()["error"]["code"] == "SIGNATURE_INVALID"

    assert snapshot_financial_state() == before
    assert not WebhookEvent.objects.filter(event_id="evt_p24_nosecret").exists()
