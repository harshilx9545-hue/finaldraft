"""Razorpay webhook.

Unauthenticated and CSRF-exempt by design: the gateway cannot present a JWT or a
CSRF token. Its authentication *is* the HMAC signature, verified over the raw request
body before anything parses it (18.1, 18.2, 18.10).

Status codes are chosen for how Razorpay reacts to them:

* 400 on a bad signature — a forged request, never retried.
* 200 on an unmatched order reference, flagged for reconciliation. An error here
  would make the gateway retry an event this platform can never match (18.7).
* 200 on a replay. The `WebhookEvent.event_id` guard makes it a no-op (18.9).
* 500 on an unexpected processing error, so the gateway *does* retry — safe because
  the `processed_at` guard makes the retry idempotent (18.6).
"""
from __future__ import annotations

import logging

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import SignatureInvalid
from core.scoping import non_tenant
from core.services.gateway import get_adapter
from core.services.payments import WebhookOutcome, process_event

logger = logging.getLogger("core.payments")

#: Razorpay sends the HMAC here.
SIGNATURE_HEADER = "HTTP_X_RAZORPAY_SIGNATURE"


@non_tenant("gateway-webhook")
@method_decorator(csrf_exempt, name="dispatch")
class RazorpayWebhookView(APIView):
    """POST /api/webhooks/razorpay"""

    #: Empty, not "AllowAny with JWT optional": an authenticator that inspects the
    #: Authorization header would give this endpoint a second way in.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        adapter = get_adapter()
        raw_body = request.body
        signature = request.META.get(SIGNATURE_HEADER)

        # Verification first. A parse error before this point would tell an
        # unsigned caller that their body was read at all.
        try:
            payload = adapter.verify_webhook(raw_body, signature)
        except SignatureInvalid:
            logger.warning("webhook signature rejected bytes=%s", len(raw_body or b""))
            raise

        event = adapter.parse_event(payload)
        if not event.event_id:
            # Nothing to deduplicate on; treat as unmatched rather than guessing.
            logger.warning("webhook without event id kind=%s", event.kind)
            return Response(
                {"received": True, "reconciliation_required": True},
                status=status.HTTP_200_OK,
            )

        result = process_event(event, payload)

        return Response(
            {
                "received": True,
                "outcome": result["outcome"],
                "reconciliation_required": result["outcome"] == WebhookOutcome.UNMATCHED,
            },
            status=status.HTTP_200_OK,
        )


__all__ = ["RazorpayWebhookView"]
