"""Feature: gym-saas-core, Property 1.

Two fully-populated tenants, and every read a User of Gym A can make. The
assertions are deliberately two-sided: the returned identifiers must be a subset of
A's, *and* disjoint from B's. A one-sided check passes on an endpoint that returns
nothing at all, which is not isolation, it is a broken endpoint.

Aggregate counts are checked too, because a `count` computed over an unfiltered
queryset leaks the size of another tenant even when the page itself is clean (3.4).

`StrengthStandard` is the one model where a null Gym means a shared platform row
(2.2). Phase 1 exposes no route for it, so that clause is checked against the
filtering component directly rather than through an endpoint that does not exist.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import (
    Invoice,
    MembershipPlan,
    MemberProfile,
    StrengthStandard,
    TrainerProfile,
)
from core.tests import factories
from core.tests.endpoints import (
    LIST_ENDPOINTS,
    ROUTE_ROLES,
    build_billed_tenant,
    client_for,
    expected_visible_ids,
    result_rows,
    url_for,
    user_for,
)

pytestmark = pytest.mark.django_db

ROLES = ["owner", "trainer", "member"]


def populate(tenant, *, extra_members=2, extra_plans=2, extra_trainers=1):
    """Give a tenant enough rows that a leak would be visible rather than lucky."""
    gym = tenant["gym"]
    for _ in range(extra_plans):
        factories.make_membership_plan(gym)
    for _ in range(extra_trainers):
        factories.make_trainer(gym)
    for index in range(extra_members):
        # Half assigned to the tenant's trainer, half unassigned, so trainer
        # narrowing is exercised as well as tenant filtering.
        factories.make_member(
            gym, trainer=tenant["trainer"] if index % 2 == 0 else None, plan=tenant["plan"]
        )
    factories.make_invoice(gym, tenant["owner"].user, taxable="4000.00")
    return tenant


def two_populated_tenants():
    a = populate(build_billed_tenant())
    b = populate(build_billed_tenant())
    return a, b


# Feature: gym-saas-core, Property 1: For any set of at least two Gyms with randomly
# distributed tenant-scoped records, and any authenticated request from a User of Gym A
# to any tenant-scoped endpoint, every record identifier appearing anywhere in the
# response - top level, nested, or contributing to an aggregate count - belongs to Gym A
# or is a StrengthStandard whose Gym is null, and this holds regardless of the requesting
# User's is_staff and is_superuser values.
# Validates: Requirements 3.1, 3.4, 2.2, 15.9
@settings(max_examples=100)
@given(
    route=st.sampled_from(sorted(LIST_ENDPOINTS)),
    role=st.sampled_from(ROLES),
    staff=st.booleans(),
    superuser=st.booleans(),
)
def test_a_list_endpoint_never_returns_another_tenants_records(route, role, staff, superuser):
    a, b = two_populated_tenants()
    model = LIST_ENDPOINTS[route]

    requester = user_for(a, role)
    if staff or superuser:
        # 3.1: the filter ignores these flags entirely.
        requester.is_staff = staff
        requester.is_superuser = superuser
        requester.save(update_fields=["is_staff", "is_superuser"])

    client = client_for(a, role)
    response = client.get(url_for(route))

    if role not in ROUTE_ROLES[route]:
        assert response.status_code == 403, response.data
        return

    assert response.status_code == 200, response.data
    rows = result_rows(response)
    returned = {row["id"] for row in rows}

    permitted = expected_visible_ids(a, route, role)
    foreign = set(model.objects.filter(gym=b["gym"]).values_list("pk", flat=True))

    assert returned <= permitted, f"{route} as {role} leaked {returned - permitted}"
    assert not (returned & foreign), f"{route} as {role} returned Gym B rows"
    assert returned == permitted, "the endpoint must still return the tenant's own rows"

    # 3.4: the aggregate count is computed over the filtered set, not the table.
    body = response.json()
    if isinstance(body, dict) and "count" in body:
        assert body["count"] == len(permitted)


@settings(max_examples=100)
@given(role=st.sampled_from(sorted(ROUTE_ROLES["core:member-list"])))
def test_nested_references_in_a_member_row_belong_to_the_requesting_tenant(role):
    """3.4 covers records nested inside a returned representation.

    Only the roles admitted to the member list are drawn; a member's refusal on this
    route is the role test's subject, not this one's.
    """
    a, b = two_populated_tenants()
    response = client_for(a, role).get(url_for("core:member-list"))
    assert response.status_code == 200, response.data

    own_plans = set(MembershipPlan.objects.filter(gym=a["gym"]).values_list("pk", flat=True))
    own_trainers = set(
        TrainerProfile.objects.filter(gym=a["gym"]).values_list("pk", flat=True)
    )
    foreign_plans = set(MembershipPlan.objects.filter(gym=b["gym"]).values_list("pk", flat=True))
    foreign_trainers = set(
        TrainerProfile.objects.filter(gym=b["gym"]).values_list("pk", flat=True)
    )

    for row in result_rows(response):
        if row["plan"] is not None:
            assert row["plan"] in own_plans
            assert row["plan"] not in foreign_plans
        if row["trainer"] is not None:
            assert row["trainer"] in own_trainers
            assert row["trainer"] not in foreign_trainers


@settings(max_examples=100)
@given(role=st.sampled_from(ROLES))
def test_the_gym_and_me_endpoints_resolve_only_the_callers_own_tenant(role):
    a, b = two_populated_tenants()
    client = client_for(a, role)

    gym_response = client.get(url_for("core:gym-detail"))
    assert gym_response.status_code == 200, gym_response.data
    assert gym_response.json()["id"] == a["gym"].pk
    assert gym_response.json()["id"] != b["gym"].pk

    me_response = client.get(url_for("core:me"))
    assert me_response.status_code == 200, me_response.data
    body = me_response.json()
    assert body["gym"]["id"] == a["gym"].pk
    assert body["email"] == user_for(a, role).email


def test_a_member_reads_their_own_gyms_plans_and_the_platform_catalogue():
    """15.9: the two catalogues a member is entitled to, and nothing else."""
    a, b = two_populated_tenants()
    client = client_for(a, "member")

    plans = client.get(url_for("core:membership-plan-list"))
    assert plans.status_code == 200
    returned = {row["id"] for row in result_rows(plans)}
    assert returned == set(
        MembershipPlan.objects.filter(gym=a["gym"]).values_list("pk", flat=True)
    )
    assert not (
        returned
        & set(MembershipPlan.objects.filter(gym=b["gym"]).values_list("pk", flat=True))
    )

    # The SaasPlan catalogue is Platform-owned and identical for every tenant, so it
    # is on the non-tenant allowlist but still requires authentication.
    factories.make_saas_plan(name="Visible Tier", price="1999.00")
    catalogue = client.get(url_for("core:saas-plan-list"))
    assert catalogue.status_code == 200
    assert result_rows(catalogue)

    from core.tests.endpoints import anonymous_client

    assert anonymous_client().get(url_for("core:saas-plan-list")).status_code == 401


def test_invoice_lists_are_payer_scoped_within_the_tenant():
    """15.8: a member sees their own invoices, not the gym's whole ledger."""
    a, _ = two_populated_tenants()

    owner_view = client_for(a, "owner").get(url_for("core:invoice-list"))
    member_view = client_for(a, "member").get(url_for("core:invoice-list"))
    assert owner_view.status_code == 200 and member_view.status_code == 200

    owner_ids = {row["id"] for row in result_rows(owner_view)}
    member_ids = {row["id"] for row in result_rows(member_view)}

    assert member_ids < owner_ids, "the owner sees strictly more than one member"
    member_payer_ids = set(
        Invoice.objects.filter(
            gym=a["gym"], payer_user=a["member"].user, deleted_at__isnull=True
        ).values_list("pk", flat=True)
    )
    assert member_ids == member_payer_ids


@settings(max_examples=100)
@given(staff=st.booleans(), superuser=st.booleans())
def test_the_filtering_component_shares_null_gym_strength_standards_only(staff, superuser):
    """2.2/3.1 at the component boundary, since Phase 1 routes no such endpoint."""
    from rest_framework.test import APIRequestFactory, force_authenticate
    from rest_framework.views import APIView

    from core.permissions import RoleAllowed
    from core.scoping import TenantScopedQuerysetMixin

    a, b = two_populated_tenants()

    # Distinct exercise names per example: the platform-wide key is unique, so
    # reusing one literal across examples would collide rather than test anything.
    shared = factories.make_strength_standard(None)
    mine = factories.make_strength_standard(a["gym"])
    theirs = factories.make_strength_standard(b["gym"])

    class StandardsView(TenantScopedQuerysetMixin, APIView):
        queryset = StrengthStandard.objects.all()
        permission_classes = [RoleAllowed]
        allowed_roles = {"owner", "trainer", "member"}
        gym_nullable_shared = True

        def get(self, request):
            from rest_framework.response import Response

            return Response(list(self.get_queryset().values_list("pk", flat=True)))

    user = user_for(a, "owner")
    user.is_staff = staff
    user.is_superuser = superuser
    user.save(update_fields=["is_staff", "is_superuser"])

    request = APIRequestFactory().get("/standards")
    force_authenticate(request, user=user)
    response = StandardsView.as_view()(request)

    assert response.status_code == 200
    visible = set(response.data)
    assert mine.pk in visible
    assert shared.pk in visible, "a null-gym platform standard is readable by every tenant"
    assert theirs.pk not in visible, "another tenant's override must never be visible"


def test_a_non_shared_model_never_yields_null_gym_rows():
    """The default path has `gym_nullable_shared` false, so null is not a wildcard."""
    from rest_framework.test import APIRequestFactory, force_authenticate
    from rest_framework.views import APIView

    from core.permissions import RoleAllowed
    from core.scoping import TenantScopedQuerysetMixin

    a, b = two_populated_tenants()

    class PlansView(TenantScopedQuerysetMixin, APIView):
        queryset = MembershipPlan.objects.all()
        permission_classes = [RoleAllowed]
        allowed_roles = {"owner"}

        def get(self, request):
            from rest_framework.response import Response

            return Response(list(self.get_queryset().values_list("pk", flat=True)))

    request = APIRequestFactory().get("/plans")
    force_authenticate(request, user=user_for(a, "owner"))
    visible = set(PlansView.as_view()(request).data)

    assert visible == set(
        MembershipPlan.objects.filter(gym=a["gym"]).values_list("pk", flat=True)
    )
    assert not (
        visible & set(MembershipPlan.objects.filter(gym=b["gym"]).values_list("pk", flat=True))
    )
