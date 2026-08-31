"""Authorization. Role and Gym come from the database row, never from the token.

An access token carries `role` and `gym_id` as claims for the client's
convenience, but nothing here reads them: every decision is made from the `User`
row and its profile, re-read each request. A revoked role or a deactivated Gym
therefore takes effect immediately instead of at token expiry (13.8, D2).

Default deny is real, not aspirational: `RoleAllowed` is the project's
`DEFAULT_PERMISSION_CLASS`, and it refuses any view that does not declare
`allowed_roles`. A new view with no declaration is closed (15.6).
"""
from __future__ import annotations

from rest_framework import permissions

from core.exceptions import Http402
from core.scoping import get_context

SAFE_METHODS = permissions.SAFE_METHODS

ALL_ROLES = frozenset({"owner", "trainer", "member"})


def _declared(view, attribute, default=None):
    return getattr(view, attribute, default)


class ContextPermission(permissions.BasePermission):
    """Base: resolves the shared RequestContext and nothing else."""

    def context(self, request):
        return get_context(request)


class IsAuthenticatedWithProfile(ContextPermission):
    """401 when anonymous; 403 when the caller has no usable tenant.

    "No usable tenant" covers three cases that must all look the same to a client:
    no non-soft-deleted profile (which is also how staff accounts are refused),
    and a Gym with `is_active` false (1.7, 3.6, 15.5).
    """

    message = "This account is not attached to an active gym."

    def has_permission(self, request, view):
        ctx = self.context(request)
        if not ctx.is_authenticated:
            # Returning False with no authenticator yields 401 via DRF.
            return False
        if not ctx.has_profile:
            return False
        return ctx.gym_is_active


class RoleAllowed(IsAuthenticatedWithProfile):
    """Declarative role gate, closed by default.

    A view opts in with either:

        allowed_roles = {"owner", "trainer"}          # applies to every method
        write_roles = {"owner"}                        # narrows unsafe methods

    A view that declares neither is denied outright, which is what makes a
    forgotten declaration fail closed rather than open (15.6).
    """

    message = "Your role does not permit this operation."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        allowed = _declared(view, "allowed_roles")
        if allowed is None:
            # No declaration: deny. Deliberately not "allow all".
            return False

        ctx = self.context(request)
        if ctx.role not in set(allowed):
            return False

        if request.method not in SAFE_METHODS:
            write_roles = _declared(view, "write_roles")
            if write_roles is not None and ctx.role not in set(write_roles):
                return False

        return True


class MemberSelfScope(ContextPermission):
    """A member may only reach their own records.

    Reads of another Member's record must 404, not 403, so existence is not
    disclosed (15.8) — that is handled by the queryset filter. This class covers
    the object-level check and refuses writes to anything that is not
    Member-scoped (15.2, 15.11).
    """

    message = "Members may only access their own records."

    def has_permission(self, request, view):
        ctx = self.context(request)
        if ctx.role != "member":
            return True
        if request.method in SAFE_METHODS:
            return True
        # Unsafe methods are allowed only where the view says a member may write.
        return bool(_declared(view, "member_writable", False))

    def has_object_permission(self, request, view, obj):
        ctx = self.context(request)
        if ctx.role != "member":
            return True
        return _owning_member_id(obj) == getattr(ctx.profile, "pk", None)


def _owning_member_id(obj):
    """The MemberProfile id an object belongs to, or None when not member-scoped."""
    from core.models import MemberProfile

    if isinstance(obj, MemberProfile):
        return obj.pk
    for attribute in ("member_id", "member"):
        value = getattr(obj, attribute, None)
        if value is not None:
            return value if isinstance(value, int) else value.pk
    # Invoice / Payment are payer-scoped rather than member-scoped.
    payer = getattr(obj, "payer_user_id", None)
    if payer is not None:
        profile = getattr(getattr(obj, "payer_user", None), "member_profile", None)
        return getattr(profile, "pk", None)
    return None


class TrainerScope(ContextPermission):
    """A trainer sees the members assigned to them, and no one else.

    Writes are limited to creating a MemberProfile in their own Gym and updating
    assigned members. Payment and Invoice writes are refused outright (15.3,
    15.10).
    """

    message = "Trainers may only act on members assigned to them."

    #: Models a trainer may never write, whatever the view declares.
    FORBIDDEN_WRITE_MODELS = frozenset({"payment", "invoice", "creditnote", "saasplan"})

    def has_permission(self, request, view):
        ctx = self.context(request)
        if ctx.role != "trainer":
            return True
        if request.method in SAFE_METHODS:
            return True

        model = _view_model_name(view)
        if model in self.FORBIDDEN_WRITE_MODELS:
            return False
        return bool(_declared(view, "trainer_writable", False))

    def has_object_permission(self, request, view, obj):
        from core.models import MemberProfile

        ctx = self.context(request)
        if ctx.role != "trainer":
            return True

        trainer_id = getattr(ctx.profile, "pk", None)
        if isinstance(obj, MemberProfile):
            return obj.trainer_id == trainer_id
        member_id = _owning_member_id(obj)
        if member_id is None:
            return True
        return MemberProfile.objects.filter(pk=member_id, trainer_id=trainer_id).exists()


def _view_model_name(view):
    model = getattr(getattr(view, "queryset", None), "model", None)
    if model is None:
        serializer = getattr(view, "serializer_class", None)
        model = getattr(getattr(serializer, "Meta", None), "model", None)
    return model.__name__.lower() if model is not None else None


class OwnerScope(ContextPermission):
    """An owner has full reach inside their own Gym, minus declared immutability.

    Cross-Gym reach is prevented by the queryset filter, not here, so this class
    only enforces that the caller is the Gym's owner where a view demands it.
    """

    message = "Only the gym owner may perform this operation."

    def has_permission(self, request, view):
        ctx = self.context(request)
        if not _declared(view, "owner_only", False):
            return True
        return ctx.role == "owner"


class SubscriptionWriteGate(ContextPermission):
    """Unpaid Gyms go read-only, except for paying their own SaaS invoice (D5).

    Resolves the tension between 21.5 and 5.8 in favour of 21.5: reads always
    work, writes require `trialing` or `active`. The exception is narrow and
    declared per view (`subscription_exempt = True`) so the only writable surface
    for a lapsed Gym is the one that lets it pay.
    """

    message = (
        "This gym's subscription is not active. The API is read-only until the "
        "outstanding invoice is settled."
    )

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if _declared(view, "subscription_exempt", False):
            return True

        ctx = self.context(request)
        if ctx.gym is None:
            return True  # IsAuthenticatedWithProfile has already refused this.
        return ctx.subscription_permits_writes


class RequiresSubscription(ContextPermission):
    """402 rather than 403 when an operation needs a live subscription (5.7).

    Distinct from `SubscriptionWriteGate` because the seat-consuming operations
    must answer "payment required", not "forbidden".
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        ctx = self.context(request)
        if ctx.gym is None:
            return True
        if not ctx.subscription_permits_writes:
            raise Http402(
                "This gym has no trialing or active subscription, so members "
                "cannot be added."
            )
        return True


class ActiveMemberGate(ContextPermission):
    """An inactive member may read, and may view and pay their own invoices (20.8)."""

    message = (
        "Your membership is not active. Settle the outstanding invoice to regain "
        "write access."
    )

    def has_permission(self, request, view):
        ctx = self.context(request)
        if ctx.role != "member":
            return True
        if request.method in SAFE_METHODS:
            return True
        if _declared(view, "inactive_member_exempt", False):
            return True
        return ctx.is_active_member


#: Convenience bundle for tenant-scoped views: identity, role, tenant billing
#: state, and membership state, in the order they should be evaluated.
TENANT_PERMISSIONS = [
    RoleAllowed,
    OwnerScope,
    TrainerScope,
    MemberSelfScope,
    SubscriptionWriteGate,
    ActiveMemberGate,
]
