"""Feature: gym-saas-core, Property 40."""
import pytest
from django.core.exceptions import ImproperlyConfigured
from hypothesis import given, settings
from hypothesis import strategies as st

from gymapp import config
from gymapp.config import SMTP_BACKEND
from core.tests.strategies import (
    invalid_hosts,
    smtp_variable_subsets,
    valid_hosts,
)

ALL_SMTP = ("EMAIL_HOST", "EMAIL_PORT", "DEFAULT_FROM_EMAIL")


def _env(monkeypatch, present):
    monkeypatch.setenv("EMAIL_BACKEND", SMTP_BACKEND)
    for name in ALL_SMTP:
        monkeypatch.delenv(name, raising=False)
    for name in present:
        monkeypatch.setenv(name, "1" if name == "EMAIL_PORT" else "value@example.com")


# Feature: gym-saas-core, Property 40: For any subset of EMAIL_HOST, EMAIL_PORT and
# DEFAULT_FROM_EMAIL absent from the environment while DEBUG is false and the SMTP
# backend is selected, startup fails with an error naming exactly the absent variables;
# and for any list of ALLOWED_HOSTS entries while DEBUG is false, startup succeeds if
# and only if every entry is a valid hostname or IP address and none is `*`, with the
# error naming the offending entry.
# Validates: Requirements 8.5, 6.6, 6.7
@given(omitted=smtp_variable_subsets())
@settings(max_examples=100)
def test_missing_smtp_variables_are_all_named_at_once(omitted, monkeypatch):
    present = [name for name in ALL_SMTP if name not in omitted]
    _env(monkeypatch, present)

    if not omitted:
        assert config.email_config(debug=False)["EMAIL_BACKEND"] == SMTP_BACKEND
        return

    with pytest.raises(ImproperlyConfigured) as caught:
        config.email_config(debug=False)

    message = str(caught.value)
    # Exactly the absent ones: named, and none of the present ones named.
    for name in omitted:
        assert name in message, f"{name} missing from {message!r}"
    for name in present:
        assert name not in message, f"{name} wrongly named in {message!r}"


@given(hosts=st.lists(valid_hosts(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_valid_allowed_hosts_start_up(hosts):
    config.validate(
        {
            "DEBUG": False,
            "SECRET_KEY": "a-real-production-key-not-the-dev-one",
            "ALLOWED_HOSTS": hosts,
            "RAZORPAY_KEY_ID": "rzp_live_x",
            "RAZORPAY_KEY_SECRET": "secret",
            "RAZORPAY_WEBHOOK_SECRET": "whsecret",
            "CORS_ALLOWED_ORIGINS": [],
        }
    )


@given(
    good=st.lists(valid_hosts(), max_size=3),
    bad=invalid_hosts(),
)
@settings(max_examples=100)
def test_invalid_allowed_hosts_entry_is_named(good, bad):
    with pytest.raises(ImproperlyConfigured) as caught:
        config.validate(
            {
                "DEBUG": False,
                "SECRET_KEY": "a-real-production-key-not-the-dev-one",
                "ALLOWED_HOSTS": good + [bad],
                "RAZORPAY_KEY_ID": "rzp_live_x",
                "RAZORPAY_KEY_SECRET": "secret",
                "RAZORPAY_WEBHOOK_SECRET": "whsecret",
                "CORS_ALLOWED_ORIGINS": [],
            }
        )
    # The message names the offending entry, or the ALLOWED_HOSTS variable when the
    # entry is the empty string and has nothing quotable.
    assert bad in str(caught.value) or "ALLOWED_HOSTS" in str(caught.value)


@given(tail=st.text(min_size=1, max_size=30))
@settings(max_examples=100)
def test_dev_secret_key_is_refused_in_production(tail):
    with pytest.raises(ImproperlyConfigured) as caught:
        config.validate(
            {
                "DEBUG": False,
                "SECRET_KEY": f"django-insecure-{tail}",
                "ALLOWED_HOSTS": ["example.com"],
            }
        )
    assert "DJANGO_SECRET_KEY" in str(caught.value)
