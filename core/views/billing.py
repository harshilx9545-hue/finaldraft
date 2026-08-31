"""Invoices, order creation, and receipts.

Invoice visibility is payer-scoped on top of the tenant filter: an owner sees the
Gym's invoices, a member sees only their own. Another member's invoice id returns
404, not 403, so the 404 body is identical to a nonexistent id (15.8).

The pay endpoint is exempt from both the subscription write gate and the inactive
member gate. That exemption is the whole reason those gates are safe: the only write
a lapsed Gym or an inactive member can perform is the one that lets them pay (D5,
20.8, 21.5).
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ErrorCode, Http409
from core.models import Invoice, Payment
from core.permissions import (
    ActiveMemberGate,
    IsAuthenticatedWithProfile,
    RoleAllowed,
    SubscriptionWriteGate,
    TrainerScope,
)
from core.scoping import TenantScopedQuerysetMixin, get_context
from core.serializers import InvoiceSerializer, ReceiptSerializer
from core.services.payments import create_order, order_response
from core.services.subscriptions import ensure_period_invoice

logger = logging.getLogger("core.payments")


class PayerScopedInvoiceQuerysetMixin(TenantScopedQuerysetMixin):
    """Tenant filter, then payer filter. Order matters only for readability."""

    def get_queryset(self):
        queryset = super().get_queryset().filter(deleted_at__isnull=True)
        ctx = get_context(self.request)
        if ctx.role == "owner":
            # The owner is billed for the SaaS subscription and issues the Gym's
            # membership invoices, so they see the whole Gym's set.
            return queryset
        return queryset.filter(payer_user=ctx.user)


class InvoiceListView(PayerScopedInvoiceQuerysetMixin, ListAPIView):
    """GET /api/invoices"""

    queryset = Invoice.objects.select_related("gym", "membership", "saas_subscription")
    serializer_class = InvoiceSerializer
    permission_classes = [RoleAllowed, TrainerScope, SubscriptionWriteGate]
    allowed_roles = {"owner", "trainer", "member"}

    def list(self, request, *args, **kwargs):
        ctx = get_context(request)
        if ctx.role == "owner":
            # Issue the upcoming period's SaaS invoice if the lead window has opened.
            # Done on the read path so Phase 1 needs no scheduler (21.7).
            subscription = getattr(ctx.gym, "subscription", None)
            if subscription is not None:
                ensure_period_invoice(subscription, actor=request.user)
        return super().list(request, *args, **kwargs)


class InvoiceDetailView(PayerScopedInvoiceQuerysetMixin, RetrieveAPIView):
    """GET /api/invoices/{id}"""

    queryset = Invoice.objects.select_related("gym", "membership", "saas_subscription")
    serializer_class = InvoiceSerializer
    permission_classes = [RoleAllowed, TrainerScope, SubscriptionWriteGate]
    allowed_roles = {"owner", "trainer", "member"}


class InvoicePayView(PayerScopedInvoiceQuerysetMixin, APIView):
    """POST /api/invoices/{id}/pay

    Exempt from the subscription and inactive-member write gates by declaration, so
    the exemption is visible here rather than buried in a permission class.
    """

    queryset = Invoice.objects.select_related("gym")
    serializer_class = InvoiceSerializer
    permission_classes = [RoleAllowed, ActiveMemberGate, SubscriptionWriteGate]
    allowed_roles = {"owner", "member"}
    write_roles = {"owner", "member"}
    subscription_exempt = True
    inactive_member_exempt = True

    def get_object(self):
        from django.shortcuts import get_object_or_404

        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def post(self, request, pk):
        invoice = self.get_object()
        result = create_order(invoice, actor=request.user, request_data=request.data)
        return Response(order_response(result["order"]), status=status.HTTP_201_CREATED)


class ReceiptView(TenantScopedQuerysetMixin, APIView):
    """GET /api/payments/{id}/receipt — payer only, once the Payment succeeded (19.9)."""

    queryset = Payment.objects.select_related("invoice", "gym", "invoice__payer_user")
    permission_classes = [RoleAllowed, ActiveMemberGate]
    allowed_roles = {"owner", "member"}
    inactive_member_exempt = True

    def get_queryset(self):
        queryset = super().get_queryset().filter(deleted_at__isnull=True)
        ctx = get_context(self.request)
        # Payer-scoped for everyone, including the owner: a receipt is addressed to
        # whoever paid.
        return queryset.filter(invoice__payer_user=ctx.user)

    def get(self, request, pk):
        from django.shortcuts import get_object_or_404

        payment = get_object_or_404(self.get_queryset(), pk=pk)
        if payment.status != "succeeded":
            raise Http409(
                "A receipt is available once the payment has succeeded.",
                code=ErrorCode.CONFLICT,
                details={"field": "status", "status": payment.status},
            )
        body = ReceiptSerializer(
            {"payment": payment, "invoice": payment.invoice, "gym": payment.gym}
        ).data
        return Response(body, status=status.HTTP_200_OK)


__all__ = [
    "InvoiceListView",
    "InvoiceDetailView",
    "InvoicePayView",
    "ReceiptView",
]
