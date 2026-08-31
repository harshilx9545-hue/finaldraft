"""Feature: ai-revenue-recovery, Property 43.

The stopping rule is what keeps automated collection from becoming harassment, so the
test drives the batch far past the limit - up to ten rounds against the same invoice -
with a planner that always wants to make contact. The rule has to hold against a planner
that never voluntarily stops.

What counts as an attempt is the substantive question. Only outcomes that actually reach
the member are counted: a reminder and a discount-with-link. A guardrail refusal, an
escalation, and a stop record are all *not* contact, and counting them would let a
misbehaving planner exhaust a member's attempt budget with requests that were refused -
silencing reminders that were never sent.

Tier 4 is checked separately because it is a different mechanism reaching the same
conclusion: at 22 days or more the ladder is over, so contact never happens even on the
first round and the invoice is handed to a human immediately.
"""
from __future__ import annotations

import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import RecoveryAttempt
from core.services.recovery_agent import (
    CONTACT_OUTCOMES,
    MAX_AUTOMATED_ATTEMPTS,
    TERMINAL_OUTCOMES,
    TOOL_SEND_REMINDER,
    AIRevenueRecoveryAgent,
    Outcome,
    RecoveryStopped,
    tier_for,
)
from core.tests import factories
from core.tests.fakes import ScriptedRecoveryPlanner, UnavailableRecoveryPlanner

pytestmark = pytest.mark.django_db

#: Ages inside the three tiers that are allowed to make contact at all.
CONTACTABLE_DAYS = (1, 3, 7, 8, 12, 14, 15, 19, 21)

#: Ages at or past the terminal tier.
TERMINAL_DAYS = (22, 30, 60, 365)


def overdue_invoice(gym, member, *, days_overdue, taxable="1500.00"):
    issue_date = gym.today() - datetime.timedelta(days=days_overdue + 7)
    membership = factories.make_membership(member, start=issue_date)
    return factories.make_invoice(
        gym, member.user, taxable=taxable, membership=membership, issue_date=issue_date
    )


def contact_rows(invoice):
    return RecoveryAttempt.objects.filter(
        invoice=invoice, outcome__in=sorted(CONTACT_OUTCOMES)
    )


def eager_planner():
    """A planner that always wants to send a reminder, whatever has already happened."""
    return ScriptedRecoveryPlanner(
        tool=TOOL_SEND_REMINDER,
        arguments=lambda context: {
            "gym_id": context["gym_id"],
            "member_id": context["member_id"],
            "tone": "firm",
        },
        reasoning="I would like to contact this member again.",
    )


def run_rounds(gym, rounds, *, planner_factory=eager_planner, synthetic=False):
    reports = []
    for _ in range(rounds):
        agent = AIRevenueRecoveryAgent(
            tenant_id=gym.pk, llm_client=planner_factory()
        )
        reports.append(agent.run_recovery_batch(gym.pk, synthetic=synthetic))
    return reports


# Feature: ai-revenue-recovery, Property 43: For any number of recovery batches run
# against the same invoice, and for any overdue age, the number of automated contacts
# recorded against that invoice never exceeds MAX_AUTOMATED_ATTEMPTS, and once the limit
# is reached every further round records a stop rather than a contact.
# Validates: stopping rule holds independently of the planner's wishes
@settings(max_examples=100, deadline=None)
@given(
    rounds=st.integers(min_value=1, max_value=10),
    days_overdue=st.sampled_from(CONTACTABLE_DAYS),
)
def test_automated_contacts_never_exceed_the_limit(rounds, days_overdue):
    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=days_overdue)

    run_rounds(tenant["gym"], rounds)

    contacts = contact_rows(invoice).count()
    assert contacts <= MAX_AUTOMATED_ATTEMPTS, (
        f"{rounds} rounds produced {contacts} automated contacts on one invoice, "
        f"over the limit of {MAX_AUTOMATED_ATTEMPTS}"
    )
    # And the limit is actually reached rather than accidentally never approached.
    assert contacts == min(rounds, MAX_AUTOMATED_ATTEMPTS)

    if rounds > MAX_AUTOMATED_ATTEMPTS:
        stops = RecoveryAttempt.objects.filter(
            invoice=invoice, outcome=Outcome.STOPPED_ATTEMPT_LIMIT
        ).count()
        assert stops == rounds - MAX_AUTOMATED_ATTEMPTS, (
            "every round past the limit must record a stop"
        )

    # One row per round, always: the ledger accounts for every decision.
    assert RecoveryAttempt.objects.filter(invoice=invoice).count() == rounds


# Feature: ai-revenue-recovery, Property 43 (second clause): at the terminal tier the
# agent never contacts the member at all, on any round, and hands the invoice to a human
# on the first one.
# Validates: tier 4 stops automated recovery outright
@settings(max_examples=100, deadline=None)
@given(
    rounds=st.integers(min_value=1, max_value=6),
    days_overdue=st.sampled_from(TERMINAL_DAYS),
)
def test_the_terminal_tier_never_contacts_the_member(rounds, days_overdue):
    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=days_overdue)
    assert tier_for(days_overdue).is_terminal

    run_rounds(tenant["gym"], rounds)

    assert contact_rows(invoice).count() == 0, (
        "a terminal-tier invoice was contacted despite the planner being overruled"
    )
    rows = list(RecoveryAttempt.objects.filter(invoice=invoice).order_by("pk"))
    assert rows[0].outcome == Outcome.ESCALATED_TO_HUMAN
    # Every later round sees the invoice is human-owned and leaves it alone.
    for row in rows[1:]:
        assert row.outcome == Outcome.STOPPED_HUMAN_OWNED, row.outcome
    assert all(row.outcome in TERMINAL_OUTCOMES for row in rows)


# Feature: ai-revenue-recovery, Property 43 (third clause): a refusal never consumes an
# attempt, so a planner whose requests are all rejected cannot exhaust a member's
# contact budget and suppress the reminders they should have received.
# Validates: only real contact counts against the stopping rule
@settings(max_examples=100, deadline=None)
@given(
    refused_rounds=st.integers(min_value=1, max_value=5),
    days_overdue=st.sampled_from(CONTACTABLE_DAYS),
)
def test_refusals_do_not_consume_attempts(refused_rounds, days_overdue):
    tenant = factories.make_tenant()
    other = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=days_overdue)

    # Every round is refused at the tenant boundary, so nothing reaches the member.
    for _ in range(refused_rounds):
        agent = AIRevenueRecoveryAgent(
            tenant_id=tenant["gym"].pk,
            llm_client=ScriptedRecoveryPlanner(
                tool=TOOL_SEND_REMINDER,
                arguments={
                    "gym_id": other["gym"].pk,
                    "member_id": other["member"].pk,
                    "tone": "firm",
                },
            ),
        )
        agent.run_recovery_batch(tenant["gym"].pk, synthetic=False)

    assert contact_rows(invoice).count() == 0
    assert (
        RecoveryAttempt.objects.filter(
            invoice=invoice, outcome=Outcome.BLOCKED_TENANT_BOUNDARY
        ).count()
        == refused_rounds
    )

    # The member's full allowance is still intact afterwards.
    run_rounds(tenant["gym"], MAX_AUTOMATED_ATTEMPTS)
    assert contact_rows(invoice).count() == MAX_AUTOMATED_ATTEMPTS


# ==== CLAUSES THE GENERATORS DELIBERATELY DO NOT PRODUCE ====

def test_the_tools_enforce_the_stopping_rule_for_a_direct_caller():
    """The rule lives in the tools too, not only in the batch loop.

    Same reasoning as the discount guard: the batch loop protects the batch, and a caller
    reaching a tool directly has to be refused by the tool.
    """
    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=10)
    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)
    member_id = tenant["member"].pk

    run_rounds(tenant["gym"], MAX_AUTOMATED_ATTEMPTS)
    assert contact_rows(invoice).count() == MAX_AUTOMATED_ATTEMPTS

    with pytest.raises(RecoveryStopped):
        agent.send_payment_reminder(
            gym_id=tenant["gym"].pk, member_id=member_id, tone="firm"
        )
    assert contact_rows(invoice).count() == MAX_AUTOMATED_ATTEMPTS


def test_escalation_is_not_refused_once_the_limit_is_spent():
    """Escalation is what the stopping rule escalates *to*.

    Gating it behind the attempt budget would strand an invoice inside an automated
    process that has already given up on it, which is the opposite of a compliant
    handoff.
    """
    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=10)
    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)

    run_rounds(tenant["gym"], MAX_AUTOMATED_ATTEMPTS)

    result = agent.escalate_to_human(
        gym_id=tenant["gym"].pk,
        member_id=tenant["member"].pk,
        reason="attempt budget spent",
    )
    assert result["handed_to_human"] is True


def test_a_settled_invoice_is_left_alone():
    """Money arriving stops recovery, whatever tier the invoice was in.

    The invoice is settled through the real settlement service rather than by waiting for
    the synthetic simulation to happen to settle it, so the test asserts the property
    instead of depending on a coin flip.
    """
    from core.services.invoicing import settle

    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=10)
    settle(invoice, factories.make_payment(invoice, status="succeeded"))
    invoice.refresh_from_db()
    assert invoice.status == "settled"

    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk)
    report = agent.run_recovery_batch(tenant["gym"].pk, synthetic=True)

    # It is not even a candidate: the batch selects open, overdue invoices.
    assert report.processed == 0
    assert not RecoveryAttempt.objects.filter(invoice=invoice).exists()


def test_the_measured_recovery_figure_is_summed_from_the_ledger():
    """Every figure in the report has to be reconcilable against the ledger.

    This is the measurement claim the batch exists to support, so it is asserted
    directly: recovered money equals the sum of the `payment_observed` rows, every
    processed invoice lands in exactly one bucket, and the three buckets' amounts add up
    to what was outstanding when the batch started.
    """
    from decimal import Decimal

    tenant = factories.make_tenant()
    for index, days in enumerate((3, 9, 16, 25, 5, 12, 19, 30)):
        member = factories.make_member(tenant["gym"], plan=tenant["plan"])
        overdue_invoice(
            tenant["gym"], member, days_overdue=days, taxable=f"{1000 + index * 250}.00"
        )

    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk, seed=7)
    report = agent.run_recovery_batch(tenant["gym"].pk, synthetic=True)

    assert report.processed == 8
    assert report.accounted_for == report.processed

    observed = RecoveryAttempt.objects.filter(
        gym=tenant["gym"], outcome=Outcome.PAYMENT_OBSERVED
    )
    assert report.recovered_count == observed.count()
    assert report.recovered_amount == sum(
        (row.amount_recovered for row in observed), Decimal("0.00")
    )

    # Nothing is double-counted and nothing is lost. The discount term is required:
    # a discounted invoice contributes its reduced amount to its bucket, so the money
    # given up has to be accounted for separately or the totals appear to lose it.
    assert report.discounts_applied > 0, "the tier-3 invoices should have been discounted"
    assert report.reconciles, (
        f"recovered {report.recovered_amount} + pending {report.pending_amount} + "
        f"stopped {report.stopped_amount} + discounts {report.discount_amount_total} "
        f"= {report.closing_balance}, expected {report.outstanding_before}"
    )


def test_a_planner_outage_does_not_stop_the_batch():
    """A hosted model being down must not become a reason to skip collection."""
    tenant = factories.make_tenant()
    invoice = overdue_invoice(tenant["gym"], tenant["member"], days_overdue=3)

    planner = UnavailableRecoveryPlanner()
    agent = AIRevenueRecoveryAgent(tenant_id=tenant["gym"].pk, llm_client=planner)
    report = agent.run_recovery_batch(tenant["gym"].pk, synthetic=False)

    assert planner.calls == 1
    assert report.processed == 1
    assert report.planner_fallbacks == 1
    attempt = RecoveryAttempt.objects.get(invoice=invoice)
    assert attempt.outcome == Outcome.REMINDER_SENT
    # The outage is visible in the trail rather than silently papered over.
    assert "planner unavailable" in attempt.llm_reasoning_text


def test_the_attempt_limit_constant_is_three():
    """The number itself, so loosening the policy fails a test."""
    assert MAX_AUTOMATED_ATTEMPTS == 3
