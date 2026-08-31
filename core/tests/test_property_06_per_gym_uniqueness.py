"""Feature: gym-saas-core, Property 6.

Both halves of the biconditional matter. "Rejected in the same Gym" without
"accepted in a different Gym" would also be satisfied by a platform-wide unique
constraint, which is precisely the pre-Phase-1 defect this requirement corrects: two
gyms must both be able to sell a plan called "Monthly".

`MembershipPlan` is checked through the API and the constraint; `StrengthStandard`
has no Phase 1 route, so it is checked at the model layer only.
"""
import pytest
from django.db import IntegrityError, transaction
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import MembershipPlan, StrengthStandard
from core.tests import factories
from core.tests.endpoints import build_billed_tenant, client_for, url_for

pytestmark = pytest.mark.django_db

#: Names including the case variations the constraint folds together.
PLAN_NAMES = st.one_of(
    st.sampled_from(["Monthly", "monthly", "MONTHLY", "Gold Tier", "  Quarterly  "]),
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ",
        min_size=1,
        max_size=40,
    ).filter(lambda value: value.strip() != ""),
)

GENDERS = st.sampled_from(["m", "f"])


def create_plan(client, name):
    return client.post(
        url_for("core:membership-plan-list"),
        {"name": name, "price": "1000.00", "duration_days": 30},
        format="json",
    )


# Feature: gym-saas-core, Property 6: For any key value, creating two records with that
# key in the same Gym is rejected while creating one record with that key in each of two
# different Gyms succeeds, for MembershipPlan keyed on name and for StrengthStandard
# keyed on (exercise_name, gender).
# Validates: Requirements 2.4, 2.5
@settings(max_examples=100)
@given(name=PLAN_NAMES)
def test_a_membership_plan_name_is_unique_within_a_gym_and_free_across_gyms(name):
    a = build_billed_tenant()
    b = build_billed_tenant()

    first = create_plan(client_for(a, "owner"), name)
    assert first.status_code == 201, first.data

    # Same name, same gym: refused.
    duplicate = create_plan(client_for(a, "owner"), name)
    assert duplicate.status_code == 400, duplicate.data
    assert duplicate.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (
        MembershipPlan.objects.filter(gym=a["gym"], name=name.strip()).count() == 1
    ), "the refusal must not have created a second row"

    # Same name, different gym: accepted. This is the half that proves the scope.
    other_gym = create_plan(client_for(b, "owner"), name)
    assert other_gym.status_code == 201, other_gym.data
    assert MembershipPlan.objects.filter(gym=b["gym"], name=name.strip()).count() == 1


@settings(max_examples=100)
@given(name=st.sampled_from(["Monthly", "Gold", "Annual Pass"]))
def test_membership_plan_name_uniqueness_is_case_insensitive(name):
    a = build_billed_tenant()

    assert create_plan(client_for(a, "owner"), name).status_code == 201

    for variant in (name.lower(), name.upper(), name.swapcase()):
        response = create_plan(client_for(a, "owner"), variant)
        assert response.status_code == 400, (
            f"{variant!r} must collide with {name!r} within one gym"
        )


def test_the_database_constraint_holds_even_when_validation_is_bypassed():
    """2.4 must survive a direct insert, not only a serializer check."""
    a = build_billed_tenant()
    b = build_billed_tenant()

    factories.make_membership_plan(a["gym"], name="Signature")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            factories.make_membership_plan(a["gym"], name="signature")

    # The same name in the other tenant inserts cleanly.
    assert factories.make_membership_plan(b["gym"], name="Signature").pk


@settings(max_examples=100)
@given(exercise=st.sampled_from(["Bench Press", "Squat", "Deadlift"]), gender=GENDERS)
def test_a_strength_standard_is_unique_per_gym_exercise_and_gender(exercise, gender):
    """2.5: the key is (gym, exercise_name, gender), not exercise_name alone."""
    a = build_billed_tenant()
    b = build_billed_tenant()

    factories.make_strength_standard(a["gym"], exercise_name=exercise, gender=gender)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            factories.make_strength_standard(
                a["gym"], exercise_name=exercise, gender=gender
            )

    # Same exercise, other gender: a distinct key, so accepted.
    other_gender = "f" if gender == "m" else "m"
    assert factories.make_strength_standard(
        a["gym"], exercise_name=exercise, gender=other_gender
    ).pk

    # Same key, different gym: accepted.
    assert factories.make_strength_standard(
        b["gym"], exercise_name=exercise, gender=gender
    ).pk


def test_a_platform_standard_coexists_with_a_gym_override():
    """2.2/2.5 together: the null-gym row is a separate key from any gym's."""
    a = build_billed_tenant()

    platform = factories.make_strength_standard(None, exercise_name="Overhead", gender="m")
    override = factories.make_strength_standard(a["gym"], exercise_name="Overhead", gender="m")

    assert platform.pk != override.pk
    assert StrengthStandard.objects.filter(exercise_name="Overhead", gender="m").count() == 2

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            factories.make_strength_standard(None, exercise_name="Overhead", gender="m")


def test_gym_slug_uniqueness_is_platform_wide_and_case_insensitive():
    """1.4: the slug is the tenant's address, so its scope is the whole platform."""
    from core.models import Gym

    factories.make_gym(slug="unique-address", with_subscription=False)

    for variant in ("unique-address", "Unique-Address", "UNIQUE-ADDRESS"):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Gym.objects.create(
                    name="Impostor",
                    slug=variant,
                    contact_email="impostor@example.com",
                    contact_phone="+919999900001",
                )
