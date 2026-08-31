"""Feature: gym-saas-core, Property 37."""
import pytest
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.throttling import effective_rate
from gymapp import config
from gymapp.config import THROTTLE_FLOOR
from core.tests.strategies import throttle_rates

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 37: For any configured per-minute request rate, the
# effective rate equals the maximum of the configured value and 5, and for any request
# count exceeding the effective rate against the login, registration, or password-reset
# endpoints, the excess requests are refused with 429.
# Validates: Requirements 24.8, 24.7
@hyp_settings(max_examples=100)
@given(configured=throttle_rates())
def test_effective_rate_is_clamped_to_the_floor(configured):
    assert effective_rate(configured) == max(configured, THROTTLE_FLOOR)
    assert effective_rate(configured) >= THROTTLE_FLOOR


@hyp_settings(max_examples=100)
@given(configured=throttle_rates())
def test_env_rate_string_never_falls_below_the_floor(configured, monkeypatch):
    monkeypatch.setenv("THROTTLE_LOGIN_PER_MINUTE", str(configured))
    rate = config.env_rate("THROTTLE_LOGIN_PER_MINUTE", 10)
    count, window = rate.split("/")
    assert int(count) == max(configured, THROTTLE_FLOOR)
    assert window == "min"


@hyp_settings(max_examples=15, deadline=None)
@given(
    scope=st.sampled_from(["login", "registration", "password_reset"]),
    excess=st.integers(min_value=1, max_value=3),
)
def test_requests_beyond_the_effective_rate_are_refused_with_429(
    scope, excess, api_client, settings, monkeypatch
):
    from django.core.cache import cache

    cache.clear()
    limit = THROTTLE_FLOOR
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            "login": f"{limit}/min",
            "registration": f"{limit}/min",
            "password_reset": f"{limit}/min",
        },
    }
    # SimpleRateThrottle captures the rate mapping as a class attribute at
    # import time.  Patch the three concrete classes used by these views rather
    # than relying on a late global-settings mutation.
    from core.throttling import LoginThrottle, PasswordResetThrottle, RegistrationThrottle

    for throttle in (LoginThrottle, RegistrationThrottle, PasswordResetThrottle):
        monkeypatch.setattr(throttle, "THROTTLE_RATES", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

    url, payload = {
        "login": (reverse("core:login"), {"identifier": "a@b.com", "password": "x"}),
        "registration": (reverse("core:register-owner"), {}),
        "password_reset": (reverse("core:password-reset"), {"email": "a@b.com"}),
    }[scope]

    statuses = [
        api_client.post(url, payload, format="json").status_code
        for _ in range(limit + excess)
    ]

    # The first `limit` requests are answered on their merits; the excess is 429.
    assert statuses[-1] == 429, statuses
    assert statuses.count(429) >= excess
    assert 429 not in statuses[:limit], statuses
