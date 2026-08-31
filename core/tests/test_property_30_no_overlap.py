"""Feature: gym-saas-core, Property 30 (stateful)."""
import datetime

import pytest
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule
from rest_framework.exceptions import ValidationError

from core.models import Membership
from core.services.memberships import (
    create_membership,
    next_start_date,
    periods_overlap,
    renew_on_settlement,
    switch_plan,
)
from core.tests import factories

pytestmark = pytest.mark.django_db(transaction=True)


# Feature: gym-saas-core, Property 30: For any Member and for any sequence of assignments
# and renewal settlements, no two of that Member's Memberships have intersecting date
# periods, an attempt to create an overlapping Membership is rejected with a validation
# error naming the start date field, a renewal settled while the Member holds a Membership
# ending on or after today starts the day after the latest such end date, a renewal
# settled with no such Membership starts on the settlement date in the Gym's timezone, and
# a plan switch during an active Membership leaves that Membership's dates and Invoice
# unchanged with no proration applied.
# Validates: Requirements 20.11, 20.6, 20.7, 20.12, 4.6, 4.7
class MembershipChainMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.gym = None
        self.member = None
        self.plans = []

    @initialize()
    def setup(self):
        self.gym = factories.make_gym()
        self.member = factories.make_member(self.gym)
        self.plans = [
            factories.make_membership_plan(self.gym, price="0.00", duration_days=30),
            factories.make_membership_plan(self.gym, price="0.00", duration_days=7),
            factories.make_membership_plan(self.gym, price="1200.00", duration_days=90),
        ]

    def _periods(self):
        return list(
            Membership.objects.filter(member=self.member)
            .order_by("start_date")
            .values_list("start_date", "end_date")
        )

    @rule(plan_index=st.integers(min_value=0, max_value=2), offset=st.integers(-60, 400))
    def try_create_membership(self, plan_index, offset):
        """Either it does not overlap and succeeds, or it overlaps and is refused."""
        plan = self.plans[plan_index]
        start = self.gym.today() + datetime.timedelta(days=offset)
        end = start + datetime.timedelta(days=plan.duration_days - 1)

        clashes = any(
            periods_overlap(start, end, existing_start, existing_end)
            for existing_start, existing_end in self._periods()
        )
        before = self._periods()

        if clashes:
            with pytest.raises(ValidationError) as caught:
                create_membership(self.member, plan, start=start)
            # The error names the start date field so the caller can fix it.
            assert "start_date" in caught.value.detail
            assert self._periods() == before
        else:
            create_membership(self.member, plan, start=start)
            assert len(self._periods()) == len(before) + 1

    @rule(plan_index=st.integers(min_value=0, max_value=2))
    def settle_a_renewal(self, plan_index):
        """20.6, 20.7: the chain point depends on whether a period is still running."""
        existing = Membership.objects.filter(member=self.member).order_by("-end_date").first()
        if existing is None:
            return

        settled_on = self.gym.today()
        expected_start = next_start_date(self.member, settled_on)

        latest_running = (
            Membership.objects.filter(member=self.member, end_date__gte=settled_on)
            .order_by("-end_date")
            .values_list("end_date", flat=True)
            .first()
        )
        if latest_running is None:
            assert expected_start == settled_on
        else:
            assert expected_start == latest_running + datetime.timedelta(days=1)

        try:
            renewed = renew_on_settlement(existing, settled_on=settled_on)
        except ValidationError as exc:
            # A future-dated membership already occupies the chain slot.
            assert "start_date" in exc.detail
            return
        assert renewed.start_date == expected_start

    @rule(plan_index=st.integers(min_value=0, max_value=2))
    def switch_plan_without_proration(self, plan_index):
        """20.12, 4.6, 4.7: the paid period is honoured in full."""
        from core.services.memberships import active_membership

        current = active_membership(self.member)
        if current is None:
            return

        before_dates = (current.start_date, current.end_date)
        before_invoices = list(current.invoices.values_list("pk", "total_amount", "status"))

        try:
            switch_plan(self.member, self.plans[plan_index])
        except ValidationError:
            return

        current.refresh_from_db()
        # The existing membership is untouched: no shortening, no proration.
        assert (current.start_date, current.end_date) == before_dates
        assert list(current.invoices.values_list("pk", "total_amount", "status")) == (
            before_invoices
        )

    @invariant()
    def no_two_periods_intersect(self):
        periods = self._periods()
        for index, (start, end) in enumerate(periods):
            for other_start, other_end in periods[index + 1 :]:
                assert not periods_overlap(start, end, other_start, other_end), (
                    f"{start}..{end} overlaps {other_start}..{other_end}"
                )

    @invariant()
    def every_period_is_well_ordered(self):
        for start, end in self._periods():
            assert end >= start


TestMembershipChain = MembershipChainMachine.TestCase
TestMembershipChain.settings = hyp_settings(
    max_examples=100, stateful_step_count=12, deadline=None
)
