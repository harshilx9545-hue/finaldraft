"""Feature: gym-saas-core, Property 33."""
import datetime

import pytest
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.exceptions import Http402, SeatLimitReached
from core.services.seats import restore_member, seat_count
from core.tests import factories

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 33: For any Gym, creation of a MemberProfile is refused
# with 409 naming the current Seat_Count and the limit when Seat_Count has reached a
# non-null limit, refused with 402 when the Gym has no SaasSubscription in status
# `trialing` or `active`, and a restore that would exceed the limit is refused with 409
# leaving the record soft-deleted; while for any update to an existing MemberProfile and
# for any Invoice settlement or Membership date change, no seat evaluation occurs and
# Seat_Count is unchanged.
# Validates: Requirements 5.2, 5.7, 5.10, 5.8, 5.9
@hyp_settings(max_examples=100)
@given(limit=st.integers(min_value=1, max_value=4))
def test_creation_at_the_limit_is_409_naming_both_numbers(limit):
    plan = factories.make_saas_plan(max_members_allowed=limit)
    gym = factories.make_gym(saas_plan=plan)

    for _ in range(limit):
        factories.make_member(gym)

    with pytest.raises(SeatLimitReached) as caught:
        factories.make_member(gym)

    detail = str(caught.value.detail)
    assert str(limit) in detail
    assert caught.value.status_code == 409
    assert caught.value.details["seat_count"] == limit
    assert caught.value.details["limit"] == limit


@hyp_settings(max_examples=100)
@given(status=st.sampled_from(["past_due", "cancelled"]))
def test_creation_without_a_live_subscription_is_402(status):
    gym = factories.make_gym(subscription_status=status)

    with pytest.raises(Http402) as caught:
        factories.make_member(gym)
    assert caught.value.status_code == 402


def test_creation_with_no_subscription_at_all_is_402():
    gym = factories.make_gym(with_subscription=False)

    with pytest.raises(Http402):
        factories.make_member(gym)


@hyp_settings(max_examples=100)
@given(limit=st.integers(min_value=1, max_value=3))
def test_restore_that_would_exceed_the_limit_is_refused_and_stays_deleted(limit):
    """5.10"""
    plan = factories.make_saas_plan(max_members_allowed=limit)
    gym = factories.make_gym(saas_plan=plan)

    members = [factories.make_member(gym) for _ in range(limit)]
    victim = members[0]
    victim.soft_delete()

    # Fill the freed seat so a restore would go over.
    factories.make_member(gym)
    assert seat_count(gym) == limit

    with pytest.raises(SeatLimitReached):
        restore_member(victim)

    victim.refresh_from_db()
    assert victim.deleted_at is not None
    assert seat_count(gym) == limit


# ---- the negative half: operations that must NOT be seat-evaluated -------------

@hyp_settings(max_examples=100)
@given(goal=st.sampled_from(["strength", "aesthetics", "cut", "bulk"]))
def test_updating_an_existing_member_is_never_seat_evaluated(goal, api_client):
    """5.8 as resolved by D5: an update cannot increase Seat_Count."""
    plan = factories.make_saas_plan(max_members_allowed=1)
    gym = factories.make_gym(saas_plan=plan)
    owner = factories.make_owner(gym)
    member = factories.make_member(gym)

    assert seat_count(gym) == 1  # already at the limit

    factories.authenticate(api_client, owner.user)
    response = api_client.patch(
        reverse("core:member-detail", args=[member.pk]), {"goal": goal}, format="json"
    )

    assert response.status_code == 200, response.content
    member.refresh_from_db()
    assert member.goal == goal
    assert seat_count(gym) == 1


@hyp_settings(max_examples=100)
@given(offset=st.integers(min_value=-30, max_value=30))
def test_membership_date_changes_and_invoice_settlement_do_not_touch_seat_count(offset):
    """5.9"""
    from core.services.invoicing import settle

    plan = factories.make_saas_plan(max_members_allowed=1)
    gym = factories.make_gym(saas_plan=plan)
    membership_plan = factories.make_membership_plan(gym, price="500.00")
    member = factories.make_member(gym, plan=membership_plan)

    before = seat_count(gym)

    membership = factories.make_membership(
        member, membership_plan, start=gym.today() + datetime.timedelta(days=offset)
    )
    invoice = factories.make_invoice(
        gym, member.user, taxable="500.00", membership=membership
    )
    payment = factories.make_payment(invoice, status="succeeded")
    settle(invoice, payment)

    assert seat_count(gym) == before
