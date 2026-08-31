"""Feature: gym-saas-core, Property 32.

Marked `slow`. On SQLite the row lock is coarse enough that concurrency is simulated
sequentially; the criterion is only truly *proved* against PostgreSQL, so the
concurrent variant skips itself when the test database is SQLite rather than passing
vacuously.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, connections
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.exceptions import Http402, SeatLimitReached
from core.services.seats import seat_count
from core.tests import factories

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]

IS_POSTGRES = connection.vendor == "postgresql"


def _attempt(gym):
    try:
        factories.make_member(gym)
        return "created"
    except SeatLimitReached:
        return "refused"
    except Http402:
        return "no_subscription"
    finally:
        connections.close_all()


# Feature: gym-saas-core, Property 32: For any member count N >= 1 and for any remaining
# seat count K >= 0, issuing N concurrent MemberProfile creation requests against a Gym
# with K remaining seats results in exactly min(N, K) created records, with the remainder
# refused, and no intermediate state exceeding the limit.
# Validates: Requirements 5.1
@hyp_settings(max_examples=25, deadline=None)
@given(n=st.integers(min_value=1, max_value=6), k=st.integers(min_value=0, max_value=4))
def test_sequential_attempts_yield_exactly_min_n_k(n, k):
    """The arithmetic half of the property, provable on any backend."""
    plan = factories.make_saas_plan(max_members_allowed=k)
    gym = factories.make_gym(saas_plan=plan)

    outcomes = [_attempt(gym) for _ in range(n)]

    assert outcomes.count("created") == min(n, k)
    assert outcomes.count("refused") == n - min(n, k)
    assert seat_count(gym) == min(n, k)
    assert seat_count(gym) <= k


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite's locking is too coarse to prove the concurrency criterion; "
    "run against PostgreSQL to exercise this.",
)
@hyp_settings(max_examples=10, deadline=None)
@given(n=st.integers(min_value=2, max_value=6), k=st.integers(min_value=0, max_value=4))
def test_concurrent_attempts_yield_exactly_min_n_k(n, k):
    plan = factories.make_saas_plan(max_members_allowed=k)
    gym = factories.make_gym(saas_plan=plan)

    with ThreadPoolExecutor(max_workers=n) as pool:
        outcomes = list(pool.map(lambda _: _attempt(gym), range(n)))

    assert outcomes.count("created") == min(n, k), outcomes
    assert seat_count(gym) == min(n, k)


def test_gym_row_is_locked_during_seat_evaluation():
    """The mechanism, asserted structurally so the intent survives a refactor."""
    import inspect

    from core.services import seats

    source = inspect.getsource(seats.create_member_atomically)
    assert "select_for_update" in source
    # The lock must be taken before the seat check, not after.
    assert source.index("select_for_update") < source.index("assert_seat_available")
