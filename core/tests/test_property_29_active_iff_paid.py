"""Feature: gym-saas-core, Property 29."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.services.memberships import is_member_active, latest_end_date, status_of
from core.tests import factories

pytestmark = pytest.mark.django_db

INVOICE_STATES = ["none", "open", "settled", "void"]


# Feature: gym-saas-core, Property 29: For any combination of Membership dates,
# MembershipPlan price, and Invoice status, the Member's computed active state is true if
# and only if the Member holds a Membership whose status is `active` that either
# references a `settled` Invoice or references a zero-price plan with no Invoice; the
# profile endpoint returns that state together with the latest Membership end date, or
# null when the Member holds no Membership; and no request can set an active or status
# field on MemberProfile while join_date accepts any supplied date.
# Validates: Requirements 20.5, 20.4, 20.9, 20.10
@hyp_settings(max_examples=100)
@given(
    price=st.sampled_from(["0.00", "1500.00"]),
    invoice_state=st.sampled_from(INVOICE_STATES),
    day_offset=st.integers(min_value=-40, max_value=40),
    duration=st.sampled_from([1, 30, 365]),
)
def test_member_is_active_exactly_when_paid_and_in_period(
    price, invoice_state, day_offset, duration
):
    gym = factories.make_gym()
    plan = factories.make_membership_plan(gym, price=price, duration_days=duration)
    member = factories.make_member(gym, plan=plan)

    today = gym.today()
    start = today - datetime.timedelta(days=day_offset)
    membership = factories.make_membership(member, plan, start=start)

    if invoice_state != "none":
        factories.make_invoice(
            gym,
            member.user,
            taxable=price,
            membership=membership,
            status=invoice_state,
        )

    in_period = status_of(membership, today) == "active"
    is_free = Decimal(price) == Decimal("0.00")
    paid = invoice_state == "settled" or (is_free and invoice_state == "none")

    expected = in_period and paid
    assert is_member_active(member, today) is expected, (
        f"price={price} invoice={invoice_state} offset={day_offset}"
    )


@hyp_settings(max_examples=100)
@given(has_membership=st.booleans(), duration=st.sampled_from([1, 30, 365]))
def test_me_reports_active_state_and_latest_end_date(has_membership, duration, api_client):
    gym = factories.make_gym()
    plan = factories.make_membership_plan(gym, price="0.00", duration_days=duration)
    member = factories.make_member(gym, plan=plan)

    expected_end = None
    if has_membership:
        membership = factories.make_membership(member, plan, start=gym.today())
        expected_end = membership.end_date

    factories.authenticate(api_client, member.user)
    response = api_client.get(reverse("core:me"))

    assert response.status_code == 200
    body = response.json()
    assert body["is_active_member"] is is_member_active(member, gym.today())
    if expected_end is None:
        assert body["current_period_end"] is None
    else:
        assert body["current_period_end"] == expected_end.isoformat()
    assert latest_end_date(member) == expected_end


@hyp_settings(max_examples=100)
@given(
    injected=st.sampled_from(["status", "is_active", "active", "is_active_member"]),
    join_offset=st.integers(min_value=-500, max_value=0),
)
def test_active_state_is_not_settable_but_join_date_is(injected, join_offset, api_client):
    """20.4, 20.9: derived state is read-only; a back-dated join is accepted."""
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    member = factories.make_member(gym)

    back_dated = gym.today() + datetime.timedelta(days=join_offset)

    factories.authenticate(api_client, owner.user)
    response = api_client.patch(
        reverse("core:member-detail", args=[member.pk]),
        {injected: True, "join_date": back_dated.isoformat()},
        format="json",
    )

    assert response.status_code == 200, response.content
    member.refresh_from_db()

    # join_date took the supplied value.
    assert member.join_date == back_dated
    # The injected key created no stored field and did not become truthy state.
    assert not hasattr(member, "status")
    assert response.json()["is_active"] is is_member_active(member, gym.today())
