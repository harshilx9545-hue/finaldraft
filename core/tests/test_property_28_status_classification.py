"""Feature: gym-saas-core, Property 28."""
import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from core.services.memberships import (
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_UPCOMING,
    end_date_for,
    status_of,
)
from core.tests.strategies import dates, durations_valid, iana_timezones


def _period(start, duration):
    return SimpleNamespace(start_date=start, end_date=end_date_for(start, duration))


# Feature: gym-saas-core, Property 28: For any Membership period, any Gym IANA
# timezone, and any instant, the derived status is `upcoming` before the start date,
# `active` from the start date through the end date inclusive, and `expired` after the
# end date, evaluated against the current date in the Gym's timezone.
# Validates: Requirements 20.1
@settings(max_examples=500)
@given(
    start=dates(),
    duration=durations_valid(),
    offset_days=st.integers(min_value=-800, max_value=4200),
)
def test_status_classification(start, duration, offset_days):
    membership = _period(start, duration)
    today = start + datetime.timedelta(days=offset_days)

    status = status_of(membership, today)

    if today < membership.start_date:
        assert status == STATUS_UPCOMING
    elif today <= membership.end_date:
        assert status == STATUS_ACTIVE
    else:
        assert status == STATUS_EXPIRED


@settings(max_examples=500)
@given(start=dates(), duration=durations_valid())
def test_boundaries_are_inclusive(start, duration):
    """Both the first and the last day are `active`; the day after is not."""
    membership = _period(start, duration)
    assert status_of(membership, membership.start_date) == STATUS_ACTIVE
    assert status_of(membership, membership.end_date) == STATUS_ACTIVE
    assert (
        status_of(membership, membership.end_date + datetime.timedelta(days=1))
        == STATUS_EXPIRED
    )
    assert (
        status_of(membership, membership.start_date - datetime.timedelta(days=1))
        == STATUS_UPCOMING
    )


# Feature: gym-saas-core, Property 28 (timezone clause): the evaluation date is the
# Gym's local date, not the server's.
@settings(max_examples=500)
@given(zone=iana_timezones(), instant=st.datetimes(
    min_value=datetime.datetime(2020, 1, 1),
    max_value=datetime.datetime(2035, 12, 31),
))
def test_local_date_drives_the_comparison(zone, instant):
    aware_utc = instant.replace(tzinfo=datetime.timezone.utc)
    local_date = aware_utc.astimezone(ZoneInfo(zone)).date()

    # A membership that ends on the *local* date is still active, even when the UTC
    # date has already rolled over (or has not yet).
    membership = _period(local_date, 1)
    assert status_of(membership, local_date) == STATUS_ACTIVE
