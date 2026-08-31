"""Order creation, webhook settlement, and refunds.

The platform never sees card data. It creates an order, hands the client an order
reference plus the *public* key, and the card details go straight from the browser to
the gateway. Any request body carrying a card-data field name — at any nesting depth
— is refused with 400 before anything else happens, and its value is never logged
(23.2, 23.4).

Order creation puts the Payment insert and the gateway call in one transaction with
the gateway call **last**. A gateway failure therefore rolls the pending Payment
back, so there is no orphan `pending` row for reconciliation to puzzle over (17.6).
"""
from __future__ import annotations

import logging
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.exceptions import (
    CardDataRejected,
    Http409,
    InvoiceAlreadyPaid,
)
from core.models import Payment, WebhookEvent
from core.services.audit import ACTION_REFUND, AuditedChange, record_create
from core.services.gateway import get_adapter
from core.services.money import from_minor_units

logger = logging.getLogger("core.payments")

#: Field-name fragments that indicate card data. Matching is done on a normalised
#: key (lowercased, separators stripped) so `cardNumber`, `card_number` and
#: `CARD-NUMBER` all collapse to the same token.
CARD_DATA_TOKENS = (
    "cardnumber",
    "cardno",
    "pan",
    "cvv",
    "cvc",
    "cvn",
    "securitycode",
    "expiry",
    "expmonth",
    "expyear",
    "expirymonth",
    "expiryyear",
    "cardholder",
    "trackdata",
    "magstripe",
)

#: Exact keys that are card data on their own.
CARD_DATA_EXACT = frozenset({"card", "cards", "cardinfo", "carddetails"})

MAX_INSPECT_DEPTH = 12


def _normalise_key(key):
    return "".join(character for character in str(key).lower() if character.isalnum())


def find_card_data_field(payload, _depth=0):
    """Return the first card-data key found anywhere in the body, or None.

    Recurses through dicts and lists because "at any nesting depth" is the actual
    requirement; a top-level-only check is trivially bypassed by wrapping the field
    in an object.
    """
    if _depth > MAX_INSPECT_DEPTH:
        return None

    if isinstance(payload, dict):
        for key, value in payload.items():
            normalised = _normalise_key(key)
            if normalised in CARD_DATA_EXACT or any(
                token in normalised for token in CARD_DATA_TOKENS
            ):
                return str(key)
            found = find_card_data_field(value, _depth + 1)
            if found:
                return found
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found = find_card_data_field(item, _depth + 1)
            if found:
                return found
    return None


def reject_card_data(payload):
    """400 when the body carries card data. The value is never logged (23.4)."""
    field = find_card_data_field(payload)
    if field is None:
        return
    # Field *name* only. Logging the value is precisely what must not happen.
    logger.warning("card data rejected field=%s", field)
    raise CardDataRejected(
        "Card data must never be sent to this platform. Use the gateway's "
        "client-side checkout instead.",
        details={"field": field},
    )


def strip_card_data(payload, _depth=0):
    """Copy of `payload` with every card-data key removed, for safe storage (18.7)."""
    if _depth > MAX_INSPECT_DEPTH:
        return None

    if isinstance(payload, dict):
        cleaned = {}
        for key, value in payload.items():
            normalised = _normalise_key(key)
            if normalised in CARD_DATA_EXACT or any(
                token in normalised for token in CARD_DATA_TOKENS
            ):
                continue
            cleaned[key] = strip_card_data(value, _depth + 1)
        return cleaned
    if isinstance(payload, (list, tuple)):
        return [strip_card_data(item, _depth + 1) for item in payload]
    return payload


# ============ IDEMPOTENCY ============

def new_idempotency_key(invoice):
    """Unique per logical pay attempt. Scoped by invoice for readability in logs."""
    return f"inv{invoice.pk}-{secrets.token_hex(16)}"


# ============ ORDER CREATION ============

def succeeded_payment_for(invoice):
    return invoice.payments.filter(status="succeeded", deleted_at__isnull=True).first()


@transaction.atomic
def create_order(invoice, *, actor=None, adapter=None, request_data=None):
    """Create a `pending` Payment and a gateway order, or neither.

    Ordering inside the transaction is the whole design: validate, insert the
    Payment, then call the gateway. The gateway call being last means its failure
    rolls the insert back.
    """
    if request_data is not None:
        reject_card_data(request_data)

    if invoice.status == "settled" or succeeded_payment_for(invoice) is not None:
        raise InvoiceAlreadyPaid(
            f"Invoice {invoice.number} has already been paid.",
            details={"invoice": invoice.number},
        )
    if invoice.status == "void":
        raise Http409(
            f"Invoice {invoice.number} has been voided and cannot be paid.",
            details={"invoice": invoice.number},
        )

    adapter = adapter or get_adapter()
    # Raises CurrencyMismatch before any row is written (17.8).
    adapter.assert_currency_supported(invoice.currency)

    idempotency_key = new_idempotency_key(invoice)
    payment = Payment(
        invoice=invoice,
        gym=invoice.gym,
        amount=invoice.total_amount,
        currency=invoice.currency,
        status="pending",
        gateway=getattr(adapter, "name", "razorpay"),
        idempotency_key=idempotency_key,
        recorded_on=invoice.gym.today(),
    )
    payment.save()

    # Last statement in the block on purpose.
    order = adapter.create_order(invoice, idempotency_key)

    payment.gateway_order_ref = order.order_ref
    payment.save(update_fields=["gateway_order_ref"])
    record_create(payment, actor=actor, gym=invoice.gym)

    logger.info(
        "order created order_ref=%s amount=%s currency=%s status=%s",
        order.order_ref,
        payment.amount,
        payment.currency,
        payment.status,
    )
    return {"payment": payment, "order": order}


def order_response(order):
    """Client-facing order body. Carries the public key id and nothing else (23.5)."""
    return {
        "order_ref": order.order_ref,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "key_id": order.public_key,
        "receipt": order.receipt,
    }


# ============ WEBHOOK SETTLEMENT ============

class WebhookOutcome:
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"


def record_event(event, raw_payload):
    """`get_or_create` on the gateway's event id is the replay guard (18.9)."""
    stored, created = WebhookEvent.objects.get_or_create(
        event_id=event.event_id,
        defaults={
            "kind": event.kind,
            # Card data is stripped before storage, unconditionally.
            "raw_payload": strip_card_data(raw_payload) or {},
        },
    )
    return stored, created


@transaction.atomic
def process_event(event, raw_payload, *, actor=None, now=None):
    """Apply a verified gateway event exactly once.

    Concurrency is handled by two independent layers, because they guard different
    things: the unique `event_id` stops the same delivery being applied twice, and
    `select_for_update()` on the Payment row serialises two *different* deliveries
    that touch the same payment.
    """
    from core.services.invoicing import settle

    now = now or timezone.now()
    stored, created = record_event(event, raw_payload)

    if not created and stored.processed_at is not None:
        return {"outcome": WebhookOutcome.DUPLICATE, "event": stored, "payment": None}

    if not event.order_ref:
        stored.reconciliation_required = True
        stored.processed_at = now
        stored.save(update_fields=["reconciliation_required", "processed_at"])
        return {"outcome": WebhookOutcome.UNMATCHED, "event": stored, "payment": None}

    payment = (
        Payment.all_objects.select_for_update()
        .filter(gateway_order_ref=event.order_ref)
        .first()
    )

    if payment is None:
        # 200 with a reconciliation flag, not an error: an error makes the gateway
        # retry an event this platform can never match (18.7).
        stored.reconciliation_required = True
        stored.processed_at = now
        stored.save(update_fields=["reconciliation_required", "processed_at"])
        logger.warning("webhook unmatched order_ref=%s", event.order_ref)
        return {"outcome": WebhookOutcome.UNMATCHED, "event": stored, "payment": None}

    stored.matched_payment = payment
    stored.save(update_fields=["matched_payment"])

    if payment.status in {"succeeded", "refunded"} and event.is_success:
        stored.processed_at = now
        stored.save(update_fields=["processed_at"])
        return {"outcome": WebhookOutcome.DUPLICATE, "event": stored, "payment": payment}

    if event.is_success:
        _apply_success(payment, event, actor=actor, now=now)
        settle(payment.invoice, payment, actor=actor, now=now)
        outcome = WebhookOutcome.PROCESSED
    elif event.is_failure:
        _apply_failure(payment, event, actor=actor)
        outcome = WebhookOutcome.PROCESSED
    else:
        outcome = WebhookOutcome.IGNORED

    stored.processed_at = now
    stored.save(update_fields=["processed_at"])

    logger.info(
        "webhook processed event=%s kind=%s order_ref=%s payment_ref=%s status=%s",
        stored.event_id,
        event.kind,
        event.order_ref,
        event.payment_ref,
        payment.status,
    )
    return {"outcome": outcome, "event": stored, "payment": payment}


def _apply_success(payment, event, *, actor=None, now=None):
    with AuditedChange(
        payment,
        actor=actor,
        gym=payment.gym,
        fields=["status", "gateway_payment_ref", "method", "paid_at"],
    ):
        payment.status = "succeeded"
        payment.gateway_payment_ref = event.payment_ref or payment.gateway_payment_ref
        payment.method = event.method or payment.method
        payment.paid_at = payment.paid_at or now or timezone.now()
        try:
            payment.save(
                update_fields=["status", "gateway_payment_ref", "method", "paid_at"]
            )
        except IntegrityError:
            # Another delivery already claimed this gateway_payment_ref. That is a
            # duplicate, not a failure: leave the winner's row alone.
            payment.refresh_from_db()


def _apply_failure(payment, event, *, actor=None):
    """A failed payment leaves the Invoice open so the member can retry (18.5)."""
    with AuditedChange(
        payment, actor=actor, gym=payment.gym, fields=["status", "gateway_payment_ref"]
    ):
        payment.status = "failed"
        payment.gateway_payment_ref = event.payment_ref or payment.gateway_payment_ref
        payment.save(update_fields=["status", "gateway_payment_ref"])


# ============ REFUNDS ============

@transaction.atomic
def refund(original, amount=None, *, actor=None, reason=""):
    """A refund is a new Payment referencing the original, never an edit (22.7)."""
    if original.status != "succeeded":
        raise Http409(
            "Only a succeeded payment can be refunded.",
            details={"field": "status", "status": original.status},
        )

    amount = amount if amount is not None else original.amount
    if amount > original.amount:
        raise Http409(
            f"A refund cannot exceed the original payment of {original.amount}.",
            details={"field": "amount"},
        )

    reversal = Payment.objects.create(
        invoice=original.invoice,
        gym=original.gym,
        amount=amount,
        currency=original.currency,
        status="refunded",
        gateway=original.gateway,
        gateway_order_ref=original.gateway_order_ref,
        idempotency_key=f"refund-{original.pk}-{secrets.token_hex(8)}",
        method=original.method,
        paid_at=timezone.now(),
        recorded_on=original.gym.today(),
        refund_of=original,
    )
    record_create(reversal, actor=actor, gym=original.gym)

    # The original keeps its amount and its references; only the status moves.
    with AuditedChange(
        original, actor=actor, gym=original.gym, fields=["status"], action=ACTION_REFUND
    ):
        original.status = "refunded"
        original.save(update_fields=["status"])

    return reversal


def ledger_balance(profile):
    """Settled invoice totals minus refunds, versus succeeded payments (22.5).

    Returned as a pair rather than a boolean so the stateful property test can report
    the two numbers when they disagree.
    """
    from decimal import Decimal

    from core.models import Invoice

    invoices = Invoice.objects.filter(
        membership__member=profile, status="settled", deleted_at__isnull=True
    )
    invoiced = sum((invoice.total_amount for invoice in invoices), Decimal("0.00"))

    payments = Payment.objects.filter(
        invoice__membership__member=profile, deleted_at__isnull=True
    )
    received = sum(
        (payment.amount for payment in payments if payment.status == "succeeded"),
        Decimal("0.00"),
    )
    refunded = sum(
        (payment.amount for payment in payments if payment.status == "refunded" and payment.refund_of_id),
        Decimal("0.00"),
    )
    return {"invoiced": invoiced, "received": received, "refunded": refunded}
