"""JWT authentication customisations with safe expiry classification."""
from __future__ import annotations

import time

import jwt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings


class DistinguishingJWTAuthentication(JWTAuthentication):
    """Report a correctly signed expired JWT separately from a malformed JWT.

    SimpleJWT intentionally collapses both cases into ``InvalidToken``.  We verify
    the signature again with expiration checking disabled only to classify that
    already-rejected token; a bad signature never receives the expired result.
    """

    def get_validated_token(self, raw_token):
        try:
            return super().get_validated_token(raw_token)
        except InvalidToken as invalid_token:
            try:
                payload = jwt.decode(
                    raw_token,
                    api_settings.SIGNING_KEY,
                    algorithms=[api_settings.ALGORITHM],
                    options={"verify_exp": False},
                    audience=api_settings.AUDIENCE,
                    issuer=api_settings.ISSUER,
                    leeway=api_settings.LEEWAY,
                )
            except jwt.InvalidTokenError:
                # Preserve SimpleJWT's normal 401 InvalidToken response for a
                # malformed or incorrectly signed value.
                raise invalid_token

            expires_at = payload.get("exp")
            if isinstance(expires_at, (int, float)) and expires_at < time.time():
                raise AuthenticationFailed("Token is expired.")
            raise
