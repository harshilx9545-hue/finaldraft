"""Feature: gym-saas-core, Property 36.

Four clauses, four shapes of test:

* The trial length and the period advance are arithmetic over the *stored* period
  end, so they are checked against a recomputed expectation rather than a literal.
* `past_due` is derived, not written by a scheduler, so it is checked by moving the
  evaluation date rather than by running anything.
* The invoice lead window depends on "today", and the issuing service reads the
  gym's own today rather than an argument, so those tests move the clock with
  `freezegun` instead of passing a date in. Passing a date the gym does not agree
  with would test a call pattern production never makes.

Gyms here are pinned to UTC so a frozen instant maps to one unambiguous date. The
timezone-sensitivity of date arithmetic is Property 28's subject, not this one's.
"""
import calendar
import datetime

import pytest
from django.test import override_settings
from freezegun import freeze_time
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Invoice, SaasSubscription
from core.services.invoicing import issue_saas_invoice, settle
from core.services.subscriptions import (
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_PAST_DUE,
    STATUS_TRIALING,
    add_months,
    advance_period,
    cancel,
    effective_status,
    ensure_period_invoice,
    invoice_due_date,
    should_issue_invoice,
    start_trial,
)
from core.tests import factories
from core.tests.strategies import dates

pytestmark = pytest.mark.django_db

#: Billing intervals the design permits: whole months, at least one (4.1).
BILLING_INTERVALS = st.one_of(
    st.sampled_from([1, 2, 3, 6, 12, 24]),  # monthly, quarterly, half-yearly, yearly
    st.integers(min_value=1, max_value=36),
)

TRIAL_LENGTHS = st.one_of(
    st.sampled_from([1, 7, 14, 30, 90, 365]),
    st.integers(min_value=1, max_value=730),
)

LEAD_TIMES = st.one_of(
    st.sampled_from([0, 1, 3, 7, 14, 30]),
    st.integers(min_value=0, max_value=60),
)


def utc_gym(**kwargs):
    kwargs.setdefault("timezone_name", "UTC")
    kwargs.setdefault("with_subscription", False)
    return factories.make_gym(**kwargs)


def subscription_for(gym, *, interval_months=1, status=STATUS_TRIALING, start=None, period_end):
    plan = factories.make_saas_plan(billing_interval_months=interval_months)
    return factories.make_subscription(
        gym,
        plan,
        status=status,
        start=start or (period_end - datetime.timedelta(days=30)),
        period_end=period_end,
    )


# Feature: gym-saas-core, Property 36: For any configured trial length, a newly created
# Gym has a SaasSubscription in status trialing whose period end is the creation date
# plus that length; for any billing interval and prior period end, settling a SaaS
# Invoice sets the status to active and advances the stored period end by that interval;
# for any instant after a period end with no settled next-period Invoice, the status
# becomes past_due; and for any configured lead time, a SaaS Invoice exists exactly when
# the current date has reached the period end minus that lead time.
# Validates: Requirements 21.3, 21.4, 21.6, 21.7
@settings(max_examples=100)
@given(trial_length=TRIAL_LENGTHS, start=dates())
def test_a_new_gym_gets_a_trialing_period_of_the_configured_length(trial_length, start):
    """21.3: the trial ends the configured number of days after it begins."""
    gym = utc_gym()
    factories.make_saas_plan(price="499.00")

    with override_settings(SAAS_TRIAL_DAYS=trial_length):
        subscription = start_trial(gym, start=start)

    assert subscription is not None
    assert subscription.status == STATUS_TRIALING
    assert subscription.start_date == start
    assert subscription.current_period_end == start + datetime.timedelta(days=trial_length)


def test_owner_registration_creates_the_trialing_subscription():
    """21.3 end to end: the tenant exists on a trial from the moment it is created."""
    factories.make_saas_plan(price="499.00", max_members_allowed=50)

    from core.services.registration import register_owner

    with override_settings(SAAS_TRIAL_DAYS=14):
        result = register_owner(
            email=factories.unique_email("owner"),
            password=factories.DEFAULT_PASSWORD,
            business_name="Period Arithmetic Gym",
            contact_phone=factories.unique_phone(),
            timezone_name="UTC",
            send_verification=False,
        )

    gym = result["gym"]
    subscription = SaasSubscription.objects.get(gym=gym)
    assert subscription.status == STATUS_TRIALING
    assert subscription.current_period_end == gym.today() + datetime.timedelta(days=14)


@settings(max_examples=100)
@given(interval_months=BILLING_INTERVALS, period_end=dates())
def test_settlement_activates_and_advances_by_the_billing_interval(
    interval_months, period_end
):
    """21.4/21.6: the anniversary advances from the stored end, not from today."""
    gym = utc_gym()
    owner = factories.make_owner(gym)
    subscription = subscription_for(
        gym, interval_months=interval_months, period_end=period_end
    )

    invoice = issue_saas_invoice(subscription, actor=owner.user)
    settle(invoice, None, actor=owner.user)

    subscription.refresh_from_db()
    assert subscription.status == STATUS_ACTIVE
    assert subscription.current_period_end == add_months(period_end, interval_months)


@settings(max_examples=100)
@given(interval_months=BILLING_INTERVALS, cycles=st.integers(min_value=1, max_value=4))
def test_repeated_settlement_keeps_the_billing_anniversary_stable(interval_months, cycles):
    """Advancing from the stored end means a late payment does not shift the cycle."""
    gym = utc_gym()
    factories.make_owner(gym)
    origin = datetime.date(2025, 1, 31)  # a day most months cannot hold
    subscription = subscription_for(
        gym, interval_months=interval_months, period_end=origin
    )

    expected = origin
    for _ in range(cycles):
        advance_period(subscription)
        expected = add_months(expected, interval_months)

    subscription.refresh_from_db()
    assert subscription.current_period_end == expected


@settings(max_examples=100)
@given(day=dates(), months=st.integers(min_value=0, max_value=48))
def test_add_months_clamps_to_the_end_of_the_target_month(day, months):
    """Billing on the 31st must land on the last day of a short month, not skip it."""
    result = add_months(day, months)

    zero_based = day.month - 1 + months
    assert result.year == day.year + zero_based // 12
    assert result.month == zero_based % 12 + 1
    last_day_of_target = calendar.monthrange(result.year, result.month)[1]
    assert result.day == min(day.day, last_day_of_target)
    assert result >= day


def test_add_months_leap_year_boundaries():
    """The cases that break naive date maths, pinned as examples."""
    assert add_months(datetime.date(2024, 1, 31), 1) == datetime.date(2024, 2, 29)
    assert add_months(datetime.date(2023, 1, 31), 1) == datetime.date(2023, 2, 28)
    assert add_months(datetime.date(2024, 2, 29), 12) == datetime.date(2025, 2, 28)
    assert add_months(datetime.date(2024, 2, 29), 48) == datetime.date(2028, 2, 29)
    assert add_months(datetime.date(2025, 3, 31), 1) == datetime.date(2025, 4, 30)
    assert add_months(datetime.date(2025, 12, 31), 1) == datetime.date(2026, 1, 31)
    assert add_months(datetime.date(2025, 12, 15), 12) == datetime.date(2026, 12, 15)


@settings(max_examples=100)
@given(
    period_end=dates(),
    offset_days=st.integers(min_value=-30, max_value=30),
    stored_status=st.sampled_from([STATUS_TRIALING, STATUS_ACTIVE, STATUS_PAST_DUE]),
)
def test_status_is_past_due_exactly_after_the_period_end_when_unpaid(
    period_end, offset_days, stored_status
):
    """21.6: derived, so it becomes true as the date rolls over with nothing running."""
    gym = utc_gym()
    subscription = subscription_for(gym, period_end=period_end, status=stored_status)

    evaluated_on = period_end + datetime.timedelta(days=offset_days)
    derived = effective_status(subscription, evaluated_on)

    if evaluated_on > period_end:
        assert derived == STATUS_PAST_DUE
    else:
        assert derived == stored_status


@settings(max_examples=100)
@given(period_end=dates(), offset_days=st.integers(min_value=1, max_value=60))
def test_a_settled_next_period_invoice_prevents_past_due(period_end, offset_days):
    """A gym that has already paid for the next period is not in arrears."""
    gym = utc_gym()
    owner = factories.make_owner(gym)
    subscription = subscription_for(gym, period_end=period_end, status=STATUS_ACTIVE)

    # Issued after the current period end, so it covers the following period.
    invoice = issue_saas_invoice(
        subscription,
        actor=owner.user,
        issue_date=period_end + datetime.timedelta(days=1),
    )
    invoice.status = "settled"
    invoice.save(update_fields=["status"])

    evaluated_on = period_end + datetime.timedelta(days=offset_days)
    assert effective_status(subscription, evaluated_on) == STATUS_ACTIVE


@settings(max_examples=100)
@given(period_end=dates(), offset_days=st.integers(min_value=-30, max_value=60))
def test_a_cancelled_subscription_stays_cancelled(period_end, offset_days):
    """21.2: cancellation is terminal; it never decays into past_due."""
    gym = utc_gym()
    subscription = subscription_for(gym, period_end=period_end, status=STATUS_ACTIVE)
    cancel(subscription)

    evaluated_on = period_end + datetime.timedelta(days=offset_days)
    assert effective_status(subscription, evaluated_on) == STATUS_CANCELLED
    # A cancelled subscription is never billed for another period either (21.7).
    assert should_issue_invoice(subscription, evaluated_on) is False


@settings(max_examples=100)
@given(lead_days=LEAD_TIMES, offset_days=st.integers(min_value=-3, max_value=3))
def test_the_saas_invoice_appears_exactly_when_the_lead_window_opens(
    lead_days, offset_days
):
    """21.7: issued when today reaches period end minus the configured lead time."""
    period_end = datetime.date(2025, 7, 15)
    frozen_day = period_end - datetime.timedelta(days=lead_days) + datetime.timedelta(
        days=offset_days
    )

    with freeze_time(datetime.datetime.combine(frozen_day, datetime.time(12, 0))):
        gym = utc_gym()
        owner = factories.make_owner(gym)
        subscription = subscription_for(
            gym, period_end=period_end, status=STATUS_ACTIVE
        )

        with override_settings(SAAS_INVOICE_LEAD_DAYS=lead_days):
            assert invoice_due_date(subscription) == period_end - datetime.timedelta(
                days=lead_days
            )
            window_open = gym.today() >= invoice_due_date(subscription)

            assert should_issue_invoice(subscription) is window_open

            issued = ensure_period_invoice(subscription, actor=owner.user)
            if window_open:
                assert issued is not None
                assert issued.saas_subscription_id == subscription.pk
                assert issued.total_amount == subscription.plan.price
            else:
                assert issued is None

            # Whether or not one was issued, a second call must not add another.
            assert ensure_period_invoice(subscription, actor=owner.user) is None
            assert (
                Invoice.objects.filter(saas_subscription=subscription).count()
                == (1 if window_open else 0)
            )


def test_settlement_through_the_webhook_advances_the_period():
    """The same advance, driven end to end by a verified gateway event."""
    from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
    from core.services.payments import create_order, process_event
    from core.tests.fakes import build_event_payload

    period_end = datetime.date(2025, 7, 15)
    gym = utc_gym()
    owner = factories.make_owner(gym)
    subscription = subscription_for(gym, interval_months=3, period_end=period_end)

    invoice = issue_saas_invoice(subscription, actor=owner.user)
    order = create_order(invoice, actor=owner.user)["order"]

    adapter = get_adapter()
    payload = build_event_payload(
        event_id="evt_p36_webhook",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=order.order_ref,
        payment_ref="pay_p36_webhook",
    )
    process_event(adapter.parse_event(payload), payload)

    subscription.refresh_from_db()
    invoice.refresh_from_db()
    assert invoice.status == "settled"
    assert subscription.status == STATUS_ACTIVE
    assert subscription.current_period_end == add_months(period_end, 3)
