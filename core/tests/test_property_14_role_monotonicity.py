"""Feature: gym-saas-core, Property 14.

The claim is a subset claim, so the test is written as one: for every
(route, method, role) combination the response must never be a success unless the
*stored* role permits it, and every refusal must leave the data untouched.

Three escalation vectors are driven separately, because each defeats a different
defence:

* a `role` key in the body — defeated by the serializer denylist;
* a forged access token whose `role` and `gym_id` claims disagree with the database
  — defeated by re-reading role and Gym from the User row every request (13.8);
* `is_staff` / `is_superuser` — deliberately not consulted by the filtering layer,
  so they grant nothing on a tenant endpoint (3.1).

The token forgery is signed with the project's own signing key, so it is a valid
token carrying false claims rather than a malformed one. That is the case that
matters: an invalid signature is refused by authentication and proves nothing about
authorization.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import MembershipPlan, MemberProfile
from core.tests import factories
from core.tests.endpoints import (
    DETAIL_ENDPOINTS,
    ROUTE_ROLES,
    ROUTE_WRITE_ROLES,
    build_billed_tenant,
    client_for,
    own_pk,
    snapshot_tenant_state,
    url_for,
    user_for,
)

pytestmark = pytest.mark.django_db

ROLES = ["owner", "trainer", "member"]
SAFE_METHODS = ["get"]
UNSAFE_METHODS = ["post", "patch", "put", "delete"]
ALL_METHODS = SAFE_METHODS + UNSAFE_METHODS

DENIAL_STATUSES = {401, 403}

#: Every route in the Phase 1 tenant surface, with whether it needs a primary key.
ROUTES = sorted(ROUTE_ROLES)

#: Bodies that try to claim something the caller is not.
ESCALATION_BODIES = [
    {},
    {"role": "owner"},
    {"role": "trainer"},
    {"is_staff": True, "is_superuser": True},
    {"email_verified": True},
    {"status": "active", "is_active_member": True},
]


def permitted(route, role, method):
    """Whether the stored role may reach this route with this method at all."""
    if role not in ROUTE_ROLES[route]:
        return False
    if method in SAFE_METHODS:
        return True
    write_roles = ROUTE_WRITE_ROLES.get(route)
    return bool(write_roles) and role in write_roles


def handles(route, pk, method):
    """Whether the view behind `route` implements a handler for `method`.

    A route with no handler answers 405 regardless of role. That is still a refusal
    — nothing is read or modified — but it is not an authorization decision, so the
    two cases are distinguished rather than lumped together.
    """
    from django.urls import resolve

    match = resolve(url_for(route, pk))
    view = getattr(match.func, "cls", None) or getattr(match.func, "view_class", None)
    assert view is not None, f"could not resolve a view class for {route}"
    allowed = {name.lower() for name in getattr(view, "http_method_names", [])}
    return method in allowed and hasattr(view, method)


def call(client, route, pk, method, body=None):
    url = url_for(route, pk)
    if method == "get":
        return client.get(url)
    if method == "delete":
        return client.delete(url)
    return getattr(client, method)(url, body or {}, format="json")


def forged_client(user, *, role, gym_id):
    """A correctly signed token whose role and gym claims are lies."""
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    access["role"] = role
    access["gym_id"] = gym_id

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


# Feature: gym-saas-core, Property 14: For any User, endpoint, HTTP method, and request
# body - including bodies that name another role, another Gym, another User, or forged
# token claims that disagree with the database - the set of records the request reads or
# modifies is a subset of the set permitted by the role and Gym stored on that User's
# database row.
# Validates: Requirements 15.7, 11.6, 15.2, 15.4, 15.8, 15.11, 13.8, 3.1
@settings(max_examples=100, deadline=None)
@given(
    route=st.sampled_from(ROUTES),
    role=st.sampled_from(ROLES),
    method=st.sampled_from(ALL_METHODS),
    body_index=st.integers(min_value=0, max_value=len(ESCALATION_BODIES) - 1),
)
def test_no_body_grants_more_than_the_stored_role(route, role, method, body_index):
    tenant = build_billed_tenant()
    pk = own_pk(tenant, route) if route in DETAIL_ENDPOINTS else None
    body = ESCALATION_BODIES[body_index]

    before = snapshot_tenant_state()
    response = call(client_for(tenant, role), route, pk, method, body)

    if permitted(route, role, method):
        assert response.status_code not in DENIAL_STATUSES, (
            f"{method.upper()} {route} as {role} was refused although the role "
            f"permits it: {response.status_code}"
        )
    else:
        # The subset claim: nothing succeeded.
        assert not 200 <= response.status_code < 300, (
            f"{method.upper()} {route} as {role} succeeded with "
            f"{response.status_code}; the stored role does not permit it"
        )
        if handles(route, pk, method):
            # The route would have acted, so the refusal must be an authorization
            # decision rather than a missing handler.
            assert response.status_code in DENIAL_STATUSES, (
                f"{method.upper()} {route} as {role} returned {response.status_code}"
            )
            assert response.json()["error"]["code"] in {
                "FORBIDDEN",
                "NOT_AUTHENTICATED",
            }
        else:
            assert response.status_code in DENIAL_STATUSES | {405}
        # A refused request changes nothing.
        assert snapshot_tenant_state() == before

    # Whatever happened, no request may have altered anyone's role or privileges.
    user = user_for(tenant, role)
    user.refresh_from_db()
    assert user.role == role
    assert user.is_staff is False and user.is_superuser is False


@settings(max_examples=100, deadline=None)
@given(
    route=st.sampled_from(ROUTES),
    method=st.sampled_from(ALL_METHODS),
    claimed_role=st.sampled_from(ROLES),
)
def test_forged_token_claims_grant_nothing(route, method, claimed_role):
    """13.8: authorization reads the database row, never the token."""
    tenant = build_billed_tenant()
    other = build_billed_tenant()

    # A member presenting a token that claims to be an owner of another Gym.
    member_user = user_for(tenant, "member")
    client = forged_client(member_user, role=claimed_role, gym_id=other["gym"].pk)

    pk = own_pk(tenant, route) if route in DETAIL_ENDPOINTS else None
    before = snapshot_tenant_state()
    response = call(client, route, pk, method, {})

    # The effective role is `member`, whatever the token says.
    if permitted(route, "member", method):
        assert response.status_code not in DENIAL_STATUSES, response.data
    else:
        assert not 200 <= response.status_code < 300, (
            f"{method.upper()} {route} with a forged {claimed_role} claim succeeded "
            f"with {response.status_code}"
        )
        if handles(route, pk, method):
            assert response.status_code in DENIAL_STATUSES, (
                f"{method.upper()} {route} with a forged {claimed_role} claim "
                f"returned {response.status_code}"
            )
        assert snapshot_tenant_state() == before


def test_a_forged_gym_claim_does_not_move_the_tenant():
    """The forged token must still resolve the Gym from the caller's own profile."""
    tenant = build_billed_tenant()
    other = build_billed_tenant()

    client = forged_client(
        user_for(tenant, "owner"), role="owner", gym_id=other["gym"].pk
    )

    gym_response = client.get(url_for("core:gym-detail"))
    assert gym_response.status_code == 200, gym_response.data
    assert gym_response.json()["id"] == tenant["gym"].pk
    assert gym_response.json()["id"] != other["gym"].pk

    members = client.get(url_for("core:member-list"))
    assert members.status_code == 200
    returned = {row["id"] for row in members.json()["results"]}
    assert other["member"].pk not in returned


def test_a_member_cannot_promote_itself_through_its_own_profile_endpoint():
    """11.6/15.7: role is never a client-supplied value."""
    tenant = build_billed_tenant()
    member_user = user_for(tenant, "member")

    response = client_for(tenant, "member").patch(
        url_for("core:me"),
        {
            "role": "owner",
            "is_staff": True,
            "is_superuser": True,
            "email_verified": True,
            "first_name": "Legitimate",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    member_user.refresh_from_db()
    assert member_user.role == "member"
    assert member_user.is_staff is False
    assert member_user.is_superuser is False
    assert member_user.email_verified is False
    # The one legitimately writable field did change, so the request was processed.
    assert member_user.first_name == "Legitimate"


def test_an_invited_member_is_created_with_the_member_role_whatever_is_asked():
    """11.4/11.6: the endpoint decides the role, not the payload."""
    tenant = build_billed_tenant()

    for claimed in ("owner", "trainer", "member", "superuser", ""):
        response = client_for(tenant, "owner").post(
            url_for("core:member-list"),
            {
                "email": factories.unique_email("roleclaim"),
                "role": claimed,
                "is_staff": True,
                "join_date": str(tenant["gym"].today()),
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        created = MemberProfile.objects.get(pk=response.json()["id"])
        assert created.user.role == "member"
        assert created.user.is_staff is False


def test_an_invited_trainer_is_created_with_the_trainer_role_whatever_is_asked():
    tenant = build_billed_tenant()

    response = client_for(tenant, "owner").post(
        url_for("core:trainer-list"),
        {
            "email": factories.unique_email("trainerclaim"),
            "role": "owner",
            "is_superuser": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    from core.models import TrainerProfile

    created = TrainerProfile.objects.get(pk=response.json()["id"])
    assert created.user.role == "trainer"
    assert created.user.is_superuser is False


def test_self_service_registration_always_produces_an_owner():
    """11.3/11.5: there is no self-service path to a trainer or member account."""
    from core.tests.endpoints import anonymous_client

    factories.make_saas_plan(price="499.00", max_members_allowed=25)

    response = anonymous_client().post(
        url_for("core:register-owner"),
        {
            "email": factories.unique_email("selfreg"),
            "password": factories.DEFAULT_PASSWORD,
            "password_confirm": factories.DEFAULT_PASSWORD,
            "business_name": "Role Claim Gym",
            "contact_phone": factories.unique_phone(),
            "role": "member",
            "is_superuser": True,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.json()["user"]["role"] == "owner"

    from django.contrib.auth import get_user_model

    created = get_user_model().objects.get(pk=response.json()["user"]["id"])
    assert created.role == "owner"
    assert created.is_superuser is False
    assert created.is_staff is False


@settings(max_examples=100, deadline=None)
@given(staff=st.booleans(), superuser=st.booleans(), route=st.sampled_from(ROUTES))
def test_staff_flags_do_not_widen_the_visible_set(staff, superuser, route):
    """3.1: the filter never consults these flags."""
    tenant = build_billed_tenant()
    other = build_billed_tenant()

    user = user_for(tenant, "owner")
    user.is_staff = staff
    user.is_superuser = superuser
    user.save(update_fields=["is_staff", "is_superuser"])

    pk = own_pk(other, route) if route in DETAIL_ENDPOINTS else None
    response = call(client_for(tenant, "owner"), route, pk, "get")

    if pk is not None:
        # Another tenant's id stays invisible however privileged the flags are.
        assert response.status_code in {403, 404, 405}, response.data
    elif response.status_code == 200:
        serialised = response.content.decode()
        assert other["gym"].slug not in serialised


def test_a_member_cannot_write_a_record_that_is_not_member_scoped():
    """15.2: an unsafe method on a non-member-scoped record is 403, not 404."""
    tenant = build_billed_tenant()
    client = client_for(tenant, "member")

    plan_write = client.patch(
        url_for("core:membership-plan-detail", tenant["plan"].pk),
        {"name": "Member Renamed"},
        format="json",
    )
    assert plan_write.status_code == 403, plan_write.data

    gym_write = client.patch(url_for("core:gym-detail"), {"name": "Member Gym"}, format="json")
    assert gym_write.status_code == 403, gym_write.data

    tenant["plan"].refresh_from_db()
    tenant["gym"].refresh_from_db()
    assert tenant["plan"].name != "Member Renamed"
    assert tenant["gym"].name != "Member Gym"


def test_a_member_reading_another_members_records_gets_404_not_403():
    """15.8/15.11: within a tenant, other members' records do not exist."""
    tenant = build_billed_tenant()
    other_member = factories.make_member(tenant["gym"], plan=tenant["plan"])
    other_invoice = factories.make_invoice(
        tenant["gym"], other_member.user, taxable="640.00"
    )
    client = client_for(tenant, "member")

    assert client.get(url_for("core:member-detail", other_member.pk)).status_code == 404
    assert client.get(url_for("core:invoice-detail", other_invoice.pk)).status_code == 404


def test_an_owner_may_write_inside_their_own_gym():
    """15.4, and the control case that makes every 403 above meaningful."""
    tenant = build_billed_tenant()
    client = client_for(tenant, "owner")

    renamed = client.patch(url_for("core:gym-detail"), {"name": "Owner Renamed"}, format="json")
    assert renamed.status_code == 200, renamed.data
    tenant["gym"].refresh_from_db()
    assert tenant["gym"].name == "Owner Renamed"

    plan = client.post(
        url_for("core:membership-plan-list"),
        {"name": "Owner Plan", "price": "1200.00", "duration_days": 60},
        format="json",
    )
    assert plan.status_code == 201, plan.data
    assert MembershipPlan.objects.get(pk=plan.json()["id"]).gym_id == tenant["gym"].pk


def test_renaming_a_gym_leaves_the_owner_business_name_alone():
    """1.6/1.13: the two names are separate values by design."""
    tenant = build_billed_tenant()
    original_business_name = tenant["owner"].business_name

    response = client_for(tenant, "owner").patch(
        url_for("core:gym-detail"), {"name": "Brand New Name"}, format="json"
    )
    assert response.status_code == 200, response.data

    tenant["owner"].refresh_from_db()
    tenant["gym"].refresh_from_db()
    assert tenant["gym"].name == "Brand New Name"
    assert tenant["owner"].business_name == original_business_name
