"""Razorpay adapter.

Two rules the rest of the payment layer depends on:

* `verify_webhook` performs HMAC-SHA256 verification over the **raw bytes** before
  anything parses them. Parsing first would mean an unsigned payload could reach
  JSON handling, and a parse error would leak that the body was even read (18.2).
* The secret key and webhook secret are read from settings, used, and never
  returned or logged. Only the public key id is ever sent to a client (23.5).

The adapter is resolved through `get_adapter()`, which honours a settings override.
That is the seam the fake adapter plugs into, so no unit or property test opens a
socket.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

from django.conf import settings

from core.exceptions import CurrencyMismatch, GatewayError, SignatureInvalid
from core.services.money import to_minor_units

logger = logging.getLogger("core.payments")

#: Settings key the tests override to install a fake adapter.
ADAPTER_SETTING = "PAYMENT_GATEWAY_ADAPTER"

GATEWAY_NAME = "razorpay"

#: Razorpay event kinds this platform acts on. Anything else is recorded and ignored.
EVENT_PAYMENT_CAPTURED = "payment.captured"
EVENT_PAYMENT_AUTHORIZED = "payment.authorized"
EVENT_PAYMENT_FAILED = "payment.failed"

SUCCESS_EVENTS = frozenset({EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_AUTHORIZED})
FAILURE_EVENTS = frozenset({EVENT_PAYMENT_FAILED})


# ============ VALUE OBJECTS ============

@dataclass(frozen=True)
class GatewayOrder:
    """What the client needs to open checkout. Frozen: nothing mutates an order."""

    order_ref: str
    amount_minor: int
    currency: str
    public_key: str
    receipt: str | None = None


@dataclass(frozen=True)
class WebhookEventData:
    """The subset of a webhook payload this platform acts on."""

    event_id: str
    kind: str
    order_ref: str | None
    payment_ref: str | None
    method: str | None
    amount_minor: int | None
    currency: str | None

    @property
    def is_success(self):
        return self.kind in SUCCESS_EVENTS

    @property
    def is_failure(self):
        return self.kind in FAILURE_EVENTS


# ============ ADAPTER ============

class RazorpayAdapter:
    """Thin, synchronous wrapper. Deliberately holds no state between calls."""

    name = GATEWAY_NAME

    def __init__(self, key_id=None, key_secret=None, webhook_secret=None, account_currency=None):
        self._key_id = key_id or getattr(settings, "RAZORPAY_KEY_ID", "")
        self._key_secret = key_secret or getattr(settings, "RAZORPAY_KEY_SECRET", "")
        self._webhook_secret = webhook_secret or getattr(
            settings, "RAZORPAY_WEBHOOK_SECRET", ""
        )
        self.account_currency = (
            account_currency or getattr(settings, "RAZORPAY_ACCOUNT_CURRENCY", "INR")
        ).upper()

    # -- public key is the only credential that may leave the platform ---------

    @property
    def public_key(self):
        return self._key_id

    def _client(self):
        try:
            import razorpay
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise GatewayError("The razorpay client library is not installed.") from exc
        return razorpay.Client(auth=(self._key_id, self._key_secret))

    # -- orders ---------------------------------------------------------------

    def assert_currency_supported(self, currency):
        if (currency or "").upper() != self.account_currency:
            raise CurrencyMismatch(
                f"This gateway account settles in {self.account_currency}; the "
                f"invoice is denominated in {currency}.",
                details={"field": "currency", "expected": self.account_currency},
            )

    def create_order(self, invoice, idempotency_key):
        """Create a gateway order for an Invoice.

        Raises `CurrencyMismatch` before any network call, and `GatewayError` for
        anything the gateway does wrong or any failure to reach it. The caller runs
        this last inside its transaction, so either exception leaves no pending
        Payment behind (17.6).
        """
        self.assert_currency_supported(invoice.currency)
        amount_minor = to_minor_units(invoice.total_amount, invoice.currency)

        payload = {
            "amount": amount_minor,
            "currency": invoice.currency.upper(),
            "receipt": invoice.number,
            # Razorpay treats receipt as advisory; the idempotency key is ours.
            "notes": {"idempotency_key": idempotency_key, "invoice": invoice.number},
        }

        try:
            order = self._client().order.create(data=payload)
        except Exception as exc:  # noqa: BLE001 - any failure is a gateway failure
            # Log the reference-level facts only. Never the payload, never a secret.
            logger.error(
                "gateway order failed invoice=%s amount=%s currency=%s error=%s",
                invoice.number,
                invoice.total_amount,
                invoice.currency,
                exc.__class__.__name__,
            )
            raise GatewayError(
                "The payment gateway could not be reached. No payment was recorded."
            ) from exc

        order_ref = (order or {}).get("id")
        if not order_ref:
            raise GatewayError("The payment gateway returned no order reference.")

        logger.info(
            "gateway order created order_ref=%s amount=%s currency=%s",
            order_ref,
            invoice.total_amount,
            invoice.currency,
        )
        return GatewayOrder(
            order_ref=order_ref,
            amount_minor=amount_minor,
            currency=invoice.currency.upper(),
            public_key=self.public_key,
            receipt=invoice.number,
        )

    # -- webhooks -------------------------------------------------------------

    def verify_webhook(self, raw_body, signature):
        """HMAC-SHA256 over the raw bytes, then parse. Never the other way round."""
        if not signature:
            raise SignatureInvalid("The webhook signature header is missing.")
        if not self._webhook_secret:
            # Refusing is the only safe answer: without a secret every caller
            # could forge a settlement.
            raise SignatureInvalid("No webhook secret is configured.")

        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature.strip()):
            raise SignatureInvalid("The webhook signature does not verify.")

        try:
            return json.loads(raw_body or b"{}")
        except (ValueError, TypeError) as exc:
            # Signature verified but the body is not JSON: that is a gateway bug,
            # not a forgery, so it is reported distinctly.
            raise GatewayError("The webhook body verified but is not valid JSON.") from exc

    def parse_event(self, payload):
        """Extract the fields the settlement path needs from a verified payload."""
        entity = _first_payment_entity(payload)
        return WebhookEventData(
            event_id=str(
                payload.get("id")
                or payload.get("event_id")
                or (entity or {}).get("id")
                or ""
            ),
            kind=str(payload.get("event") or payload.get("kind") or ""),
            order_ref=(entity or {}).get("order_id"),
            payment_ref=(entity or {}).get("id"),
            method=_normalise_method((entity or {}).get("method")),
            amount_minor=(entity or {}).get("amount"),
            currency=((entity or {}).get("currency") or None),
        )


def _first_payment_entity(payload):
    """Razorpay nests the payment under payload.payment.entity."""
    container = (payload or {}).get("payload") or {}
    for key in ("payment", "order", "refund"):
        entity = (container.get(key) or {}).get("entity")
        if entity:
            return entity
    # Flattened shape, used by the fake adapter and by captured fixtures.
    return (payload or {}).get("entity") or {}


#: Razorpay reports several wallet/UPI variants; the model stores three choices.
_METHOD_MAP = {
    "upi": "upi",
    "card": "card",
    "netbanking": "netbanking",
    "wallet": "upi",
    "emi": "card",
}


def _normalise_method(value):
    if not value:
        return None
    return _METHOD_MAP.get(str(value).lower())


# ============ RESOLUTION ============

def get_adapter():
    """Return the configured adapter, honouring a settings override.

    The override may be an instance, a class, or a dotted path, so a test can inject
    a fake without knowing how the production adapter is constructed.
    """
    override = getattr(settings, ADAPTER_SETTING, None)
    if override is None:
        return RazorpayAdapter()
    if isinstance(override, str):
        from django.utils.module_loading import import_string

        return import_string(override)()
    if isinstance(override, type):
        return override()
    return override
