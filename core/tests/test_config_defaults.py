"""Single-condition configuration and settings-shape checks (task 2.6).

These do not vary with input, so they are examples rather than properties.
Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.9, 6.10, 6.11, 6.13, 7.1, 7.2, 7.3,
8.1, 8.3, 8.4
"""
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from gymapp import config

BASE_DIR = Path(settings.BASE_DIR)


# ============ VALIDATION BEHAVIOUR ============

def test_missing_secret_key_is_an_error_naming_the_variable():
    with pytest.raises(ImproperlyConfigured) as caught:
        config.validate({"DEBUG": True, "SECRET_KEY": "", "ALLOWED_HOSTS": ["x"]})
    assert "DJANGO_SECRET_KEY" in str(caught.value)


def test_debug_defaults_to_false_when_absent(monkeypatch):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    assert config.env_bool("DJANGO_DEBUG", False) is False


def test_empty_allowed_hosts_is_an_error_in_production():
    with pytest.raises(ImproperlyConfigured) as caught:
        config.validate(
            {"DEBUG": False, "SECRET_KEY": "prod-key-value", "ALLOWED_HOSTS": []}
        )
    assert "DJANGO_ALLOWED_HOSTS" in str(caught.value)


def test_console_backend_under_debug(monkeypatch):
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    assert config.email_config(debug=True)["EMAIL_BACKEND"] == config.CONSOLE_BACKEND


def test_missing_email_backend_is_an_error_in_production(monkeypatch):
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    with pytest.raises(ImproperlyConfigured) as caught:
        config.email_config(debug=False)
    assert "EMAIL_BACKEND" in str(caught.value)
    # No silent fallback: the console backend would discard real mail.
    assert config.CONSOLE_BACKEND not in str(caught.value).split("must be set")[0]


def test_wildcard_host_is_never_valid():
    assert config.is_valid_host("*") is False
    assert config.is_valid_host("") is False
    assert config.is_valid_host("example.com") is True
    assert config.is_valid_host("127.0.0.1") is True
    assert config.is_valid_host(".example.com") is True


# ============ SETTINGS SHAPE ============

def test_mailers_block_is_gone():
    """The old MAILERS dict was a hardcoded credential store (8.1)."""
    assert not hasattr(settings, "MAILERS")


def test_no_secret_key_literal_in_tracked_source():
    """6.2: the key is read from the environment, never written in a file."""
    settings_source = (BASE_DIR / "gymapp" / "settings.py").read_text(encoding="utf-8")
    assert "django-insecure-" not in settings_source
    assert re.search(r"^SECRET_KEY\s*=\s*['\"]", settings_source, re.MULTILINE) is None


def test_env_example_covers_every_variable_the_loader_reads():
    """6.11: a variable the loader reads but the example omits is a deploy trap."""
    example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    missing = [name for name in config.KNOWN_VARIABLES if name not in example]
    assert not missing, f".env.example is missing: {missing}"


def test_env_example_contains_no_real_secret():
    example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    assert "rzp_live" not in example
    for line in example.splitlines():
        if line.startswith("DJANGO_SECRET_KEY="):
            assert line.split("=", 1)[1].strip() in {"replace-me", ""}


def test_django_pin_declares_a_range_matching_the_target_major_version():
    """6.13: the declared range and the version the code targets must agree."""
    import django

    requirements = (BASE_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "Django>=5.2,<6.0" in requirements
    assert django.VERSION[0] == 5 and django.VERSION[1] >= 2


def test_unconditional_hardening_is_applied():
    """7.3: nosniff and DENY need no relaxed development variant."""
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert settings.X_FRAME_OPTIONS == "DENY"


def test_production_hardening_block_is_present_in_source():
    """7.1, 7.2: asserted structurally, since the test suite runs with DEBUG on."""
    source = (BASE_DIR / "gymapp" / "settings.py").read_text(encoding="utf-8")
    for setting in (
        "SECURE_SSL_REDIRECT",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SECURE_HSTS_SECONDS = 31536000",
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "SECURE_PROXY_SSL_HEADER",
    ):
        assert setting in source, f"{setting} absent from settings.py"


def test_logging_declares_the_named_loggers():
    """6.10: payment and auth logs are separable from framework noise."""
    loggers = settings.LOGGING["loggers"]
    assert "core.payments" in loggers
    assert "core.auth" in loggers
    assert settings.LOGGING["root"]["level"] == "INFO"


def test_drf_and_jwt_blocks_are_configured():
    """6.9, 13.3, 24.1"""
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "core.permissions.RoleAllowed"
    ]
    assert (
        settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]
        == "core.exceptions.api_exception_handler"
    )
    assert settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"] is True
    assert settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"] is True
    assert settings.AUTH_USER_MODEL == "core.User"


def test_static_and_media_roots_are_declared():
    """6.12 companion: collectstatic and uploads need explicit destinations."""
    assert settings.STATIC_ROOT
    assert settings.MEDIA_ROOT
    assert settings.MEDIA_URL


def test_database_url_selects_the_engine():
    sqlite = config.database_config(None, BASE_DIR)
    assert sqlite["default"]["ENGINE"].endswith("sqlite3")

    postgres = config.database_config(
        "postgres://user:pw@db.example.com:5432/gymapp", BASE_DIR
    )
    assert postgres["default"]["ENGINE"].endswith("postgresql")
    assert postgres["default"]["NAME"] == "gymapp"
    assert postgres["default"]["HOST"] == "db.example.com"


def test_default_auto_field_is_declared_on_the_app():
    """7.5"""
    from core.apps import CoreConfig

    assert CoreConfig.default_auto_field == "django.db.models.BigAutoField"
