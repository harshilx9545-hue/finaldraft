"""Tenant resolution and the single queryset-filtering component.

Three cooperating pieces:

* `RequestContext` resolves who is asking and which Gym they belong to, once per
  request, from the database. Permission classes, the queryset mixin and the
  serializers all read the same object, so they cannot disagree about the tenant.
* `TenantScopedQuerysetMixin` is the *only* place a `gym` filter is applied. That
  is deliberate: with FK tenancy, a view that forgets to filter is the entire
  risk, so there is one component to get right and a management command
  (`check_tenant_scoping`) that fails the build when a view skips it.
* `NON_TENANT_VIEWS` is the closed allowlist of endpoints that legitimately
  operate without a tenant.

Because filtering happens in `get_queryset()`, a detail lookup for another Gym's
id raises `Http404` through the ordinary lookup path, producing exactly the body a
nonexistent id produces. Existence is therefore never disclosed.
"""
from __future__ import annotations

from dataclasses import dataclass
from django.db.models import Q

#: Attribute the resolved context is cached on.
CONTEXT_ATTRIBUTE = "tenant_context"

#: Roles that own a profile type. Staff accounts hold none of them (D6).
PROFILE_ATTRIBUTES = {
    "owner": "owner_profile",
    "trainer": "trainer_profile",
    "member": "member_profile",
}

#: Subscription statuses that permit unsafe methods on tenant-scoped endpoints.
WRITE_PERMITTING_STATUSES = frozenset({"trialing", "active"})


# ============ NON-TENANT ALLOWLIST ============

#: Exactly the nine endpoint groups that operate outside a tenant (3.7). Keys are
#: `module.QualName` strings so the conformance command can compare against the
#: view classes it finds by walking the URLconf, without importing view modules
#: in a particular order.
NON_TENANT_VIEWS: set[str] = set()

#: Human-readable names of the nine groups, asserted by the conformance tests so
#: an accidental tenth addition is visible in a diff.
NON_TENANT_GROUPS = (
    "owner-registration",
    "login",
    "token-refresh",
    "logout",
    "email-verification",
    "password-reset-request",
    "password-reset-confirm",
    "saas-plan-catalogue",
    "gateway-webhook",
)


def view_label(view_class):
    return f"{view_class.__module__}.{view_class.__qualname__}"


def non_tenant(group):
    """Class decorator registering a view as intentionally unscoped.

    Takes the group name so the registration states *which* of the nine
    allowlisted groups the view belongs to; an unrecognised group is a mistake and
    fails immediately rather than silently widening the allowlist.
    """

    if group not in NON_TENANT_GROUPS:
        raise ValueError(
            f"{group!r} is not one of the nine allowlisted non-tenant groups: "
            f"{', '.join(NON_TENANT_GROUPS)}"
        )

    def decorate(view_class):
        view_class.non_tenant_group = group
        view_class.is_non_tenant = True
        NON_TENANT_VIEWS.add(view_label(view_class))
        return view_class

    return decorate


def is_non_tenant_view(view_class):
    return view_label(view_class) in NON_TENANT_VIEWS or getattr(
        view_class, "is_non_tenant", False
    )


# ============ REQUEST CONTEXT ============

@dataclass(frozen=True)
class RequestContext:
    """Everything the authorization and filtering layers need, resolved once.

    `role` and `gym` come from the User row and its profile, never from token
    claims, so a role change or a deactivated Gym takes effect on the next request
    rather than at token expiry (13.8, D2).
    """

    user: object | None
    profile: object | None
    gym: object | None
    role: str | None
    subscription_status: str | None
    is_active_member: bool
    is_platform_operator: bool

    @property
    def is_authenticated(self):
        return self.user is not None and getattr(self.user, "is_authenticated", False)

    @property
    def has_profile(self):
        return self.profile is not None

    @property
    def gym_is_active(self):
        return self.gym is not None and bool(self.gym.is_active)

    @property
    def subscription_permits_writes(self):
        return self.subscription_status in WRITE_PERMITTING_STATUSES

    def today(self):
        """Current date in the Gym's timezone, never the server-local date."""
        from django.utils import timezone

        if self.gym is not None:
            return self.gym.today()
        return timezone.now().date()


def resolve_profile(user):
    """The user's single non-soft-deleted profile, or None.

    Checked in role order first so the common case is one attribute access, then
    across all three so a role/profile disagreement still resolves to whatever
    profile actually exists (and is then rejected by the consistency rules).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    ordered = []
    preferred = PROFILE_ATTRIBUTES.get(getattr(user, "role", None))
    if preferred:
        ordered.append(preferred)
    ordered.extend(name for name in PROFILE_ATTRIBUTES.values() if name != preferred)

    for attribute in ordered:
        try:
            profile = getattr(user, attribute, None)
        except Exception:  # RelatedObjectDoesNotExist
            profile = None
        if profile is not None and profile.deleted_at is None:
            return profile
    return None


def build_context(request):
    """Resolve the context from the database. Called once per request."""
    from core.services.memberships import is_member_active

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return RequestContext(
            user=None,
            profile=None,
            gym=None,
            role=None,
            subscription_status=None,
            is_active_member=False,
            is_platform_operator=False,
        )

    profile = resolve_profile(user)
    gym = getattr(profile, "gym", None)
    subscription = getattr(gym, "subscription", None) if gym is not None else None

    is_active_member = False
    if profile is not None and gym is not None and user.role == "member":
        is_active_member = is_member_active(profile, gym.today())

    return RequestContext(
        user=user,
        profile=profile,
        gym=gym,
        role=getattr(user, "role", None),
        subscription_status=getattr(subscription, "status", None),
        is_active_member=is_active_member,
        is_platform_operator=bool(user.is_staff or user.is_superuser),
    )


def get_context(request):
    """Cached accessor. Every layer reads this, so they all see one answer."""
    context = getattr(request, CONTEXT_ATTRIBUTE, None)
    if context is None:
        context = build_context(request)
        setattr(request, CONTEXT_ATTRIBUTE, context)
    return context


# ============ THE FILTERING COMPONENT ============

class TenantScopedQuerysetMixin:
    """The single component that applies the `gym` filter (3.8).

    Set `gym_field` when the FK is not literally named `gym` (for example
    `member__gym`). Set `gym_nullable_shared = True` for models where a null Gym
    means a platform-wide default row visible to every tenant — currently only
    `StrengthStandard` (2.2).

    `is_staff` and `is_superuser` are deliberately not consulted: a staff account
    reaching a tenant endpoint is filtered exactly like anyone else, and in
    practice is refused earlier for holding no profile (3.1).
    """

    #: Lookup path from the model to its Gym.
    gym_field = "gym"
    #: True when a null Gym is a shared default row rather than a data error.
    gym_nullable_shared = False

    def get_tenant_context(self):
        return get_context(self.request)

    def get_tenant_gym(self):
        return self.get_tenant_context().gym

    def get_base_queryset(self):
        """The unfiltered queryset, whatever kind of view this is mixed into.

        DRF's `GenericAPIView` supplies `get_queryset()`; a plain `APIView` does
        not, and two of the billing endpoints are plain `APIView`s that declare a
        `queryset` attribute so they can still be tenant-filtered. Falling back to
        that attribute is what lets the *single* filtering component cover both
        kinds of view, which is the whole point of 3.8 — the alternative is a
        second filtering path for `APIView`, and a second path is exactly the
        thing this component exists to prevent.
        """
        inherited = getattr(super(), "get_queryset", None)
        if callable(inherited):
            return inherited()

        queryset = getattr(self, "queryset", None)
        if queryset is None:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"{type(self).__name__} uses TenantScopedQuerysetMixin but supplies "
                "neither get_queryset() nor a queryset attribute, so there is "
                "nothing to scope."
            )
        return queryset.all()

    def filter_queryset_to_tenant(self, queryset):
        gym = self.get_tenant_gym()
        if gym is None:
            # No tenant resolved. Returning nothing is the safe answer; the
            # permission layer has already refused this request with 403, so this
            # branch only guards against a view that skipped the permission.
            return queryset.none()

        if self.gym_nullable_shared:
            return queryset.filter(
                Q(**{self.gym_field: gym}) | Q(**{f"{self.gym_field}__isnull": True})
            )
        return queryset.filter(**{self.gym_field: gym})

    def get_queryset(self):
        return self.filter_queryset_to_tenant(self.get_base_queryset())
