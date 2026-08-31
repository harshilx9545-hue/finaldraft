"""Feature: gym-saas-core, Property 31 (stateful)."""
import pytest
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from core.exceptions import PlanDowngradeBlocked, SeatLimitReached
from core.models import MemberProfile
from core.services.seats import (
    change_saas_plan,
    restore_member,
    seat_count,
    seat_limit,
    soft_delete_member,
)
from core.tests import factories

pytestmark = pytest.mark.django_db(transaction=True)


# Feature: gym-saas-core, Property 31: For any sequence of MemberProfile create,
# soft-delete, restore, and SaasPlan-change operations against a Gym, the Gym's Seat_Count
# is less than or equal to the non-null max_members_allowed of that Gym's current SaasPlan
# after every operation, and is unbounded when that value is null.
# Validates: Requirements 5.4, 5.3
class SeatMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.gym = None
        self.plans = []

    @initialize()
    def setup(self):
        self.plans = [
            factories.make_saas_plan(max_members_allowed=1, price="100.00"),
            factories.make_saas_plan(max_members_allowed=3, price="200.00"),
            factories.make_saas_plan(max_members_allowed=5, price="300.00"),
            factories.make_saas_plan(max_members_allowed=None, price="900.00"),
        ]
        self.gym = factories.make_gym(saas_plan=self.plans[1])

    @rule()
    def create_member(self):
        limit = seat_limit(self.gym)
        current = seat_count(self.gym)

        if limit is not None and current >= limit:
            with pytest.raises(SeatLimitReached) as caught:
                factories.make_member(self.gym)
            # The refusal states both numbers (5.2).
            assert str(current) in str(caught.value.detail)
            assert str(limit) in str(caught.value.detail)
            assert seat_count(self.gym) == current
        else:
            factories.make_member(self.gym)
            assert seat_count(self.gym) == current + 1

    @rule()
    def soft_delete_a_member(self):
        profile = MemberProfile.objects.filter(gym=self.gym, deleted_at__isnull=True).first()
        if profile is None:
            return
        before = seat_count(self.gym)
        soft_delete_member(profile)
        # Releasing capacity is never gated.
        assert seat_count(self.gym) == before - 1

    @rule()
    def restore_a_member(self):
        profile = MemberProfile.all_objects.filter(
            gym=self.gym, deleted_at__isnull=False
        ).first()
        if profile is None:
            return

        limit = seat_limit(self.gym)
        before = seat_count(self.gym)

        if limit is not None and before >= limit:
            with pytest.raises(SeatLimitReached):
                restore_member(profile)
            profile.refresh_from_db()
            # A refused restore leaves the record soft-deleted (5.10).
            assert profile.deleted_at is not None
            assert seat_count(self.gym) == before
        else:
            restore_member(profile)
            assert seat_count(self.gym) == before + 1

    @rule(plan_index=st.integers(min_value=0, max_value=3))
    def change_plan(self, plan_index):
        target = self.plans[plan_index]
        current = seat_count(self.gym)
        before_plan = self.gym.subscription.plan_id

        if target.max_members_allowed is not None and current > target.max_members_allowed:
            with pytest.raises(PlanDowngradeBlocked) as caught:
                change_saas_plan(self.gym, target)
            assert str(current) in str(caught.value.detail)
            assert str(target.max_members_allowed) in str(caught.value.detail)
            self.gym.subscription.refresh_from_db()
            assert self.gym.subscription.plan_id == before_plan
        else:
            change_saas_plan(self.gym, target)
            self.gym.subscription.refresh_from_db()
            assert self.gym.subscription.plan_id == target.pk

    @invariant()
    def seat_count_never_exceeds_the_limit(self):
        if self.gym is None:
            return
        limit = seat_limit(self.gym)
        if limit is None:
            return  # unbounded by design
        assert seat_count(self.gym) <= limit, (
            f"seat_count={seat_count(self.gym)} exceeds limit={limit}"
        )

    @invariant()
    def soft_deleted_members_do_not_count(self):
        if self.gym is None:
            return
        alive = MemberProfile.objects.filter(gym=self.gym, deleted_at__isnull=True).count()
        assert seat_count(self.gym) == alive


TestSeatInvariant = SeatMachine.TestCase
TestSeatInvariant.settings = hyp_settings(
    max_examples=100, stateful_step_count=15, deadline=None
)


def test_null_limit_is_unbounded():
    """5.3: a plan with no max_members_allowed imposes no ceiling."""
    plan = factories.make_saas_plan(max_members_allowed=None)
    gym = factories.make_gym(saas_plan=plan)

    for _ in range(6):
        factories.make_member(gym)

    assert seat_limit(gym) is None
    assert seat_count(gym) == 6
