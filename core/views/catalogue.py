"""Plan catalogues.

`SaasPlan` is Platform-owned and identical for every tenant, so its list endpoint is
on the non-tenant allowlist: filtering it by gym would return nothing. It still
requires authentication — the price list is not public — which is the distinction
requirement 15.9 draws.

`MembershipPlan` is Gym-scoped and goes through the shared filtering mixin like
everything else.
"""
from __future__ import annotations

from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated

from core.models import MembershipPlan, SaasPlan
from core.permissions import RoleAllowed, SubscriptionWriteGate
from core.scoping import TenantScopedQuerysetMixin, non_tenant
from core.serializers import MembershipPlanSerializer, SaasPlanSerializer


@non_tenant("saas-plan-catalogue")
class SaasPlanListView(ListAPIView):
    """GET /api/saas-plans — the Platform tier list, visible to any authenticated user."""

    queryset = SaasPlan.objects.filter(is_active=True).order_by("price")
    serializer_class = SaasPlanSerializer
    permission_classes = [IsAuthenticated]


class MembershipPlanListCreateView(TenantScopedQuerysetMixin, ListCreateAPIView):
    """GET / POST /api/membership-plans — readable by every role, writable by the owner."""

    queryset = MembershipPlan.objects.all().order_by("price")
    serializer_class = MembershipPlanSerializer
    permission_classes = [RoleAllowed, SubscriptionWriteGate]
    allowed_roles = {"owner", "trainer", "member"}
    write_roles = {"owner"}


class MembershipPlanDetailView(TenantScopedQuerysetMixin, RetrieveUpdateAPIView):
    """GET / PATCH /api/membership-plans/{id}"""

    queryset = MembershipPlan.objects.all()
    serializer_class = MembershipPlanSerializer
    permission_classes = [RoleAllowed, SubscriptionWriteGate]
    allowed_roles = {"owner", "trainer", "member"}
    write_roles = {"owner"}
    http_method_names = ["get", "patch", "head", "options"]


__all__ = [
    "SaasPlanListView",
    "MembershipPlanListCreateView",
    "MembershipPlanDetailView",
]
