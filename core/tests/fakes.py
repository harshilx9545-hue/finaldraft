"""In-memory gateway that matches `RazorpayAdapter`'s interface exactly.

Installed through the `PAYMENT_GATEWAY_ADAPTER` settings override, which is the same
seam `get_adapter()` reads in production. No unit or property test opens a socket.

Failure modes are injectable rather than monkeypatched, because Property 22 has to
drive *every* gateway failure mode and assert that none of them leaves a pending
Payment behind:

    gateway = FakeRazorpayAdapter(fail_mode="unreachable")
    gateway = FakeRazorpayAdapter(fail_mode="no_order_ref")
    gateway = FakeRazorpayAdapter(fail_mode="error_after_order")   # order made, call fails
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json

from core.exceptions import CurrencyMismatch, GatewayError, SignatureInvalid
from core.services.gateway import (
    EVENT_PAYMENT_CAPTURED,
    EVENT_PAYMENT_FAILED,
    GATEWAY_NAME,
    GatewayOrder,
    WebhookEventData,
    _normalise_method,
)
from core.services.money import to_minor_units

FAKE_PUBLIC_KEY = "rzp_test_fake_public"
FAKE_KEY_SECRET = "fake_key_secret"
FAKE_WEBHOOK_SECRET = "fake_webhook_secret"

#: Every way the adapter is allowed to fail, for exhaustive property coverage.
FAILURE_MODES = (
    None,
    "unreachable",         # network error before the order is created
    "gateway_rejected",    # gateway returns an error response
    "no_order_ref",        # 200 response with no order id
    "error_after_order",   # order exists remotely but the call raises
    "timeout",
)


class FakeRazorpayAdapter:
    """Same methods, same exceptions, same frozen return types. No network."""

    name = GATEWAY_NAME

    def __init__(
        self,
        *,
        account_currency="INR",
        webhook_secret=FAKE_WEBHOOK_SECRET,
        public_key=FAKE_PUBLIC_KEY,
        fail_mode=None,
    ):
        self.account_currency = account_currency.upper()
        self._webhook_secret = webhook_secret
        self._public_key = public_key
        self.fail_mode = fail_mode

        #: Everything the fake was asked to do, for assertions.
        self.orders = {}
        self.create_order_calls = []
        self.verify_calls = []
        self._counter = itertools.count(1)

    # -- credential containment ----------------------------------------------

    @property
    def public_key(self):
        return self._public_key

    @property
    def secrets(self):
        """The values Property 26 asserts never appear in a response or a log."""
        return (FAKE_KEY_SECRET, self._webhook_secret)

    # -- orders ---------------------------------------------------------------

    def assert_currency_supported(self, currency):
        if (currency or "").upper() != self.account_currency:
            raise CurrencyMismatch(
                f"This gateway account settles in {self.account_currency}; the "
                f"invoice is denominated in {currency}.",
                details={"field": "currency", "expected": self.account_currency},
            )

    def next_order_ref(self):
        return f"order_fake{next(self._counter):08d}"

    def create_order(self, invoice, idempotency_key):
        self.create_order_calls.append((invoice.pk, idempotency_key))
        self.assert_currency_supported(invoice.currency)

        if self.fail_mode in {"unreachable", "timeout"}:
            raise GatewayError(
                "The payment gateway could not be reached. No payment was recorded."
            )
        if self.fail_mode == "gateway_rejected":
            raise GatewayError("The payment gateway rejected the order.")
        if self.fail_mode == "no_order_ref":
            raise GatewayError("The payment gateway returned no order reference.")

        amount_minor = to_minor_units(invoice.total_amount, invoice.currency)
        order_ref = self.next_order_ref()
        self.orders[order_ref] = {
            "invoice": invoice.pk,
            "amount": amount_minor,
            "currency": invoice.currency.upper(),
            "idempotency_key": idempotency_key,
        }

        if self.fail_mode == "error_after_order":
            # The remote side succeeded but the call raises. The caller must still
            # end up with no pending Payment row.
            raise GatewayError("The gateway response could not be read.")

        return GatewayOrder(
            order_ref=order_ref,
            amount_minor=amount_minor,
            currency=invoice.currency.upper(),
            public_key=self.public_key,
            receipt=invoice.number,
        )

    # -- webhooks -------------------------------------------------------------

    def sign(self, raw_body, secret=None):
        """Produce the signature a genuine gateway would send, for test fixtures."""
        return hmac.new(
            (secret or self._webhook_secret).encode("utf-8"),
            raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_webhook(self, raw_body, signature):
        self.verify_calls.append(bool(signature))
        if not signature:
            raise SignatureInvalid("The webhook signature header is missing.")
        if not hmac.compare_digest(self.sign(raw_body), signature.strip()):
            raise SignatureInvalid("The webhook signature does not verify.")
        try:
            return json.loads(raw_body or b"{}")
        except (ValueError, TypeError) as exc:
            raise GatewayError("The webhook body verified but is not valid JSON.") from exc

    def parse_event(self, payload):
        entity = (payload or {}).get("entity") or (
            ((payload or {}).get("payload") or {}).get("payment") or {}
        ).get("entity") or {}
        return WebhookEventData(
            event_id=str(payload.get("id") or entity.get("id") or ""),
            kind=str(payload.get("event") or ""),
            order_ref=entity.get("order_id"),
            payment_ref=entity.get("id"),
            method=_normalise_method(entity.get("method")),
            amount_minor=entity.get("amount"),
            currency=entity.get("currency"),
        )


# ============ PAYLOAD BUILDERS ============

def build_event_payload(
    *,
    event_id,
    kind=EVENT_PAYMENT_CAPTURED,
    order_ref=None,
    payment_ref=None,
    method="upi",
    amount_minor=10000,
    currency="INR",
    include_card_data=False,
):
    """A payload shaped like a real Razorpay webhook.

    `include_card_data` adds the keys the handler must strip before storing the
    payload, so Property 26 can assert they never reach the database.
    """
    entity = {
        "id": payment_ref or "pay_fake00000001",
        "order_id": order_ref,
        "method": method,
        "amount": amount_minor,
        "currency": currency,
        "status": "captured" if kind == EVENT_PAYMENT_CAPTURED else "failed",
    }
    if include_card_data:
        entity["card"] = {
            "number": "4111111111111111",
            "cvv": "123",
            "expiry_month": 12,
            "expiry_year": 2030,
        }
        entity["card_number"] = "4111111111111111"

    return {
        "id": event_id,
        "event": kind,
        "entity": entity,
        "payload": {"payment": {"entity": entity}},
        "created_at": 1700000000,
    }


def signed_body(adapter, payload, *, secret=None, tamper=False):
    """(raw_bytes, signature) for a payload.

    `tamper=True` returns a signature over *different* bytes, which is the third
    failure case Property 24 requires alongside absent and wrong-secret.
    """
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signed_over = raw + b" " if tamper else raw
    return raw, adapter.sign(signed_over, secret=secret)


def failure_payload(**kwargs):
    kwargs.setdefault("kind", EVENT_PAYMENT_FAILED)
    return build_event_payload(**kwargs)


# ============ RECOVERY PLANNERS ============

class ScriptedRecoveryPlanner:
    """A recovery planner that returns exactly what a test tells it to.

    The guardrails in `core.services.recovery_agent` only matter against a planner that
    misbehaves, and a real model cannot be relied on to misbehave on cue. This one is
    installed the same way the production planner is resolved - through the
    `RECOVERY_LLM_CLIENT` settings override, or by passing `llm_client=` - and can be
    driven three ways:

        # behave sensibly, but force one argument
        ScriptedRecoveryPlanner(argument_overrides={"discount_percentage": 95})

        # a fixed tool call, every time
        ScriptedRecoveryPlanner(tool="apply_recovery_discount_and_get_link",
                                arguments={"gym_id": other.pk, "member_id": 1,
                                           "discount_percentage": 50})

        # a scripted sequence; the last entry repeats once exhausted
        ScriptedRecoveryPlanner(calls=[first_call, second_call])

    `argument_overrides` is the most useful form for property tests: the planner still
    picks a tier-appropriate tool, so the test drives one guard at a time rather than
    also having to construct a plausible whole decision.
    """

    name = "scripted"

    def __init__(
        self,
        tool=None,
        arguments=None,
        reasoning="scripted decision",
        *,
        calls=None,
        argument_overrides=None,
    ):
        self.tool = tool
        self.arguments = arguments
        self.reasoning = reasoning
        self.calls = list(calls) if calls else None
        self.argument_overrides = argument_overrides or {}

        #: Every context it was asked about, and every call it returned, for assertions.
        self.contexts = []
        self.returned = []

    def complete(self, *, messages, tools=None, context=None):
        from core.services.recovery_agent import HeuristicRecoveryPlanner, ToolCall

        context = context or {}
        self.contexts.append(context)

        if self.calls:
            # The last scripted call repeats, so a test driving several rounds does not
            # have to know how many invoices the batch will find.
            call = self.calls.pop(0) if len(self.calls) > 1 else self.calls[0]
        elif self.tool is not None:
            arguments = self.arguments
            if callable(arguments):
                arguments = arguments(context)
            call = ToolCall(
                name=self.tool,
                arguments=dict(arguments or {}),
                reasoning=self.reasoning,
            )
        else:
            base = HeuristicRecoveryPlanner().complete(
                messages=messages, tools=tools, context=context
            )
            call = ToolCall(
                name=base.name,
                arguments=dict(base.arguments),
                reasoning=base.reasoning,
            )

        if self.argument_overrides:
            call = ToolCall(
                name=call.name,
                arguments={**call.arguments, **self.argument_overrides},
                reasoning=call.reasoning,
            )

        self.returned.append(call)
        return call


class UnavailableRecoveryPlanner:
    """A planner that is always down, for the fallback path.

    A hosted model being unreachable must not stop a dunning batch, and the only way to
    assert that is to have a planner that reliably fails.
    """

    name = "unavailable"

    def __init__(self, message="scripted outage"):
        self.message = message
        self.calls = 0

    def complete(self, *, messages, tools=None, context=None):
        from core.services.recovery_agent import LLMUnavailable

        self.calls += 1
        raise LLMUnavailable(self.message)
