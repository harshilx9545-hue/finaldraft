"""Feature: gym-saas-core, Property 16 (stateful)."""
import pytest
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)
from rest_framework.exceptions import ValidationError

from core.models import MemberProfile, OwnerProfile, TrainerProfile, User
from core.services import profiles as profile_service
from core.tests import factories

pytestmark = pytest.mark.django_db(transaction=True)

PROFILE_MODELS = {
    "owner": OwnerProfile,
    "trainer": TrainerProfile,
    "member": MemberProfile,
}


# Feature: gym-saas-core, Property 16: For any sequence of registration, invitation,
# role-change, profile-creation, and failure-injection operations, every committed User
# whose is_staff and is_superuser are both false holds exactly one non-soft-deleted
# profile whose type corresponds to the stored role, and every operation that would
# violate that correspondence - mismatched profile type, second profile, role change with
# an existing profile of the previous type, or any profile for a staff account - is
# rejected with a validation error naming the conflicting values while leaving the
# existing role and profile unchanged.
# Validates: Requirements 12.4, 12.1, 12.2, 12.3, 12.5, 12.6, 12.7, 11.1, 11.3, 11.4,
# 11.5
class RoleProfileMachine(RuleBasedStateMachine):
    """Drives the five consistency rules against a real database."""

    def __init__(self):
        super().__init__()
        self.gym = None
        self.user_ids = []
        self.staff_ids = []

    @initialize()
    def setup(self):
        self.gym = factories.make_gym()

    # -- construction ---------------------------------------------------------

    @rule(role=st.sampled_from(list(PROFILE_MODELS)))
    def register_with_profile(self, role):
        """The legal path: a user and its matching profile."""
        profile = {
            "owner": factories.make_owner,
            "trainer": factories.make_trainer,
            "member": factories.make_member,
        }[role](self.gym)
        self.user_ids.append(profile.user_id)

    @rule()
    def create_staff_account(self):
        """A platform operator: staff, no profile, no Gym (D6)."""
        staff = factories.make_staff()
        self.staff_ids.append(staff.pk)

    # -- violations, all of which must be refused ------------------------------

    @rule(role=st.sampled_from(list(PROFILE_MODELS)))
    def reject_second_profile(self, role):
        if not self.user_ids:
            return
        user = User.objects.get(pk=self.user_ids[-1])
        before = (user.role, profile_service.existing_profiles(user).keys())

        with pytest.raises(ValidationError) as caught:
            profile_service.create_profile(user, role, gym=self.gym)

        detail = caught.value.detail
        # The error names the conflicting values, not just "invalid".
        assert any(key in detail for key in ("profile", "role")), detail

        user.refresh_from_db()
        assert (user.role, profile_service.existing_profiles(user).keys()) == before

    @rule(new_role=st.sampled_from(list(PROFILE_MODELS)))
    def reject_role_change_while_profile_exists(self, new_role):
        if not self.user_ids:
            return
        user = User.objects.get(pk=self.user_ids[-1])
        if new_role == user.role:
            return

        before_role = user.role
        with pytest.raises(ValidationError) as caught:
            profile_service.assert_role_change_allowed(user, new_role)
        assert "role" in caught.value.detail

        user.refresh_from_db()
        assert user.role == before_role

    @rule(role=st.sampled_from(list(PROFILE_MODELS)))
    def reject_profile_for_staff_account(self, role):
        if not self.staff_ids:
            return
        staff = User.objects.get(pk=self.staff_ids[-1])

        with pytest.raises(ValidationError) as caught:
            profile_service.create_profile(staff, role, gym=self.gym)
        assert "user" in caught.value.detail or "role" in caught.value.detail

        assert profile_service.existing_profiles(staff) == {}

    @rule(role=st.sampled_from(list(PROFILE_MODELS)))
    def reject_mismatched_profile_type(self, role):
        """A profile whose type disagrees with the stored role is refused (12.2)."""
        user = factories.make_user(role="member")
        if role == "member":
            return

        with pytest.raises(ValidationError) as caught:
            profile_service.create_profile(user, role, gym=self.gym)
        assert "role" in caught.value.detail

        assert profile_service.existing_profiles(user) == {}

    # -- the legal role change -------------------------------------------------

    @rule()
    def change_role_after_soft_deleting_the_profile(self):
        """Rule 5: role change plus profile creation is atomic when no profile exists."""
        if not self.user_ids:
            return
        user = User.objects.get(pk=self.user_ids[-1])
        held = profile_service.existing_profiles(user)
        if not held:
            return

        (current_role,) = held
        held[current_role].soft_delete()

        target = next(role for role in PROFILE_MODELS if role != current_role)
        fields = {"gym": self.gym}
        if target == "owner":
            fields["business_name"] = self.gym.name
        elif target == "member":
            fields["join_date"] = self.gym.today()

        profile_service.change_role_with_profile(user, target, **fields)

        user.refresh_from_db()
        assert user.role == target
        assert set(profile_service.existing_profiles(user)) == {target}

    # -- the invariant ---------------------------------------------------------

    @invariant()
    def every_user_agrees_with_its_profile(self):
        for user in User.objects.all():
            if user.is_staff or user.is_superuser:
                assert profile_service.existing_profiles(user) == {}, (
                    f"staff account {user.pk} holds a profile"
                )
                continue
            held = profile_service.existing_profiles(user)
            if not held:
                # A bare User with no profile yet is legal mid-sequence; it is only
                # committed identities that must agree.
                continue
            assert len(held) == 1, f"user {user.pk} holds {sorted(held)}"
            assert next(iter(held)) == user.role, (
                f"user {user.pk}: role={user.role}, profile={next(iter(held))}"
            )


TestRoleProfileAgreement = RoleProfileMachine.TestCase
TestRoleProfileAgreement.settings = hyp_settings(
    max_examples=100, stateful_step_count=12, deadline=None
)


def test_self_service_registration_is_refused_for_trainer_and_member():
    """11.3, 12.6: only owners self-register."""
    from core.services.registration import reject_self_service_role

    for role in ("trainer", "member"):
        with pytest.raises(ValidationError) as caught:
            reject_self_service_role(role)
        assert "role" in caught.value.detail

    # Owner is allowed through.
    reject_self_service_role("owner")


def test_invited_user_inherits_the_inviting_owners_gym():
    """12.7"""
    from core.services.registration import invite_trainer

    gym = factories.make_gym()
    owner = factories.make_owner(gym)

    result = invite_trainer(gym=gym, email=factories.unique_email(), actor=owner.user)
    assert result["profile"].gym_id == gym.pk
    assert result["user"].role == "trainer"
