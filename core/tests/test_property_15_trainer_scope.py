"""Feature: gym-saas-core, Property 15.

A random trainer-to-member assignment graph inside one Gym, then every read and
write a trainer can attempt against it. The graph matters: with a single trainer and
a single member, "the trainer can see the member" and "the trainer can see the Gym"
are indistinguishable, and only the first is what 15.3 grants.

The read boundary is 404 rather than 403 — an unassigned member in the same Gym must
not be discoverable — while the write boundary is 403, because the trainer's role is
what refuses the operation rather than the record being invisible.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import MemberProfile
from core.tests import factories
from core.tests.endpoints import (
    build_billed_tenant,
    client_for,
    result_rows,
    snapshot_tenant_state,
    url_for,
)

pytestmark = pytest.mark.django_db


def assignment_graph(trainer_count, member_count, assignment_bits):
    """One Gym, several trainers, several members, a random assignment mapping."""
    tenant = build_billed_tenant()
    gym = tenant["gym"]

    trainers = [tenant["trainer"]] + [
        factories.make_trainer(gym) for _ in range(trainer_count - 1)
    ]
    members = []
    for index in range(member_count):
        choice = assignment_bits[index % len(assignment_bits)]
        # `None` means unassigned, which is the case 15.3 must hide from every
        # trainer rather than show to all of them.
        trainer = None if choice < 0 else trainers[choice % len(trainers)]
        members.append(factories.make_member(gym, plan=tenant["plan"], trainer=trainer))

    tenant["trainers"] = trainers
    tenant["members"] = members
    return tenant


# Feature: gym-saas-core, Property 15: For any Gym containing a random
# trainer-to-member assignment graph, a Trainer's read of a Member's record succeeds if
# and only if that Member is assigned to that Trainer, returning 404 otherwise, and the
# Trainer's writes are limited to creating a MemberProfile in that Gym and updating
# assigned Members, with every other write - including any write to Payment or Invoice -
# denied with 403.
# Validates: Requirements 15.3, 15.10
@settings(max_examples=100, deadline=None)
@given(
    trainer_count=st.integers(min_value=1, max_value=3),
    member_count=st.integers(min_value=1, max_value=5),
    assignment_bits=st.lists(
        st.integers(min_value=-1, max_value=2), min_size=1, max_size=5
    ),
)
def test_a_trainer_reads_exactly_their_assigned_members(
    trainer_count, member_count, assignment_bits
):
    tenant = assignment_graph(trainer_count, member_count, assignment_bits)
    trainer = tenant["trainers"][0]
    client = client_for(tenant, "trainer")

    assigned = set(
        MemberProfile.objects.filter(gym=tenant["gym"], trainer=trainer).values_list(
            "pk", flat=True
        )
    )
    everyone = set(
        MemberProfile.objects.filter(gym=tenant["gym"]).values_list("pk", flat=True)
    )

    listed = {row["id"] for row in result_rows(client.get(url_for("core:member-list")))}
    assert listed == assigned, f"listed {listed}, assigned {assigned}"

    for member_pk in everyone:
        response = client.get(url_for("core:member-detail", member_pk))
        if member_pk in assigned:
            assert response.status_code == 200, response.data
            assert response.json()["id"] == member_pk
        else:
            # 15.3: an unassigned member in the same Gym is not discoverable.
            assert response.status_code == 404, (
                f"member {member_pk} is not assigned to this trainer but returned "
                f"{response.status_code}"
            )


@settings(max_examples=100, deadline=None)
@given(
    trainer_count=st.integers(min_value=2, max_value=3),
    member_count=st.integers(min_value=2, max_value=5),
    assignment_bits=st.lists(
        st.integers(min_value=-1, max_value=2), min_size=1, max_size=5
    ),
)
def test_a_trainer_updates_only_assigned_members(
    trainer_count, member_count, assignment_bits
):
    tenant = assignment_graph(trainer_count, member_count, assignment_bits)
    trainer = tenant["trainers"][0]
    client = client_for(tenant, "trainer")

    for member in tenant["members"]:
        before = member.goal
        response = client.patch(
            url_for("core:member-detail", member.pk), {"goal": "bulk"}, format="json"
        )
        member.refresh_from_db()

        if member.trainer_id == trainer.pk:
            assert response.status_code == 200, response.data
            assert member.goal == "bulk"
        else:
            assert response.status_code == 404, response.data
            assert member.goal == before, "an unassigned member must be unchanged"


def test_a_trainer_may_create_a_member_in_their_own_gym_assigned_to_themselves():
    """15.10: the one write a trainer is granted, and its assignment is forced."""
    tenant = build_billed_tenant()
    trainer = tenant["trainer"]

    response = client_for(tenant, "trainer").post(
        url_for("core:member-list"),
        {
            "email": factories.unique_email("trainercreated"),
            "join_date": str(tenant["gym"].today()),
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    created = MemberProfile.objects.get(pk=response.json()["id"])
    assert created.gym_id == tenant["gym"].pk
    # A trainer may only create members assigned to themselves.
    assert created.trainer_id == trainer.pk


def test_a_trainer_cannot_assign_a_new_member_to_another_trainer():
    """The forced self-assignment holds even when another trainer is named."""
    tenant = build_billed_tenant()
    other_trainer = factories.make_trainer(tenant["gym"])

    response = client_for(tenant, "trainer").post(
        url_for("core:member-list"),
        {
            "email": factories.unique_email("reassign"),
            "trainer": other_trainer.pk,
            "join_date": str(tenant["gym"].today()),
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    created = MemberProfile.objects.get(pk=response.json()["id"])
    assert created.trainer_id == tenant["trainer"].pk
    assert created.trainer_id != other_trainer.pk


def test_a_trainer_cannot_write_anything_else():
    """15.10: every other write is 403, including Payment and Invoice."""
    tenant = build_billed_tenant()
    client = client_for(tenant, "trainer")
    before = snapshot_tenant_state()

    refusals = [
        ("patch", url_for("core:gym-detail"), {"name": "Trainer Renamed"}),
        (
            "post",
            url_for("core:membership-plan-list"),
            {"name": "Trainer Plan", "price": "10.00", "duration_days": 30},
        ),
        (
            "patch",
            url_for("core:membership-plan-detail", tenant["plan"].pk),
            {"name": "Trainer Renamed Plan"},
        ),
        (
            "post",
            url_for("core:trainer-list"),
            {"email": factories.unique_email("trainerbytrainer")},
        ),
        ("post", url_for("core:invoice-pay", tenant["member_invoice"].pk), {}),
    ]

    for method, url, body in refusals:
        response = getattr(client, method)(url, body, format="json")
        assert response.status_code == 403, f"{method.upper()} {url}: {response.status_code}"
        assert response.json()["error"]["code"] == "FORBIDDEN"

    assert snapshot_tenant_state() == before


def test_a_trainer_cannot_read_a_members_invoice_or_receipt():
    """15.10 plus payer scoping: financial records are not the trainer's business."""
    tenant = build_billed_tenant()
    client = client_for(tenant, "trainer")

    # Listing is permitted but payer-scoped, so a trainer sees an empty ledger.
    listed = client.get(url_for("core:invoice-list"))
    assert listed.status_code == 200, listed.data
    assert result_rows(listed) == []

    detail = client.get(url_for("core:invoice-detail", tenant["member_invoice"].pk))
    assert detail.status_code == 404, detail.data

    receipt = client.get(url_for("core:payment-receipt", tenant["member_payment"].pk))
    assert receipt.status_code == 403, receipt.data


def test_a_trainer_cannot_reach_another_gyms_members_at_all():
    """The tenant filter applies before the assignment filter, not instead of it."""
    a = build_billed_tenant()
    b = build_billed_tenant()

    # Assign B's member to B's trainer, so the record is assigned - just not here.
    b["member"].trainer = b["trainer"]
    b["member"].save(update_fields=["trainer"])

    client = client_for(a, "trainer")
    assert client.get(url_for("core:member-detail", b["member"].pk)).status_code == 404

    listed = {row["id"] for row in result_rows(client.get(url_for("core:member-list")))}
    assert b["member"].pk not in listed


def test_the_forbidden_write_models_are_refused_at_the_permission_layer():
    """TrainerScope refuses Payment and Invoice writes whatever a view declares."""
    from rest_framework.test import APIRequestFactory, force_authenticate
    from rest_framework.views import APIView

    from core.models import Invoice
    from core.permissions import RoleAllowed, TrainerScope
    from core.scoping import TenantScopedQuerysetMixin

    tenant = build_billed_tenant()

    class OverPermissiveInvoiceView(TenantScopedQuerysetMixin, APIView):
        """Deliberately declares a trainer may write. TrainerScope must still refuse."""

        queryset = Invoice.objects.all()
        permission_classes = [RoleAllowed, TrainerScope]
        allowed_roles = {"owner", "trainer"}
        write_roles = {"owner", "trainer"}
        trainer_writable = True

        def post(self, request):
            from rest_framework.response import Response

            return Response({"reached": True})

    request = APIRequestFactory().post("/invoices-danger", {}, format="json")
    force_authenticate(request, user=tenant["trainer"].user)
    response = OverPermissiveInvoiceView.as_view()(request)

    assert response.status_code == 403, (
        "a trainer reached an Invoice write despite the model-level refusal"
    )
