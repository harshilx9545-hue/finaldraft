"""Feature: ai-revenue-recovery, Property 41.

The discount cap is the guardrail with money directly behind it, so it is tested
against an adversarial planner rather than a cooperative one: every example here has
the model asking for something it must not get.

Two distinct claims are checked, and the difference between them is the whole design:

* The **orchestration layer clamps**. Whatever the planner proposes, the discount that
  reaches the tool is at most the cap, so one hallucinated number does not cost the gym
  a collection attempt. The ledger records what the planner asked for alongside what
  was applied.
* The **tool refuses independently**. Called directly with an over-cap value - which is
  what a successful prompt injection or a compromised caller looks like - it raises and
  changes nothing. This is the check that must hold even if the clamp is removed, so it
  is exercised without going through `dispatch` at all.

The generators deliberately include values a naive range check mishandles: NaN and the
infinities, which compare false against both bounds; strings and None, which a model
emitting loose JSON really does produce; and values just either side of 20.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.models import RecoveryAttempt
from core.services.recovery_agent import (
    MAX_DISCOUNT_PERCENTAGE,
    AIRevenueRecoveryAgent,
    DiscountCapExceeded,
    DuplicateDiscountRefused,
    Outcome,
    TOOL_APPLY_DISCOUNT,
)

from core.tests import factories
from core.tests.fakes import ScriptedRecoveryPlanner

pytestmark = pytest.mark.django_db

#: Overdue ages inside tier 3, the only tier at which a discount is permitted.
TIER_3_DAYS = (15, 16, 19, 21)

#: Percentages that must all be refused or clamped. Mixes the plausible (25, 100) with
#: the pathological (NaN, inf, "fifty percent", None).
ILLEGAL_DISCOUNTS = st.one_of(
    st.floats(min_value=20.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=21, max_value=10_000),
    st.sampled_from(
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            "50",
            "fifty percent",
            None,
            -5,
            0,
            "20.0001",
            10**9,
        ]
    ),
)


def overdue_invoice(gym, member, *, days_overdue, taxable="1500.00"):
    """One open invoice, `days_overdue` days past its due date.

    The seven-day offset mirrors `DEFAULT_PAYMENT_TERM_DAYS`, which is what
    `issue_invoice` applies when it derives a due date, so the invoice reaches the
    intended tier without the test hard-coding a due date the service would not produce.
    """
    issue_date = gym.today() - datetime.timedelta(days=days_overdue + 7)
    membership = factories.make_membership(member, start=issue_date)
    return factories.make_invoice(
        gym,
        member.user,
        taxable=taxable,
        membership=membership,
        issue_date=issue_date,
    )


def tier_3_setup(*, days_overdue=16, taxable="1500.00", gstin=None):
    tenant = factories.make_tenant(gstin=gstin)
    invoice = overdue_invoice(
        tenant["gym"], tenant["member"], days_overdue=days_overdue, taxable=taxable
    )
    return tenant, invoice


# Feature: ai-revenue-recovery, Property 41: For any discount percentage a language
# model proposes - including values above the cap, non-finite values, and values that
# are not numbers at all - the discount actually applied to an invoice never exceeds
# MAX_DISCOUNT_PERCENTAGE of its taxable value, no RecoveryAttempt ever records an
# applied discount above the cap, and the invoice's taxable value never falls below
# (100 - cap)% of what it was.
# Validates: hard cap enforced in code, independent of LLM output
@settings(max_examples=100)
@given(
    proposed=ILLEGAL_DISCOUNTS,
    days_overdue=st.sampled_from(TIER_3_DAYS),
    taxable=st.sampled_from(["1500.00", "999.99", "0.01", "87654.32"]),
)
def test_no_proposed_discount_ever_exceeds_the_cap(proposed, days_overdue, taxable):
    tenant, invoice = tier_3_setup(days_overdue=days_overdue, taxable=taxable)
    original_taxable = invoice.taxable_value

    agent = AIRevenueRecoveryAgent(
        tenant_id=tenant["gym"].pk,
        llm_client=ScriptedRecoveryPlanner(
            argument_overrides={"discount_percentage": proposed}
        ),
    )
    attempt = agent.process_invoice(invoice)
    invoice.refresh_from_db()

    # Whatever happened, the taxable value cannot have fallen further than the cap.
    largest_legal_reduction = (
        original_taxable * MAX_DISCOUNT_PERCENTAGE / Decimal("100")
    ).quantize(Decimal("0.01")) + Decimal("0.01")
    assert original_taxable - invoice.taxable_value <= largest_legal_reduction, (
        f"proposed {proposed!r} reduced taxable from {original_taxable} to "
        f"{invoice.taxable_value}, more than the {MAX_DISCOUNT_PERCENTAGE}% cap allows"
    )
    assert invoice.taxable_value >= Decimal("0.00")

    # And no ledger row anywhere claims an applied discount above the cap.
    for row in RecoveryAttempt.objects.filter(invoice=invoice):
        applied = (row.arguments_passed or {}).get("discount_percentage")
        if applied is None:
            continue
        assert Decimal(str(applied)) <= MAX_DISCOUNT_PERCENTAGE, (
            f"ledger row {row.pk} records an applied discount of {applied}, above the "
            f"{MAX_DISCOUNT_PERCENTAGE}% cap"
        )

    # The attempt is recorded either way: a clamped success or a refusal, never silence.
    assert attempt.outcome in {
        Outcome.DISCOUNT_APPLIED,
        Outcome.BLOCKED_DISCOUNT_CAP,
        Outcome.BLOCKED_INVALID_ARGUMENTS,
        Outcome.GATEWAY_UNAVAILABLE,
    }, attempt.outcome
    if attempt.outcome == Outcome.DISCOUNT_APPLIED:
        # The provenance of the clamp is in the trail, not just the result.
        assert attempt.arguments_passed.get("clamped_by_guardrail") is True
        assert Decimal(attempt.arguments_passed["discount_percentage"]) == (
            MAX_DISCOUNT_PERCENTAGE
        )


# Feature: ai-revenue-recovery, Property 41 (second clause): the tool itself refuses an
# over-cap discount when called directly, without the orchestration layer's clamp, and
# leaves the invoice completely unchanged.
# Validates: cap is enforced in the tool, not only in the caller
@settings(max_examples=100)
@given(
    proposed=st.one_of(
        st.floats(
            min_value=20.01, max_value=10_000.0, allow_nan=False, allow_infinity=False
        ),
        st.integers(min_value=21, max_value=10_000),
        st.decimals(
            min_value=Decimal("20.01"),
            max_value=Decimal("9999.99"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        ),
    ),
    days_overdue=st.sampled_from(TIER_3_DAYS),
)
def test_the_tool_refuses_an_over_cap_discount_and_changes_nothing(
    proposed, days_overdue
):
    assume(Decimal(str(proposed)) > MAX_DISCOUNT_PERCENTAGE)
    tenant, invoice = tier_3_setup(days_overdue=days_overdue)
    before = (
        invoice.taxable_value,
        invoice.total_amount,
        invoice.cgst,
        invoice.sgst,
        invoice.igst,
        invoice.status,
    )
    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)
    member_id = invoice.membership.member.pk

    with pytest.raises(DiscountCapExceeded):
        agent.apply_recovery_discount_and_get_link(
            gym_id=tenant["gym"].pk,
            member_id=member_id,
            discount_percentage=proposed,
        )

    invoice.refresh_from_db()
    assert (
        invoice.taxable_value,
        invoice.total_amount,
        invoice.cgst,
        invoice.sgst,
        invoice.igst,
        invoice.status,
    ) == before, f"a refused {proposed} discount still altered the invoice"
    # A refusal reaching the tool directly writes no Payment either.
    assert not invoice.payments.exists()


# ==== CLAUSES THE GENERATORS DELIBERATELY DO NOT PRODUCE ====

def test_a_legal_discount_is_applied_and_recomputes_gst():
    """The happy path, with a GSTIN, so the tax recomputation is exercised.

    Asserted here rather than generated because the interesting part is an exact
    arithmetic identity - total equals taxable plus the populated components - and one
    concrete case pins it more clearly than a hundred random ones.
    """
    tenant, invoice = tier_3_setup(taxable="1000.00", gstin="27AAAPA1234A1Z5")
    original_total = invoice.total_amount
    assert invoice.cgst is not None and invoice.sgst is not None

    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)
    result = agent.apply_recovery_discount_and_get_link(
        gym_id=tenant["gym"].pk,
        member_id=invoice.membership.member.pk,
        discount_percentage=Decimal("10"),
    )
    invoice.refresh_from_db()

    assert invoice.taxable_value == Decimal("900.00")
    # Property 19's invariant still holds on a discounted invoice.
    assert invoice.total_amount == invoice.taxable_value + invoice.tax_total
    assert invoice.cgst + invoice.sgst == invoice.tax_total
    assert invoice.total_amount < original_total
    assert result["payment_link"].endswith(result["order_ref"])
    assert Decimal(result["amount_due"]) == invoice.total_amount


def test_a_second_discount_on_the_same_invoice_is_refused():
    """One discount per invoice, however persuasive the second request is."""
    tenant, invoice = tier_3_setup()
    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)
    member_id = invoice.membership.member.pk

    agent.apply_recovery_discount_and_get_link(
        gym_id=tenant["gym"].pk, member_id=member_id, discount_percentage=Decimal("5")
    )
    invoice.refresh_from_db()
    after_first = invoice.taxable_value

    with pytest.raises(DuplicateDiscountRefused):
        agent.apply_recovery_discount_and_get_link(
            gym_id=tenant["gym"].pk,
            member_id=member_id,
            discount_percentage=Decimal("5"),
        )

    invoice.refresh_from_db()
    assert invoice.taxable_value == after_first


def test_repeated_batches_never_grant_a_second_discount():
    """The duplicate guard survives the orchestration layer, not just direct calls.

    A planner that asks for a discount on every round is exactly the failure mode the
    ledger-counted guard exists for, so this drives four rounds and asserts the count
    of granted discounts is one.
    """
    tenant, invoice = tier_3_setup()
    for _ in range(4):
        agent = AIRevenueRecoveryAgent(
            tenant_id=tenant["gym"].pk,
            llm_client=ScriptedRecoveryPlanner(
                tool=TOOL_APPLY_DISCOUNT,
                arguments=lambda context: {
                    "gym_id": context["gym_id"],
                    "member_id": context["member_id"],
                    "discount_percentage": 20,
                },
            ),
        )
        agent.run_recovery_batch(tenant["gym"].pk, synthetic=False)

    granted = RecoveryAttempt.objects.filter(
        invoice=invoice, outcome=Outcome.DISCOUNT_APPLIED
    ).count()
    assert granted == 1, f"{granted} discounts were granted on one invoice"
    assert RecoveryAttempt.objects.filter(
        invoice=invoice, outcome=Outcome.BLOCKED_DUPLICATE_DISCOUNT
    ).exists(), "the refusals were not recorded"


def test_a_discount_is_refused_outside_tier_3():
    """Tier policy downgrades a discount request to a reminder at tiers 1 and 2."""
    tenant, invoice = tier_3_setup(days_overdue=3)  # tier 1
    agent = AIRevenueRecoveryAgent(
        tenant_id=tenant["gym"].pk,
        llm_client=ScriptedRecoveryPlanner(
            tool=TOOL_APPLY_DISCOUNT,
            arguments=lambda context: {
                "gym_id": context["gym_id"],
                "member_id": context["member_id"],
                "discount_percentage": 20,
            },
        ),
    )
    attempt = agent.process_invoice(invoice)
    invoice.refresh_from_db()

    assert attempt.outcome == Outcome.REMINDER_SENT
    assert attempt.arguments_passed["overridden_planner_tool"] == TOOL_APPLY_DISCOUNT
    assert invoice.taxable_value == Decimal("1500.00"), "a tier-1 invoice was discounted"


def test_the_cap_constant_is_twenty_percent():
    """The number itself, so a silent change to the policy fails a test."""
    assert MAX_DISCOUNT_PERCENTAGE == Decimal("20")
