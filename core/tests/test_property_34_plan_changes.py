"""Feature: gym-saas-core, Property 34."""
import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.exceptions import PlanDowngradeBlocked
from core.services.seats import assert_plan_change_allowed, change_saas_plan, seat_count
from core.tests import factories

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 34: For any current Seat_Count and for any requested
# SaasPlan, the change is accepted if and only if the requested plan's max_members_allowed
# is null or greater than or equal to that Seat_Count; a refusal is 409 naming both numbers
# and leaves the SaasSubscription unchanged.
# Validates: Requirements 5.5, 5.6
@hyp_settings(max_examples=100)
@given(
    current_members=st.integers(min_value=0, max_value=5),
    requested_limit=st.one_of(st.none(), st.integers(min_value=1, max_value=6)),
)
def test_plan_change_respects_the_current_seat_count(current_members, requested_limit):
    start_plan = factories.make_saas_plan(max_members_allowed=None, price="900.00")
    gym = factories.make_gym(saas_plan=start_plan)
    for _ in range(current_members):
        factories.make_member(gym)

    target = factories.make_saas_plan(max_members_allowed=requested_limit, price="100.00")
    current = seat_count(gym)
    original_plan_id = gym.subscription.plan_id

    should_accept = requested_limit is None or requested_limit >= current

    if should_accept:
        change_saas_plan(gym, target)
        gym.subscription.refresh_from_db()
        assert gym.subscription.plan_id == target.pk
    else:
        with pytest.raises(PlanDowngradeBlocked) as caught:
            change_saas_plan(gym, target)

        assert caught.value.status_code == 409
        # The refusal names both numbers, so the owner knows how many they are over.
        assert caught.value.details["seat_count"] == current
        assert caught.value.details["limit"] == requested_limit
        assert str(current) in str(caught.value.detail)
        assert str(requested_limit) in str(caught.value.detail)

        gym.subscription.refresh_from_db()
        assert gym.subscription.plan_id == original_plan_id


@hyp_settings(max_examples=100)
@given(current_members=st.integers(min_value=0, max_value=4))
def test_upgrade_to_unlimited_is_always_allowed(current_members):
    gym = factories.make_gym(max_members=10)
    for _ in range(current_members):
        factories.make_member(gym)

    unlimited = factories.make_saas_plan(max_members_allowed=None)
    assert_plan_change_allowed(gym, unlimited)  # does not raise


@hyp_settings(max_examples=100)
@given(seats=st.integers(min_value=1, max_value=5))
def test_change_to_exactly_the_current_count_is_allowed(seats):
    """The boundary: `>=` not `>`."""
    gym = factories.make_gym(max_members=None)
    for _ in range(seats):
        factories.make_member(gym)

    exact = factories.make_saas_plan(max_members_allowed=seats)
    change_saas_plan(gym, exact)

    gym.subscription.refresh_from_db()
    assert gym.subscription.plan_id == exact.pk
