"""Authentication and onboarding. Every view here is on the non-tenant allowlist.

Two response shapes are deliberately contrasting (14.7):

* Password-reset **request** always answers 202 with no body detail, whether or not
  the email exists. Anything else turns the endpoint into an account enumerator.
* Password-reset **confirm** answers an explicit 400 with a machine-readable code
  when the token is expired or already used, because at that point the caller holds
  a token and needs to know to request a new one.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import AuthUnavailable, InvalidCredentials, TokenConsumed
from core.scoping import non_tenant
from core.serializers import (
    EmailVerificationSerializer,
    LoginSerializer,
    LogoutSerializer,
    OwnerRegistrationSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RefreshSerializer,
    RegistrationResponseSerializer,
    apply_password_validators,
)
from core.services import auth_tokens
from core.services import email as email_service
from core.throttling import LoginThrottle, PasswordResetThrottle, RegistrationThrottle

logger = logging.getLogger("core.auth")

User = get_user_model()


class PublicAPIView(APIView):
    """Anonymous by construction: no authenticator, no permission, no tenant."""

    authentication_classes = []
    permission_classes = [AllowAny]


@non_tenant("owner-registration")
class OwnerRegistrationView(PublicAPIView):
    """POST /api/auth/register/owner

    Open to anonymous callers because this is how a tenant comes into existence.
    Throttled on the `registration` scope: creating a Gym, a User and a profile is
    the most expensive anonymous operation the platform offers.
    """

    throttle_classes = [RegistrationThrottle]

    @method_decorator(sensitive_post_parameters("password", "password_confirm"))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        serializer = OwnerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        body = RegistrationResponseSerializer(result).data
        return Response(body, status=status.HTTP_201_CREATED)


@non_tenant("login")
class LoginView(PublicAPIView):
    """POST /api/auth/login — email or phone, plus password."""

    throttle_classes = [LoginThrottle]

    @method_decorator(sensitive_post_parameters("password"))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = auth_tokens.authenticate_identifier(
                serializer.validated_data["identifier"],
                serializer.validated_data["password"],
            )
        except Exception as exc:  # noqa: BLE001
            # An internal failure is 500 AUTH_UNAVAILABLE, deliberately distinct
            # from the 401 for rejected credentials (10.8).
            logger.exception("auth service failure")
            raise AuthUnavailable() from exc

        if user is None:
            # One body for unknown identifier and wrong password alike (10.6).
            raise InvalidCredentials()

        tokens = auth_tokens.issue_tokens(user)
        logger.info("login user_id=%s role=%s", user.pk, user.role)
        return Response(tokens, status=status.HTTP_200_OK)


@non_tenant("token-refresh")
class TokenRefreshView(PublicAPIView):
    """POST /api/auth/refresh — rotates the pair and retires the presented token."""

    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = auth_tokens.rotate_tokens(serializer.validated_data["refresh"])
        return Response(tokens, status=status.HTTP_200_OK)


@non_tenant("logout")
class LogoutView(APIView):
    """POST /api/auth/logout — blacklists the presented refresh token.

    Authenticated on purpose: an unauthenticated logout endpoint lets anyone who
    obtains a refresh token invalidate someone else's session.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        auth_tokens.revoke_refresh(serializer.validated_data["refresh"])
        logger.info("logout user_id=%s", request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


@non_tenant("email-verification")
class EmailVerificationView(PublicAPIView):
    """POST /api/auth/verify-email — consumes a 72-hour single-use token."""

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = auth_tokens.consume_token(
            serializer.validated_data["token"], auth_tokens.PURPOSE_EMAIL
        )
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=["email_verified"])

        return Response({"email_verified": True}, status=status.HTTP_200_OK)


@non_tenant("password-reset-request")
class PasswordResetRequestView(PublicAPIView):
    """POST /api/auth/password-reset — always 202 (14.4).

    The response does not vary with whether the address is registered, so the
    endpoint cannot be used to enumerate accounts.
    """

    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            raw_token = auth_tokens.issue_reset_token(user)
            # Mail failure must not change the response: the helper swallows it (8.6).
            email_service.send_password_reset_email(user, raw_token)

        return Response(
            {
                "detail": (
                    "If an account exists for that address, a reset link has been "
                    "sent."
                )
            },
            status=status.HTTP_202_ACCEPTED,
        )


@non_tenant("password-reset-confirm")
class PasswordResetConfirmView(PublicAPIView):
    """POST /api/auth/password-reset/confirm — explicit 400 on token problems (14.6)."""

    throttle_classes = [PasswordResetThrottle]

    @method_decorator(sensitive_post_parameters("password", "password_confirm"))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            user = auth_tokens.consume_token(
                serializer.validated_data["token"], auth_tokens.PURPOSE_RESET
            )
            apply_password_validators(serializer.validated_data["password"], user=user)
            user.set_password(serializer.validated_data["password"])
            user.save(update_fields=["password"])
            # Whoever held the old credentials is locked out, which an unexpired
            # refresh token would otherwise defeat (14.5).
            auth_tokens.revoke_all_refresh(user)

        logger.info("password reset completed user_id=%s at=%s", user.pk, timezone.now())
        return Response({"detail": "Password updated."}, status=status.HTTP_200_OK)


__all__ = [
    "OwnerRegistrationView",
    "LoginView",
    "TokenRefreshView",
    "LogoutView",
    "EmailVerificationView",
    "PasswordResetRequestView",
    "PasswordResetConfirmView",
    "TokenConsumed",
]
