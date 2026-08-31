"""One error shape for every non-2xx response.

    {"error": {"code": "SEAT_LIMIT_REACHED", "message": "...", "details": {...}}}

Registered as DRF's `EXCEPTION_HANDLER`, so errors raised inside services get the
same envelope as errors raised by serializers. `details` is present only when a
criterion requires the error to name a field or state numbers; an empty details
dict is omitted rather than serialised as `{}`.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response

logger = logging.getLogger("core.api")


# ============ CODE CATALOGUE ============

class ErrorCode:
    """The complete set of machine-readable codes the API emits."""

    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_CONSUMED = "TOKEN_CONSUMED"
    AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SEAT_LIMIT_REACHED = "SEAT_LIMIT_REACHED"
    PLAN_DOWNGRADE_BLOCKED = "PLAN_DOWNGRADE_BLOCKED"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
    INVOICE_ALREADY_PAID = "INVOICE_ALREADY_PAID"
    INVOICE_IMMUTABLE = "INVOICE_IMMUTABLE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    CARD_DATA_REJECTED = "CARD_DATA_REJECTED"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    RATE_LIMITED = "RATE_LIMITED"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    SERVER_ERROR = "SERVER_ERROR"


#: Every code the catalogue defines, for the conformance test that asserts the
#: handler can never emit a code outside it.
ALL_ERROR_CODES = frozenset(
    value
    for name, value in vars(ErrorCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


# ============ EXCEPTION TYPES ============

class ApiError(drf_exceptions.APIException):
    """Base for platform errors that carry a catalogue code and optional details."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code_name = ErrorCode.VALIDATION_ERROR
    default_detail = "The request could not be completed."

    def __init__(self, detail=None, code=None, details=None):
        super().__init__(detail or self.default_detail)
        self.code_name = code or self.default_code_name
        self.details = details or {}


class Http402(ApiError):
    """Payment required: the Gym has no usable SaasSubscription (5.7)."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code_name = ErrorCode.SUBSCRIPTION_REQUIRED
    default_detail = "An active or trialing subscription is required."


class Http409(ApiError):
    """Conflict: a business rule refuses an otherwise well-formed request."""

    status_code = status.HTTP_409_CONFLICT
    default_code_name = ErrorCode.CONFLICT
    default_detail = "The request conflicts with the current state of the resource."


class SeatLimitReached(Http409):
    default_code_name = ErrorCode.SEAT_LIMIT_REACHED

    def __init__(self, seat_count, limit):
        super().__init__(
            f"Seat count {seat_count} has reached the plan limit of {limit}.",
            details={"seat_count": seat_count, "limit": limit, "field": "member"},
        )


class PlanDowngradeBlocked(Http409):
    default_code_name = ErrorCode.PLAN_DOWNGRADE_BLOCKED

    def __init__(self, seat_count, limit):
        super().__init__(
            f"The requested plan allows {limit} members but the gym currently has "
            f"{seat_count}.",
            details={"seat_count": seat_count, "limit": limit, "field": "plan"},
        )


class InvoiceAlreadyPaid(Http409):
    default_code_name = ErrorCode.INVOICE_ALREADY_PAID
    default_detail = "This invoice already has a succeeded payment."


class InvoiceImmutable(Http409):
    default_code_name = ErrorCode.INVOICE_IMMUTABLE
    default_detail = (
        "A settled invoice cannot be amended. Issue a credit note instead."
    )


class CardDataRejected(ApiError):
    default_code_name = ErrorCode.CARD_DATA_REJECTED
    default_detail = (
        "Card data must never be sent to this platform. Use the gateway's "
        "client-side checkout."
    )


class CurrencyMismatch(ApiError):
    default_code_name = ErrorCode.CURRENCY_MISMATCH
    default_detail = "The invoice currency does not match the gateway account currency."


class SignatureInvalid(ApiError):
    default_code_name = ErrorCode.SIGNATURE_INVALID
    default_detail = "The webhook signature is absent or does not verify."


class TokenConsumed(ApiError):
    default_code_name = ErrorCode.TOKEN_CONSUMED
    default_detail = "This token has expired or has already been used."


class GatewayError(ApiError):
    """The gateway errored or was unreachable (17.6)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code_name = ErrorCode.GATEWAY_ERROR
    default_detail = "The payment gateway could not be reached. No payment was recorded."


class AuthUnavailable(ApiError):
    """Auth service internal failure, distinct from rejected credentials (10.8)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_code_name = ErrorCode.AUTH_UNAVAILABLE
    default_detail = "Authentication is temporarily unavailable. Please retry."


class InvalidCredentials(ApiError):
    """One body for unknown identifier and wrong password alike (10.6)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_code_name = ErrorCode.INVALID_CREDENTIALS
    default_detail = "No active account found with the given credentials."


# ============ MAPPING ============

#: DRF/Django exception class -> catalogue code. Order matters only in that
#: subclasses are looked up before their bases by walking the MRO.
_EXCEPTION_CODES = {
    drf_exceptions.NotAuthenticated: ErrorCode.NOT_AUTHENTICATED,
    drf_exceptions.AuthenticationFailed: ErrorCode.TOKEN_INVALID,
    drf_exceptions.PermissionDenied: ErrorCode.FORBIDDEN,
    drf_exceptions.NotFound: ErrorCode.NOT_FOUND,
    drf_exceptions.MethodNotAllowed: ErrorCode.METHOD_NOT_ALLOWED,
    drf_exceptions.Throttled: ErrorCode.RATE_LIMITED,
    drf_exceptions.ValidationError: ErrorCode.VALIDATION_ERROR,
    drf_exceptions.ParseError: ErrorCode.VALIDATION_ERROR,
    drf_exceptions.UnsupportedMediaType: ErrorCode.VALIDATION_ERROR,
}

#: simplejwt raises AuthenticationFailed for both cases; the difference is in the
#: message, so it is normalised here into the two documented codes (13.4).
_EXPIRED_MARKERS = ("token is expired", "token has expired")


def _code_for(exc):
    if isinstance(exc, ApiError):
        return exc.code_name
    if isinstance(exc, drf_exceptions.AuthenticationFailed):
        text = str(getattr(exc, "detail", "")).lower()
        if any(marker in text for marker in _EXPIRED_MARKERS):
            return ErrorCode.TOKEN_EXPIRED
        return ErrorCode.TOKEN_INVALID
    for klass in type(exc).__mro__:
        if klass in _EXCEPTION_CODES:
            return _EXCEPTION_CODES[klass]
    return ErrorCode.SERVER_ERROR


def _flatten_validation_detail(detail):
    """Turn DRF's nested validation detail into one message plus a field name.

    Property 17 requires a non-empty human-readable message on every error, and
    many criteria require the error to *name* the offending field, so the first
    offending field is lifted into `details.field`.
    """
    field = None
    messages = []

    def walk(node, path):
        nonlocal field
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + [str(key)])
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, path)
        else:
            text = str(node).strip()
            if not text:
                return
            name = next((part for part in path if part not in ("detail", "non_field_errors")), None)
            if field is None and name is not None:
                field = name
            messages.append(f"{name}: {text}" if name else text)

    walk(detail, [])
    message = " ".join(messages) or "The request was not valid."
    return message, field


def _message_for(exc, detail):
    if isinstance(detail, (dict, list)):
        message, _ = _flatten_validation_detail(detail)
        return message
    text = str(detail).strip()
    return text or "The request could not be completed."


def _details_for(exc, detail):
    details = dict(getattr(exc, "details", {}) or {})
    if isinstance(detail, (dict, list)) and "field" not in details:
        _, field = _flatten_validation_detail(detail)
        if field:
            details["field"] = field
    if isinstance(exc, drf_exceptions.Throttled) and exc.wait is not None:
        details.setdefault("retry_after_seconds", int(exc.wait))
    return details


def _envelope(code, message, details):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def api_exception_handler(exc, context):
    """DRF EXCEPTION_HANDLER: normalise everything into the single envelope."""
    from rest_framework.views import exception_handler as drf_exception_handler

    # Translate the Django-level equivalents so services can raise either kind.
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()
    elif isinstance(exc, DjangoValidationError):
        exc = drf_exceptions.ValidationError(
            getattr(exc, "message_dict", None) or list(exc.messages)
        )

    response = drf_exception_handler(exc, context)

    if response is None:
        # Not a DRF exception: let Django's 500 handling take over in production,
        # but still emit the envelope so clients never see two shapes.
        if not isinstance(exc, drf_exceptions.APIException):
            logger.exception("unhandled exception in %s", context.get("view"))
            return Response(
                _envelope(
                    ErrorCode.SERVER_ERROR,
                    "An unexpected error occurred.",
                    {},
                ),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response = Response(status=exc.status_code)

    detail = getattr(exc, "detail", None)
    if detail is None:
        detail = response.data if response.data is not None else str(exc)

    response.data = _envelope(
        _code_for(exc), _message_for(exc, detail), _details_for(exc, detail)
    )
    return response
