"""Scoped throttles for the endpoints worth brute-forcing.

Rates are read from the environment by `gymapp.config.env_rate`, which clamps
every configured value to a floor of 5 requests per minute. The floor exists in
one place only: a misconfigured `THROTTLE_LOGIN_PER_MINUTE=0` would otherwise make
the platform unusable and look like an outage rather than a config error (24.8).

Anonymous callers are keyed on IP, authenticated ones on user id, so one abusive
client behind a shared NAT cannot lock out an authenticated user.
"""
from __future__ import annotations

from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from gymapp.config import THROTTLE_FLOOR


class FloorClampedScopedThrottle(ScopedRateThrottle):
    """`ScopedRateThrottle` that re-applies the floor at parse time.

    The rate string usually arrives already clamped from `env_rate`. Re-clamping
    here covers rates set directly in settings by a test or a deployment override,
    so there is no path to an effective rate below the floor.
    """

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num_requests, duration = super().parse_rate(rate)
        if duration is None:
            return (num_requests, duration)
        # Normalise the floor to the window actually configured: 5/min is the
        # stated floor, so a 5-per-60s equivalent is the minimum for any window.
        minimum = max(1, int(THROTTLE_FLOOR * duration / 60)) if duration >= 60 else THROTTLE_FLOOR
        return (max(num_requests, minimum), duration)

    def get_cache_key(self, request, view):
        scope = getattr(view, self.scope_attr, None)
        if not scope:
            return None
        self.scope = scope
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _NamedScopeThrottle(SimpleRateThrottle):
    """Base for the three fixed scopes, keyed on IP for anonymous callers."""

    scope = None

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num_requests, duration = super().parse_rate(rate)
        if duration is None:
            return (num_requests, duration)
        minimum = max(1, int(THROTTLE_FLOOR * duration / 60)) if duration >= 60 else THROTTLE_FLOOR
        return (max(num_requests, minimum), duration)

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginThrottle(_NamedScopeThrottle):
    """Credential stuffing is the threat; the identifier is attacker-controlled."""

    scope = "login"


class RegistrationThrottle(_NamedScopeThrottle):
    """Limits automated tenant creation, which is expensive (Gym + User + profile)."""

    scope = "registration"


class PasswordResetThrottle(_NamedScopeThrottle):
    """Reset always answers 202, so without a throttle it is a free mail cannon."""

    scope = "password_reset"


def effective_rate(configured_per_minute):
    """The rate actually enforced for a configured per-minute value.

    Exposed so Property 37 can assert the clamping rule without reaching into DRF
    internals: `effective_rate(n) == max(n, 5)`.
    """
    return max(int(configured_per_minute), THROTTLE_FLOOR)
