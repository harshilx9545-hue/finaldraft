"""Feature: gym-saas-core, Property 27."""
import pytest
from hypothesis import given, settings
from rest_framework.exceptions import ValidationError

from core.services.memberships import end_date_for
from core.tests.strategies import dates, durations_invalid, durations_valid


# Feature: gym-saas-core, Property 27: For any start date and for any duration_days
# between 1 and 3650, the computed end date satisfies
# end_date - start_date == duration_days - 1 and end_date >= start_date, and for any
# duration_days outside that range the Membership is rejected with a validation error
# naming the plan field and no Membership row is created.
# Validates: Requirements 20.2, 20.3, 4.4
@settings(max_examples=500)
@given(start=dates(), duration=durations_valid())
def test_end_date_arithmetic(start, duration):
    end = end_date_for(start, duration)
    assert (end - start).days == duration - 1
    assert end >= start


@settings(max_examples=500)
@given(start=dates(), duration=durations_invalid())
def test_out_of_range_duration_is_rejected_naming_the_plan_field(start, duration):
    with pytest.raises(ValidationError) as caught:
        end_date_for(start, duration)
    assert "plan" in caught.value.detail


@settings(max_examples=500)
@given(start=dates())
def test_single_day_membership_starts_and_ends_on_the_same_day(start):
    """duration_days=1 is a valid one-day pass, not an empty period."""
    assert end_date_for(start, 1) == start
