"""Feature: gym-saas-core, Property 5.

A foreign primary key in a reference field is a different attack from a foreign
`gym` key: the id is real, it resolves through the relation's queryset, and only an
explicit same-tenant check stops it. Both the create and the update path are driven,
because a serializer that validates on create and not on update is the usual shape
of this bug.

The rejection must *name the field* — a generic 400 would leave a client unable to
tell which of `trainer` and `plan` was wrong.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import MemberProfile
from core.tests import factories
from core.tests.endpoints import build_billed_tenant, client_for, snapshot_tenant_state, url_for

pytestmark = pytest.mark.django_db

REFERENCE_FIELDS = ["trainer", "plan"]


def foreign_reference(tenant, field):
    return {"trainer": tenant["trainer"].pk, "plan": tenant["plan"].pk}[field]


# Feature: gym-saas-core, Property 5: For any two distinct Gyms A and B, and for any
# reference field in {trainer, plan} on a MemberProfile of Gym A, assigning a Gym B
# object to that field is rejected with a validation error naming that field, and no
# MemberProfile row changes.
# Validates: Requirements 2.6, 2.7
@settings(max_examples=100)
@given(field=st.sampled_from(REFERENCE_FIELDS), creator_role=st.sampled_from(["owner", "trainer"]))
def test_creating_a_member_with_a_foreign_reference_is_rejected_by_field(field, creator_role):
    a = build_billed_tenant()
    b = build_billed_tenant()

    before = snapshot_tenant_state()
    response = client_for(a, creator_role).post(
        url_for("core:member-list"),
        {
            "email": factories.unique_email("crossref"),
            "join_date": str(a["gym"].today()),
            field: foreign_reference(b, field),
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    envelope = response.json()["error"]
    assert envelope["code"] == "VALIDATION_ERROR"
    assert envelope["details"]["field"] == field, envelope
    assert field in envelope["message"]

    # 2.6/2.7: no row changes, and no orphan User is left behind either.
    assert snapshot_tenant_state() == before


@settings(max_examples=100)
@given(field=st.sampled_from(REFERENCE_FIELDS))
def test_patching_a_member_with_a_foreign_reference_is_rejected_by_field(field):
    a = build_billed_tenant()
    b = build_billed_tenant()

    member = a["member"]
    before = snapshot_tenant_state()

    response = client_for(a, "owner").patch(
        url_for("core:member-detail", member.pk),
        {field: foreign_reference(b, field)},
        format="json",
    )

    assert response.status_code == 400, response.data
    envelope = response.json()["error"]
    assert envelope["details"]["field"] == field, envelope

    member.refresh_from_db()
    assert getattr(member, f"{field}_id") != foreign_reference(b, field)
    assert snapshot_tenant_state() == before


@settings(max_examples=100)
@given(field=st.sampled_from(REFERENCE_FIELDS))
def test_an_own_gym_reference_is_accepted_so_the_rejections_mean_something(field):
    """The control case: the same field with a same-tenant id succeeds."""
    a = build_billed_tenant()
    own = {"trainer": a["trainer"].pk, "plan": a["plan"].pk}[field]

    response = client_for(a, "owner").patch(
        url_for("core:member-detail", a["member"].pk), {field: own}, format="json"
    )

    assert response.status_code == 200, response.data
    a["member"].refresh_from_db()
    assert getattr(a["member"], f"{field}_id") == own


def test_the_seat_service_rejects_a_foreign_reference_and_creates_no_user():
    """The service enforces it too, so a non-API caller cannot bypass the check."""
    from django.contrib.auth import get_user_model
    from rest_framework.exceptions import ValidationError

    from core.services.seats import create_member_atomically

    a = build_billed_tenant()
    b = build_billed_tenant()
    User = get_user_model()

    for field, value in (("plan", b["plan"]), ("trainer", b["trainer"])):
        email = factories.unique_email("serviceref")
        before_users = User.objects.count()
        before_members = MemberProfile.all_objects.count()

        with pytest.raises(ValidationError) as caught:
            create_member_atomically(
                a["gym"],
                email=email,
                password=factories.DEFAULT_PASSWORD,
                **{field: value},
            )
        assert field in str(caught.value.detail)

        # Atomic: the User insert precedes the failure inside the block, so it must
        # roll back with it.
        assert User.objects.count() == before_users
        assert MemberProfile.all_objects.count() == before_members
        assert not User.objects.filter(email=email).exists()


def test_a_membership_cannot_be_created_against_another_gyms_plan():
    """2.7 at the membership boundary, which is where the plan is actually charged."""
    from rest_framework.exceptions import ValidationError

    from core.models import Membership
    from core.services.memberships import create_membership

    a = build_billed_tenant()
    b = build_billed_tenant()

    before = Membership.all_objects.count()
    with pytest.raises(ValidationError) as caught:
        create_membership(a["member"], b["plan"], start=a["gym"].today())

    assert "plan" in str(caught.value.detail)
    assert Membership.all_objects.count() == before
