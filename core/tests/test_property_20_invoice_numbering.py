"""Feature: gym-saas-core, Property 20.

The concurrency clause needs PostgreSQL; the sequential and rollback clauses hold on
any backend and are what actually guard the gapless property in practice.
"""
import datetime

import pytest
from django.db import connection, transaction
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models import Invoice
from core.services.invoicing import financial_year_for
from core.tests import factories

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]

IS_POSTGRES = connection.vendor == "postgresql"


def _committed_numbers(gym, fy):
    return sorted(
        Invoice.all_objects.filter(gym=gym, financial_year=fy).values_list(
            "sequence_no", flat=True
        )
    )


# Feature: gym-saas-core, Property 20: For any sequence of Invoice issue attempts across
# random Gyms and financial years, including concurrent attempts and attempts whose
# transaction rolls back, the numbers committed within each (Gym, financial year) pair form
# a contiguous ascending sequence starting at 1 with no gaps and no duplicates.
# Validates: Requirements 19.3
@hyp_settings(max_examples=50, deadline=None)
@given(
    gym_count=st.integers(min_value=1, max_value=3),
    issues=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=2),      # which gym
            st.sampled_from([2024, 2025, 2026]),         # which financial year
            st.booleans(),                               # roll this attempt back
        ),
        min_size=1,
        max_size=10,
    ),
)
def test_invoice_numbers_are_unique_and_gapless(gym_count, issues):
    from core.services.invoicing import issue_invoice

    gyms = [factories.make_gym() for _ in range(gym_count)]
    owners = [factories.make_owner(gym) for gym in gyms]
    touched = set()

    for gym_index, year, should_rollback in issues:
        gym = gyms[gym_index % gym_count]
        owner = owners[gym_index % gym_count]
        issue_date = datetime.date(year, 6, 15)  # mid-year, so the FY is unambiguous
        fy = financial_year_for(issue_date)
        touched.add((gym.pk, fy))

        if should_rollback:
            # A rolled-back attempt must roll the sequence increment back too,
            # otherwise it leaves a permanent hole in the series.
            try:
                with transaction.atomic():
                    issue_invoice(
                        gym=gym,
                        payer_user=owner.user,
                        taxable_value="100.00",
                        saas_subscription=gym.subscription,
                        issue_date=issue_date,
                    )
                    raise RuntimeError("injected rollback")
            except RuntimeError:
                pass
        else:
            issue_invoice(
                gym=gym,
                payer_user=owner.user,
                taxable_value="100.00",
                saas_subscription=gym.subscription,
                issue_date=issue_date,
            )

    for gym in gyms:
        for gym_pk, fy in touched:
            if gym_pk != gym.pk:
                continue
            numbers = _committed_numbers(gym, fy)
            if not numbers:
                continue
            assert numbers == list(range(1, len(numbers) + 1)), (
                f"gym {gym.slug} {fy}: {numbers}"
            )
            assert len(numbers) == len(set(numbers)), "duplicate sequence numbers"


@hyp_settings(max_examples=100)
@given(day=st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2035, 12, 31)))
def test_financial_year_runs_april_to_march(day):
    fy = financial_year_for(day)
    start_year = int(fy.split("-")[0])

    if day.month >= 4:
        assert start_year == day.year
    else:
        assert start_year == day.year - 1
    assert fy == f"{start_year}-{str(start_year + 1)[-2:]}"


def test_number_format_is_slug_fy_and_five_digits():
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    invoice = factories.make_invoice(gym, owner.user, taxable="100.00")

    assert invoice.number == f"{gym.slug}/{invoice.financial_year}/{invoice.sequence_no:05d}"
    assert invoice.sequence_no == 1


def test_numbering_is_independent_per_gym():
    """Two gyms both start at 1: the series is per tenant, not global."""
    first, second = factories.make_gym(), factories.make_gym()
    first_owner, second_owner = factories.make_owner(first), factories.make_owner(second)

    a = factories.make_invoice(first, first_owner.user, taxable="100.00")
    b = factories.make_invoice(second, second_owner.user, taxable="100.00")

    assert a.sequence_no == b.sequence_no == 1
    assert a.number != b.number


@pytest.mark.skipif(
    not IS_POSTGRES,
    reason="SQLite locking is too coarse to prove the concurrent clause.",
)
def test_concurrent_issues_produce_no_duplicates():
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from core.services.invoicing import issue_invoice

    gym = factories.make_gym()
    owner = factories.make_owner(gym)

    def issue(_):
        try:
            issue_invoice(
                gym=gym,
                payer_user=owner.user,
                taxable_value="100.00",
                saas_subscription=gym.subscription,
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(issue, range(5)))

    fy = financial_year_for(gym.today())
    numbers = _committed_numbers(gym, fy)
    assert numbers == list(range(1, 6)), numbers
