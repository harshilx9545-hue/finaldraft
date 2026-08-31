"""Feature: gym-saas-core, Property 12."""
import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from rest_framework_simplejwt.tokens import AccessToken

from core.services.auth_tokens import issue_tokens
from core.tests import factories

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 12: For any User identifier, role, and Gym
# identifier, decoding the access token issued for those values yields exactly those
# three values.
# Validates: Requirements 13.7, 13.2
@hyp_settings(max_examples=100)
@given(role=st.sampled_from(["owner", "trainer", "member"]))
def test_access_token_claims_round_trip(role):
    gym = factories.make_gym()
    profile = {
        "owner": factories.make_owner,
        "trainer": factories.make_trainer,
        "member": factories.make_member,
    }[role](gym)
    user = profile.user

    tokens = issue_tokens(user)
    decoded = AccessToken(tokens["access"])

    assert decoded["user_id"] == user.pk
    assert decoded["role"] == role
    assert decoded["gym_id"] == gym.pk


@hyp_settings(max_examples=100)
@given(role=st.sampled_from(["owner", "trainer", "member"]))
def test_refresh_token_carries_the_same_claims(role):
    from rest_framework_simplejwt.tokens import RefreshToken

    gym = factories.make_gym()
    profile = {
        "owner": factories.make_owner,
        "trainer": factories.make_trainer,
        "member": factories.make_member,
    }[role](gym)

    tokens = issue_tokens(profile.user)
    decoded = RefreshToken(tokens["refresh"])

    assert decoded["user_id"] == profile.user.pk
    assert decoded["role"] == role
    assert decoded["gym_id"] == gym.pk


def test_staff_account_token_carries_a_null_gym():
    """D6: a platform operator holds no profile and therefore no Gym."""
    staff = factories.make_staff()
    decoded = AccessToken(issue_tokens(staff)["access"])

    assert decoded["gym_id"] is None
    assert decoded["user_id"] == staff.pk
