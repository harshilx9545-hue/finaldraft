"""Invoice numbering, GST computation, settlement, and voiding.

Numbering is gapless per (Gym, financial year) because the `InvoiceSequence` row is
locked and incremented in the *same* transaction that inserts the Invoice. A
rolled-back Invoice rolls the increment back with it, so a failed issue attempt
leaves no hole — which is exactly what a tax authority expects of an invoice series
and what Property 20 checks.

Settled invoices are immutable. Corrections are credit notes, never edits (19.7,
19.8).
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.exceptions import InvoiceImmutable
from core.models import CreditNote, Invoice, InvoiceSequence
from core.services.money import quantize_money

logger = logging.getLogger("core.payments")

#: Fitness services fall under SAC 999723; 18% GST, split evenly for intra-state.
DEFAULT_SAC_CODE = "999723"
GST_RATE = Decimal("0.18")

#: Financial fields that may never change once an Invoice is settled.
IMMUTABLE_WHEN_SETTLED = (
    "taxable_value",
    "cgst",
    "sgst",
    "igst",
    "total_amount",
    "currency",
)

DEFAULT_PAYMENT_TERM_DAYS = 7
ZERO = Decimal("0.00")


# ============ FINANCIAL YEAR ============

def financial_year_for(day):
    """Indian financial year containing `day`, formatted `2025-26`.

    April 1 to March 31. A January date belongs to the year that began the previous
    April, which is the off-by-one this function exists to stop people rewriting.
    """
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def financial_year_bounds(fy):
    """(first_day, last_day) for a `2025-26` style financial year string."""
    start_year = int(fy.split("-")[0])
    return datetime.date(start_year, 4, 1), datetime.date(start_year + 1, 3, 31)


# ============ NUMBERING ============

def next_invoice_number(gym, fy):
    """Reserve and format the next number in this Gym's series for this year.

    Must be called inside a transaction: the returned number is only guaranteed
    unique if the caller's Invoice insert shares the transaction that holds the
    sequence lock.
    """
    sequence, _ = InvoiceSequence.objects.get_or_create(gym=gym, financial_year=fy)
    locked = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)

    value = locked.next_value
    locked.next_value = value + 1
    locked.save(update_fields=["next_value"])

    return f"{gym.slug}/{fy}/{value:05d}", value


# ============ TAX ============

@dataclass(frozen=True)
class TaxBreakdown:
    """All-None when the issuer has no GSTIN; otherwise exactly one split is set."""

    cgst: Decimal | None
    sgst: Decimal | None
    igst: Decimal | None
    hsn_sac: str | None

    @property
    def total(self):
        return sum(
            (part for part in (self.cgst, self.sgst, self.igst) if part is not None),
            ZERO,
        )


def compute_tax(taxable, issuer_gstin, intra_state=True, *, sac=DEFAULT_SAC_CODE, rate=GST_RATE):
    """GST split for a taxable value.

    No GSTIN means the issuer is not registered, so no tax is charged and every tax
    field stays null — not zero. Null and 0.00 mean different things on an invoice:
    one is "not applicable", the other is "applicable, and nil" (19.5).
    """
    if not issuer_gstin:
        return TaxBreakdown(cgst=None, sgst=None, igst=None, hsn_sac=None)

    taxable = quantize_money(taxable)
    total_tax = quantize_money(taxable * rate)

    if intra_state:
        # Split so the halves always re-add to the total, even for odd paise.
        cgst = quantize_money(total_tax / 2)
        sgst = quantize_money(total_tax - cgst)
        return TaxBreakdown(cgst=cgst, sgst=sgst, igst=None, hsn_sac=sac)

    return TaxBreakdown(cgst=None, sgst=None, igst=total_tax, hsn_sac=sac)


def is_intra_state(issuer_gstin, payer_gstin):
    """Same first two digits means same state, so CGST+SGST rather than IGST.

    With no payer GSTIN (an individual member, the common case) the place of supply
    is the gym's own state, so the supply is intra-state.
    """
    if not issuer_gstin:
        return True
    if not payer_gstin:
        return True
    return issuer_gstin[:2] == payer_gstin[:2]


# ============ ISSUE ============

@transaction.atomic
def issue_invoice(
    *,
    gym,
    payer_user,
    taxable_value,
    membership=None,
    saas_subscription=None,
    currency=None,
    issue_date=None,
    due_date=None,
    payer_gstin=None,
    actor=None,
):
    """Create one Invoice with a reserved number and a computed total.

    Total is taxable value plus the populated tax components only, so an unregistered
    issuer's total equals the taxable value exactly (19.6).
    """
    from core.services.audit import record_create

    if (membership is None) == (saas_subscription is None):
        raise ValidationError(
            {
                "subject": (
                    "An invoice must reference exactly one of membership or "
                    "saas_subscription."
                )
            }
        )

    issue_date = issue_date or gym.today()
    due_date = due_date or issue_date + datetime.timedelta(days=DEFAULT_PAYMENT_TERM_DAYS)
    fy = financial_year_for(issue_date)
    taxable_value = quantize_money(taxable_value)

    tax = compute_tax(
        taxable_value, gym.gstin, is_intra_state(gym.gstin, payer_gstin)
    )
    number, sequence_no = next_invoice_number(gym, fy)

    if not currency:
        if saas_subscription is not None:
            currency = saas_subscription.plan.currency
        elif membership is not None:
            currency = membership.plan.currency
        else:
            currency = "INR"

    invoice = Invoice(
        gym=gym,
        payer_user=payer_user,
        membership=membership,
        saas_subscription=saas_subscription,
        number=number,
        financial_year=fy,
        sequence_no=sequence_no,
        taxable_value=taxable_value,
        cgst=tax.cgst,
        sgst=tax.sgst,
        igst=tax.igst,
        hsn_sac=tax.hsn_sac,
        total_amount=quantize_money(taxable_value + tax.total),
        currency=currency,
        status="open",
        issue_date=issue_date,
        due_date=due_date,
    )
    invoice.save()
    record_create(invoice, actor=actor, gym=gym)
    logger.info(
        "invoice issued number=%s gym_id=%s total=%s %s",
        invoice.number,
        gym.pk,
        invoice.total_amount,
        invoice.currency,
    )
    return invoice


def issue_membership_invoice(membership, *, actor=None, issue_date=None):
    """Invoice for a Gym-to-Member membership period."""
    profile = membership.member
    return issue_invoice(
        gym=profile.gym,
        payer_user=profile.user,
        taxable_value=membership.plan.price,
        membership=membership,
        currency=membership.plan.currency,
        issue_date=issue_date or membership.start_date,
        actor=actor,
    )


def issue_saas_invoice(subscription, *, actor=None, issue_date=None):
    """Invoice for a Platform-to-Gym_Owner subscription period."""
    gym = subscription.gym
    owner_profile = gym.owner_profiles.filter(deleted_at__isnull=True).first()
    if owner_profile is None:
        raise ValidationError({"gym": "This gym has no active owner to bill."})

    return issue_invoice(
        gym=gym,
        payer_user=owner_profile.user,
        taxable_value=subscription.plan.price,
        saas_subscription=subscription,
        currency=subscription.plan.currency,
        issue_date=issue_date or gym.today(),
        actor=actor,
    )


# ============ IMMUTABILITY ============

def assert_amendable(invoice, changing_fields):
    """Refuse a financial-field change on a settled Invoice with 409 (19.7)."""
    if invoice.status != "settled":
        return
    touched = sorted(set(changing_fields) & set(IMMUTABLE_WHEN_SETTLED))
    if touched:
        raise InvoiceImmutable(
            "A settled invoice cannot be amended. Issue a credit note instead. "
            f"Refused change to: {', '.join(touched)}.",
            details={"fields": touched, "field": touched[0], "invoice": invoice.number},
        )


# ============ SETTLEMENT ============

@transaction.atomic
def settle(invoice, payment, *, actor=None, now=None):
    """Mark an Invoice settled from a succeeded Payment. Idempotent.

    Idempotent because the webhook handler may legitimately run this more than once
    for the same event: a second call finds the Invoice already settled and returns
    without touching anything (18.6).
    """
    from core.services.audit import ACTION_SETTLE, AuditedChange
    from core.services.memberships import renew_on_settlement

    now = now or timezone.now()

    if invoice.status == "settled":
        return invoice

    with AuditedChange(
        invoice, actor=actor, gym=invoice.gym, fields=["status"], action=ACTION_SETTLE
    ):
        invoice.status = "settled"
        invoice.save(update_fields=["status"])

    if payment is not None and payment.paid_at is None:
        payment.paid_at = now
        payment.save(update_fields=["paid_at"])

    if invoice.saas_subscription_id is not None:
        from core.services.subscriptions import advance_period

        advance_period(invoice.saas_subscription, actor=actor)
    elif invoice.membership_id is not None:
        membership = invoice.membership
        # Only chain a *renewal*. The first period's dates were set when the
        # membership was created and settling its invoice must not add a second.
        if membership.end_date < invoice.gym.today():
            renew_on_settlement(membership, actor=actor)

    logger.info(
        "invoice settled number=%s payment_ref=%s",
        invoice.number,
        getattr(payment, "gateway_payment_ref", None),
    )
    return invoice


# ============ VOIDING ============

@transaction.atomic
def void_via_credit_note(invoice, reason, *, amount=None, actor=None, issue_date=None):
    """Reverse an invoice by issuing a credit note against it (19.8).

    The invoice row itself keeps its numbers; only its status changes. Editing the
    amounts would break the numbered series and destroy the audit trail.
    """
    from core.services.audit import ACTION_VOID, AuditedChange, record_create

    issue_date = issue_date or invoice.gym.today()
    amount = quantize_money(amount if amount is not None else invoice.total_amount)

    if amount > invoice.total_amount:
        raise ValidationError(
            {
                "amount": (
                    f"A credit note cannot exceed the invoice total of "
                    f"{invoice.total_amount}."
                ),
                "field": "amount",
            }
        )

    number, _ = next_invoice_number(invoice.gym, financial_year_for(issue_date))
    note = CreditNote.objects.create(
        invoice=invoice,
        number=f"CN/{number}",
        amount=amount,
        reason=reason,
        issue_date=issue_date,
    )
    record_create(note, actor=actor, gym=invoice.gym)

    new_status = "void" if amount >= invoice.total_amount else invoice.status
    if new_status != invoice.status:
        with AuditedChange(
            invoice, actor=actor, gym=invoice.gym, fields=["status"], action=ACTION_VOID
        ):
            invoice.status = new_status
            invoice.save(update_fields=["status"])

    return note
