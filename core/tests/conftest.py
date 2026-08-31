"""Shared fixtures for the `core` test suite.

The gateway hook is the important part: every unit and property test runs against
`FakeRazorpayAdapter`, installed through the same settings key `get_adapter()` reads
in production, so no test in the default run touches the network. Tests that
deliberately talk to the real sandbox are marked `@pytest.mark.integration` and
excluded by `pytest.ini`.

Hypothesis is configured with `suppress_health_check=[function_scoped_fixture]`
because the database-backed properties genuinely do want a fresh transaction per
example, and the deadline is disabled because the first example of a database test
pays for connection setup.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

import pytest
from hypothesis import HealthCheck, settings as hypothesis_settings

#: Settings key the payment layer reads to resolve its gateway adapter.
GATEWAY_ADAPTER_SETTING = "PAYMENT_GATEWAY_ADAPTER"


hypothesis_settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
    ],
)
hypothesis_settings.register_profile(
    "pure",
    max_examples=500,
    deadline=datetime.timedelta(seconds=2),
)
hypothesis_settings.load_profile("default")


@pytest.fixture
def override_settings(settings) -> Callable[..., Any]:
    """Apply one or more Django settings for one test, with automatic restore."""

    def apply(**overrides: Any) -> Any:
        for name, value in overrides.items():
            setattr(settings, name, value)
        return settings

    return apply


@pytest.fixture
def install_gateway_adapter(override_settings) -> Callable[[Any], Any]:
    """Install a payment-gateway adapter for the duration of one test."""

    def install(adapter: Any) -> Any:
        override_settings(**{GATEWAY_ADAPTER_SETTING: adapter})
        return adapter

    return install


@pytest.fixture(autouse=True)
def fake_gateway(settings):
    """Every test gets the fake adapter unless it explicitly installs another.

    Autouse on purpose: a test that forgets to inject the fake would otherwise try
    to reach Razorpay, and the failure would look like a logic bug rather than a
    missing fixture.
    """
    from core.tests.fakes import FAKE_WEBHOOK_SECRET, FakeRazorpayAdapter

    adapter = FakeRazorpayAdapter()
    settings.PAYMENT_GATEWAY_ADAPTER = adapter
    settings.RAZORPAY_WEBHOOK_SECRET = FAKE_WEBHOOK_SECRET
    settings.RAZORPAY_KEY_ID = adapter.public_key
    return adapter


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Throttle counters live in the cache and would leak between tests."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def tenant(db):
    """A whole tenant: Gym, owner, trainer, member, membership plan."""
    from core.tests.factories import make_tenant

    return make_tenant()


@pytest.fixture
def two_tenants(db):
    """Two independent tenants, for every isolation and non-disclosure property."""
    from core.tests.factories import make_tenant

    return {"a": make_tenant(), "b": make_tenant()}


@pytest.fixture
def owner_client(api_client, tenant):
    from core.tests.factories import authenticate

    authenticate(api_client, tenant["owner"].user)
    return api_client


@pytest.fixture
def member_client(api_client, tenant):
    from core.tests.factories import authenticate

    authenticate(api_client, tenant["member"].user)
    return api_client


@pytest.fixture
def trainer_client(api_client, tenant):
    from core.tests.factories import authenticate

    authenticate(api_client, tenant["trainer"].user)
    return api_client
