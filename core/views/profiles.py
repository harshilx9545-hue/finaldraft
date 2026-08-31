"""`/api/me`, and the owner/trainer surfaces for trainers and members.

Member creation goes through `services.seats.create_member_atomically` rather than
the serializer's `create()`. That is not indirection for its own sake: the seat and
subscription checks have to happen under a row lock in the same transaction as the
insert, and a serializer cannot own that boundary.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import MemberProfile, TrainerProfile
from core.permissions import (
    ActiveMemberGate,
    IsAuthenticatedWithProfile,
    MemberSelfScope,
    RequiresSubscription,
    RoleAllowed,
    SubscriptionWriteGate,
    TrainerScope,
)
from core.scoping import TenantScopedQuerysetMixin, get_context
from core.serializers import (
    MemberInviteSerializer,
    MemberProfileSerializer,
    MeSerializer,
    MeUpdateSerializer,
    TrainerInviteSerializer,
    TrainerProfileSerializer,
)
from core.services.registration import generate_temporary_password, invite_trainer
from core.services.seats import create_member_atomically


class MeView(APIView):
    """GET / PATCH /api/me

    Scoped by construction: it reads `request.user` and the Gym reached through that
    user's own profile. There is no id in the path, so there is no cross-tenant
    lookup to get wrong — which is why it needs no queryset mixin.
    """

    # PATCH here is a write to a tenant-scoped endpoint, so it is subject to both
    # write gates: a Gym whose subscription has lapsed is read-only (21.5), and an
    # inactive Member may only issue safe methods and reach their own invoices
    # (20.8). Reads stay open under both, which is what those criteria require.
    permission_classes = [RoleAllowed, SubscriptionWriteGate, ActiveMemberGate]
    allowed_roles = {"owner", "trainer", "member"}
    write_roles = {"owner", "trainer", "member"}
    http_method_names = ["get", "patch", "head", "options"]

    def get(self, request):
        return Response(MeSerializer(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request):
        serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data, status=status.HTTP_200_OK)


class GymDetailView(TenantScopedQuerysetMixin, RetrieveUpdateAPIView):
    """GET / PATCH /api/gym — the caller's own gym, resolved from their profile."""

    from core.serializers import GymSerializer  # local: avoids a circular import

    serializer_class = GymSerializer
    permission_classes = [RoleAllowed, SubscriptionWriteGate]
    allowed_roles = {"owner", "trainer", "member"}
    write_roles = {"owner"}
    owner_only = False
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        from core.models import Gym

        gym = get_context(self.request).gym
        # Filtered to a single row by primary key; the tenant filter is the identity
        # of the row itself here.
        return Gym.objects.filter(pk=getattr(gym, "pk", None))

    def get_object(self):
        return get_context(self.request).gym


class TrainerListCreateView(TenantScopedQuerysetMixin, ListCreateAPIView):
    """GET / POST /api/trainers — owner only.

    Trainers do not consume member seats, so no seat gate applies here; the
    subscription write gate still does.
    """

    # Explicitly ordered: paginating an unordered queryset can repeat or drop a row
    # between pages, which for a list of staff accounts is a correctness bug rather
    # than a cosmetic one.
    queryset = TrainerProfile.objects.select_related("user").order_by("pk")
    serializer_class = TrainerProfileSerializer
    permission_classes = [RoleAllowed, SubscriptionWriteGate]
    allowed_roles = {"owner"}
    write_roles = {"owner"}
    owner_only = True

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TrainerInviteSerializer
        return TrainerProfileSerializer

    def create(self, request, *args, **kwargs):
        serializer = TrainerInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ctx = get_context(request)
        result = invite_trainer(
            gym=ctx.gym,
            actor=request.user,
            **serializer.validated_data,
        )
        body = TrainerProfileSerializer(result["profile"]).data
        return Response(body, status=status.HTTP_201_CREATED)


class MemberListCreateView(TenantScopedQuerysetMixin, ListCreateAPIView):
    """GET / POST /api/members — owner, and trainer for creation (15.10).

    `RequiresSubscription` is listed before the seat check reached inside the
    service so a Gym with no live subscription gets 402, not 409: "you have not
    paid" is more actionable than "you are out of seats".
    """

    # `-join_date` alone is not unique, so a primary-key tiebreaker keeps paging
    # stable when several members joined on the same day.
    queryset = MemberProfile.objects.select_related("user", "plan", "trainer").order_by(
        "-join_date", "pk"
    )
    serializer_class = MemberProfileSerializer
    # `RequiresSubscription` precedes `SubscriptionWriteGate` deliberately. Both
    # refuse a Gym without a trialing or active subscription, but 5.7 names an
    # explicit status for *this* route: creating a member must answer 402
    # SUBSCRIPTION_REQUIRED, not the generic 403 the write gate returns. The
    # specific rule therefore has to be evaluated first; every other write route
    # keeps 21.5's 403.
    permission_classes = [
        RoleAllowed,
        TrainerScope,
        MemberSelfScope,
        RequiresSubscription,
        SubscriptionWriteGate,
        ActiveMemberGate,
    ]
    allowed_roles = {"owner", "trainer"}
    write_roles = {"owner", "trainer"}
    trainer_writable = True

    def get_queryset(self):
        queryset = super().get_queryset()
        ctx = get_context(self.request)
        if ctx.role == "trainer":
            # A trainer sees the members assigned to them and no others (15.3).
            return queryset.filter(trainer=ctx.profile)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = MemberInviteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        ctx = get_context(request)
        trainer = data.get("trainer")
        if ctx.role == "trainer":
            # A trainer may only create members assigned to themselves.
            trainer = ctx.profile

        profile = create_member_atomically(
            ctx.gym,
            email=data["email"],
            password=generate_temporary_password(),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            phone=data.get("phone") or None,
            join_date=data.get("join_date"),
            plan=data.get("plan"),
            trainer=trainer,
            goal=data.get("goal", ""),
            actor=request.user,
        )
        body = MemberProfileSerializer(profile, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED)


class MemberDetailView(TenantScopedQuerysetMixin, RetrieveUpdateAPIView):
    """GET / PATCH /api/members/{id}

    Updates to an existing MemberProfile are never seat-evaluated: they cannot
    increase Seat_Count (D5, 5.8).
    """

    queryset = MemberProfile.objects.select_related("user", "plan", "trainer")
    serializer_class = MemberProfileSerializer
    permission_classes = [
        RoleAllowed,
        TrainerScope,
        MemberSelfScope,
        SubscriptionWriteGate,
        ActiveMemberGate,
    ]
    allowed_roles = {"owner", "trainer", "member"}
    write_roles = {"owner", "trainer"}
    trainer_writable = True
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        ctx = get_context(self.request)
        if ctx.role == "trainer":
            return queryset.filter(trainer=ctx.profile)
        if ctx.role == "member":
            # Another member's id must 404, not 403, so existence stays private (15.8).
            return queryset.filter(pk=getattr(ctx.profile, "pk", None))
        return queryset


__all__ = [
    "MeView",
    "GymDetailView",
    "TrainerListCreateView",
    "MemberListCreateView",
    "MemberDetailView",
]
