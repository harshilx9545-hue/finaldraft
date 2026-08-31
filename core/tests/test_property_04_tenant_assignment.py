"""Feature: gym-saas-core, Property 4.

Every create route, with a foreign Gym identifier smuggled into the body under every
spelling a client might try. The stored row's Gym must always be the authenticated
User's, never the one that was sent.

The keys are tried individually *and* together, because a denylist that catches
`gym` but not `gym_id` would pass a test that only ever sends one of them.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import MembershipPlan, MemberProfile, TrainerProfile
from core.tests import factories
from core.tests.endpoints import build_billed_tenant, client_for, url_for

pytestmark = pytest.mark.django_db

#: Spellings of "put this record in another tenant".
INJECTION_KEYS = ["gym", "gym_id", "gym_pk", "tenant", "gymId"]


def injection_bodies(foreign_gym_id):
    """One body per key, plus one carrying every key at once."""
    bodies = [{key: foreign_gym_id} for key in INJECTION_KEYS]
    bodies.append({key: foreign_gym_id for key in INJECTION_KEYS})
    return bodies


# Feature: gym-saas-core, Property 4: For any create request against a tenant-scoped
# model, and for any Gym identifier injected into the request body, the stored record's
# Gym equals the authenticated User's Gym.
# Validates: Requirements 2.3
@settings(max_examples=100)
@given(
    injection_index=st.integers(min_value=0, max_value=len(INJECTION_KEYS)),
    creator_role=st.sampled_from(["owner", "trainer"]),
)
def test_a_created_member_belongs_to_the_creators_gym(injection_index, creator_role):
    a = build_billed_tenant()
    b = build_billed_tenant()

    body = {
        "email": factories.unique_email("injected"),
        "first_name": "Injected",
        "join_date": str(a["gym"].today()),
    }
    body.update(injection_bodies(b["gym"].pk)[injection_index])

    response = client_for(a, creator_role).post(
        url_for("core:member-list"), body, format="json"
    )
    assert response.status_code == 201, response.data

    created = MemberProfile.objects.get(pk=response.json()["id"])
    assert created.gym_id == a["gym"].pk, "a client-supplied gym escaped the tenant"
    assert created.gym_id != b["gym"].pk
    assert created.user.role == "member"


@settings(max_examples=100)
@given(injection_index=st.integers(min_value=0, max_value=len(INJECTION_KEYS)))
def test_a_created_trainer_belongs_to_the_owners_gym(injection_index):
    a = build_billed_tenant()
    b = build_billed_tenant()

    body = {
        "email": factories.unique_email("injectedtrainer"),
        "specialization": "Powerlifting",
    }
    body.update(injection_bodies(b["gym"].pk)[injection_index])

    response = client_for(a, "owner").post(url_for("core:trainer-list"), body, format="json")
    assert response.status_code == 201, response.data

    created = TrainerProfile.objects.get(pk=response.json()["id"])
    assert created.gym_id == a["gym"].pk
    assert created.gym_id != b["gym"].pk
    assert created.user.role == "trainer"


@settings(max_examples=100)
@given(injection_index=st.integers(min_value=0, max_value=len(INJECTION_KEYS)))
def test_a_created_membership_plan_belongs_to_the_owners_gym(injection_index):
    a = build_billed_tenant()
    b = build_billed_tenant()

    body = {
        "name": f"Injected Plan {injection_index}",
        "price": "2500.00",
        "duration_days": 90,
    }
    body.update(injection_bodies(b["gym"].pk)[injection_index])

    response = client_for(a, "owner").post(
        url_for("core:membership-plan-list"), body, format="json"
    )
    assert response.status_code == 201, response.data

    created = MembershipPlan.objects.get(pk=response.json()["id"])
    assert created.gym_id == a["gym"].pk
    assert created.gym_id != b["gym"].pk


def test_a_gym_key_in_the_body_is_dropped_rather_than_validated():
    """The denied keys never reach field validation, so they cannot be probed.

    A 400 naming `gym` would confirm the key is meaningful. The serializer strips it
    in `to_internal_value`, so the request simply succeeds with the server's value.
    """
    a = build_billed_tenant()
    b = build_billed_tenant()

    response = client_for(a, "owner").post(
        url_for("core:membership-plan-list"),
        {
            "name": "Probe Plan",
            "price": "100.00",
            "duration_days": 30,
            "gym": b["gym"].pk,
            "gym_id": b["gym"].pk,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert "gym" not in response.json()
    assert MembershipPlan.objects.get(pk=response.json()["id"]).gym_id == a["gym"].pk


def test_patching_an_existing_record_cannot_move_it_to_another_gym():
    """2.3 applies to updates as well: tenancy is never client-supplied."""
    a = build_billed_tenant()
    b = build_billed_tenant()

    plan = a["plan"]
    response = client_for(a, "owner").patch(
        url_for("core:membership-plan-detail", plan.pk),
        {"name": "Renamed", "gym": b["gym"].pk, "gym_id": b["gym"].pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    plan.refresh_from_db()
    assert plan.gym_id == a["gym"].pk
    assert plan.name == "Renamed"

    member = a["member"]
    member_response = client_for(a, "owner").patch(
        url_for("core:member-detail", member.pk),
        {"goal": "strength", "gym": b["gym"].pk},
        format="json",
    )
    assert member_response.status_code == 200, member_response.data
    member.refresh_from_db()
    assert member.gym_id == a["gym"].pk
    assert member.goal == "strength"


def test_the_service_layer_also_ignores_a_foreign_gym():
    """The seat service takes the Gym as an argument, never from user input."""
    from core.services.seats import create_member_atomically

    a = build_billed_tenant()
    b = build_billed_tenant()

    profile = create_member_atomically(
        a["gym"],
        email=factories.unique_email("servicemember"),
        password=factories.DEFAULT_PASSWORD,
        join_date=a["gym"].today(),
    )
    assert profile.gym_id == a["gym"].pk
    assert profile.gym_id != b["gym"].pk
