"""Single-execution deployment gates (task 16.5).

Validates: Requirements 7.4, 9.1, 9.3, 9.4, 9.5, 9.6, 18.1, 18.10, 23.1, 23.3,
           24.2, 24.3, 24.4

These do not vary with input, so they are example-based checks rather than
properties. They are the assertions a release must satisfy before it ships, kept in
the test suite so a regression is caught on the commit that causes it rather than at
deploy time.

`check --deploy` is run against a *production-shaped* configuration, not the test
settings: under `DEBUG = True` the deploy checks are largely vacuous, so running
them as-is would prove nothing.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import get_resolver

from core.services.payments import find_card_data_field

BASE_DIR = Path(settings.BASE_DIR)
MIGRATIONS_DIR = BASE_DIR / "core" / "migrations"


# ============ MIGRATIONS (9.1, 9.3, 9.4, 9.5, 9.6) ============

def migration_files():
    return sorted(
        path for path in MIGRATIONS_DIR.glob("*.py") if path.name != "__init__.py"
    )


def test_exactly_one_migration_file_exists():
    """9.1: one clean baseline, not a baseline plus a chain of follow-ups."""
    files = migration_files()
    assert [path.name for path in files] == ["0001_initial.py"], (
        f"expected a single baseline, found {[p.name for p in files]}"
    )
    assert (MIGRATIONS_DIR / "__init__.py").exists(), "the package marker must survive"


def test_the_baseline_declares_every_gym_fk_as_non_nullable_with_no_backfill():
    """9.3: tenancy is in the schema from the start, so no data migration exists."""
    source = (MIGRATIONS_DIR / "0001_initial.py").read_text(encoding="utf-8")

    # Models whose gym FK must be non-nullable.
    for model in ("membershipplan", "equipment", "memberprofile", "trainerprofile"):
        pattern = re.compile(
            r"name=['\"]" + model + r"['\"].*?\)\s*,\s*\n\s*migrations\.",
            re.DOTALL | re.IGNORECASE,
        )
        block = pattern.search(source)
        assert block, f"no CreateModel block found for {model}"
        gym_line = [
            line
            for line in block.group(0).splitlines()
            if "'gym'" in line and "ForeignKey" in line
        ]
        assert gym_line, f"{model} has no gym ForeignKey in the baseline"
        assert "null=True" not in gym_line[0], (
            f"{model}.gym is nullable in the baseline: {gym_line[0].strip()}"
        )

    # No backfill: a data migration would appear as RunPython.
    assert "RunPython" not in source
    assert "RunSQL" not in source


def test_the_baseline_declares_email_as_the_login_identifier():
    """9.4"""
    source = (MIGRATIONS_DIR / "0001_initial.py").read_text(encoding="utf-8")

    assert "('email', models.EmailField(max_length=254, unique=True))" in source
    # username survives as an optional, non-unique column off the login path.
    assert "('username', models.CharField(blank=True, max_length=150, null=True))" in source
    assert "user_email_ci_unique" in source

    from django.contrib.auth import get_user_model

    User = get_user_model()
    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []


@pytest.mark.django_db
def test_no_model_changes_are_pending():
    """9.6: `makemigrations --check --dry-run` reports nothing outstanding.

    Needs database access because the command verifies migration history against
    the recorder table before comparing models.
    """
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


@pytest.mark.django_db
def test_migrate_applies_cleanly(django_db_setup):
    """9.5: the test database itself is built by running the migrations."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert plan == [], f"unapplied migrations remain: {plan}"

    applied = {name for app, name in executor.loader.applied_migrations if app == "core"}
    assert applied == {"0001_initial"}, applied


# ============ CARD DATA SCOPE (23.1, 23.3) ============

def test_no_model_field_could_hold_card_data():
    """23.1: there is no column a PAN, CVV or expiry could be written to."""
    from django.apps import apps

    offenders = []
    for model in apps.get_app_config("core").get_models():
        for field in model._meta.get_fields():
            name = getattr(field, "name", None)
            if name and find_card_data_field({name: ""}) is not None:
                offenders.append(f"{model.__name__}.{name}")
    assert offenders == [], offenders


def test_no_serializer_declares_a_card_data_field():
    """23.3: nor is there a serializer that would accept one."""
    from core import serializers as core_serializers

    offenders = []
    for attribute in dir(core_serializers):
        candidate = getattr(core_serializers, attribute)
        declared = getattr(getattr(candidate, "Meta", None), "fields", None)
        if not isinstance(declared, (list, tuple)):
            continue
        for name in declared:
            if find_card_data_field({name: ""}) is not None:
                offenders.append(f"{attribute}.{name}")
    assert offenders == [], offenders


# ============ ROUTE PRESENCE (24.2, 24.3, 24.4) ============

REQUIRED_ROUTES = {
    # 24.2 - authentication
    "core:register-owner": "/api/auth/register/owner",
    "core:login": "/api/auth/login",
    "core:token-refresh": "/api/auth/refresh",
    "core:logout": "/api/auth/logout",
    "core:verify-email": "/api/auth/verify-email",
    "core:password-reset": "/api/auth/password-reset",
    "core:password-reset-confirm": "/api/auth/password-reset/confirm",
    # 24.3 - identity and catalogue
    "core:me": "/api/me",
    "core:trainer-list": "/api/trainers",
    "core:member-list": "/api/members",
    "core:membership-plan-list": "/api/membership-plans",
    "core:saas-plan-list": "/api/saas-plans",
    # 24.4 - billing
    "core:invoice-list": "/api/invoices",
    "core:razorpay-webhook": "/api/webhooks/razorpay",
}


@pytest.mark.parametrize("name,expected_path", sorted(REQUIRED_ROUTES.items()))
def test_the_phase_one_routes_are_registered_at_the_documented_paths(name, expected_path):
    from django.urls import reverse

    assert reverse(name) == expected_path


def test_the_parameterised_billing_routes_are_registered():
    from django.urls import reverse

    assert reverse("core:invoice-detail", kwargs={"pk": 1}) == "/api/invoices/1"
    assert reverse("core:invoice-pay", kwargs={"pk": 1}) == "/api/invoices/1/pay"
    assert reverse("core:payment-receipt", kwargs={"pk": 1}) == "/api/payments/1/receipt"


# ============ WEBHOOK EXPOSURE (18.1, 18.10) ============

def test_the_webhook_view_is_unauthenticated_and_csrf_exempt():
    """18.1/18.10: the HMAC signature is its only credential."""
    from core.views.webhooks import RazorpayWebhookView

    assert RazorpayWebhookView.authentication_classes == []
    assert RazorpayWebhookView.throttle_classes == []
    assert getattr(RazorpayWebhookView.as_view(), "csrf_exempt", False) is True

    from rest_framework.permissions import AllowAny

    assert RazorpayWebhookView.permission_classes == [AllowAny]

    # And it is registered as one of the nine non-tenant groups, not as an
    # unclassified exception.
    assert RazorpayWebhookView.non_tenant_group == "gateway-webhook"


def test_csrf_middleware_is_installed_so_the_exemption_means_something():
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE


# ============ PRODUCTION CONFIGURATION (7.4) ============

#: A production-shaped environment. Values are placeholders; none is a real secret.
#: The key is long and varied on purpose — Django's own `security.W009` check
#: rejects a short or low-entropy key, and this fixture has to clear the same bar a
#: real deployment does or the gate below would be testing nothing.
PRODUCTION_ENV = {
    "DJANGO_DEBUG": "False",
    "DJANGO_SECRET_KEY": (
        "aB3-dE6_gH9jK2mN5pQ8rS1tU4vW7xY0zA3bC6dE9fG2hJ5kL8mN1pQ4rS7tU0vW"
    ),
    "DJANGO_ALLOWED_HOSTS": "gym.example.com,api.gym.example.com",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.example.com",
    "EMAIL_PORT": "587",
    "DEFAULT_FROM_EMAIL": "no-reply@gym.example.com",
    "CORS_ALLOWED_ORIGINS": "https://gym.example.com",
    "RAZORPAY_KEY_ID": "rzp_live_placeholder",
    "RAZORPAY_KEY_SECRET": "placeholder-key-secret",
    "RAZORPAY_WEBHOOK_SECRET": "placeholder-webhook-secret",
    "DATABASE_URL": "postgres://gym:pw@db.internal:5432/gymapp",
}


def run_management_command(arguments, env_overrides):
    """Run manage.py in a subprocess with a production-shaped environment.

    A subprocess is required rather than `call_command`: the settings under test are
    resolved at import time, and `check --deploy` is only meaningful against a
    process that started with `DEBUG` false.
    """
    import os

    env = {**os.environ, **env_overrides}
    # The loader reads .env with setdefault, so a stale local value must not win.
    env["DJANGO_SETTINGS_MODULE"] = "gymapp.settings"

    return subprocess.run(
        [sys.executable, str(BASE_DIR / "manage.py"), *arguments],
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
        env=env,
        timeout=180,
    )


@pytest.mark.slow
def test_check_deploy_reports_no_issue_against_a_production_configuration():
    """7.4: zero findings at WARNING or above with DEBUG false."""
    result = run_management_command(["check", "--deploy", "--fail-level", "WARNING"], PRODUCTION_ENV)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "System check identified no issues" in combined, combined


@pytest.mark.slow
def test_the_conformance_commands_pass_against_a_production_configuration():
    for command in (["check_tenant_scoping"], ["check_api_surface"]):
        result = run_management_command(command, PRODUCTION_ENV)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.slow
def test_startup_fails_without_a_secret_key():
    """6.3: the process must refuse to start, not start weakened."""
    env = {**PRODUCTION_ENV, "DJANGO_SECRET_KEY": ""}
    result = run_management_command(["check"], env)

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stdout + result.stderr


@pytest.mark.slow
def test_startup_fails_with_a_development_key_in_production():
    """6.7"""
    env = {**PRODUCTION_ENV, "DJANGO_SECRET_KEY": "django-insecure-" + "x" * 30}
    result = run_management_command(["check"], env)

    assert result.returncode != 0
    assert "development key" in (result.stdout + result.stderr) or "django-admin startproject" in (
        result.stdout + result.stderr
    )


@pytest.mark.slow
def test_startup_fails_with_a_wildcard_allowed_host():
    """6.6"""
    env = {**PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": "*"}
    result = run_management_command(["check"], env)

    assert result.returncode != 0
    assert "ALLOWED_HOSTS" in result.stdout + result.stderr


# ============ SECURITY SETTINGS PRESENT (6.9, 6.10, 7.3, 13.3) ============

def test_unconditional_hardening_is_applied():
    """7.3: nosniff and frame denial do not depend on DEBUG."""
    assert settings.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert settings.X_FRAME_OPTIONS == "DENY"


def test_static_and_media_roots_are_defined():
    """6.9"""
    assert settings.STATIC_ROOT
    assert settings.MEDIA_ROOT
    assert settings.MEDIA_URL


def test_logging_routes_the_payment_and_auth_components_to_named_loggers():
    """6.10"""
    loggers = settings.LOGGING["loggers"]
    assert "core.payments" in loggers
    assert "core.auth" in loggers
    assert settings.LOGGING["root"]["level"] == "INFO"
    assert settings.LOGGING["handlers"]["console"]["class"] == "logging.StreamHandler"


def test_jwt_is_configured_for_rotation_and_blacklisting():
    """13.3/13.5/13.6"""
    jwt = settings.SIMPLE_JWT
    assert jwt["ROTATE_REFRESH_TOKENS"] is True
    assert jwt["BLACKLIST_AFTER_ROTATION"] is True
    assert jwt["ACCESS_TOKEN_LIFETIME"].total_seconds() <= 60 * 60
    assert jwt["REFRESH_TOKEN_LIFETIME"].days <= 30
    assert "rest_framework_simplejwt.token_blacklist" in settings.INSTALLED_APPS


def test_cors_is_not_open():
    assert settings.CORS_ALLOW_ALL_ORIGINS is False
    assert settings.CORS_ALLOW_CREDENTIALS is False


def test_the_default_permission_class_is_the_closed_one():
    """15.6: default deny is configured, not just available."""
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "core.permissions.RoleAllowed"
    ]
    assert (
        settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]
        == "core.exceptions.api_exception_handler"
    )


def test_no_secret_key_literal_is_committed():
    """6.2: the tracked tree contains no SECRET_KEY value."""
    offenders = []
    for path in BASE_DIR.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Only a direct assignment counts. A dict entry keyed on the variable name
        # (as the production-shaped fixture below uses) is not a committed setting.
        for match in re.finditer(r"^\s*SECRET_KEY\s*=\s*([\"'])(.+?)\1", text, re.MULTILINE):
            value = match.group(2)
            if len(value) > 20 and "placeholder" not in value:
                offenders.append(f"{path}: {value[:12]}...")
    assert offenders == [], offenders


def test_env_example_covers_every_variable_the_loader_reads():
    """6.11"""
    from gymapp import config

    text = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    missing = [name for name in config.KNOWN_VARIABLES if name not in text]
    assert missing == [], missing


def test_the_django_pin_matches_the_running_major_version():
    """6.13"""
    import django

    requirements = (BASE_DIR / "requirements.txt").read_text(encoding="utf-8")
    pin = re.search(r"^Django>=(\d+)\.(\d+),<(\d+)\.(\d+)", requirements, re.MULTILINE)
    assert pin, "requirements.txt must pin a Django range"

    major, minor = django.VERSION[0], django.VERSION[1]
    low = (int(pin.group(1)), int(pin.group(2)))
    high = (int(pin.group(3)), int(pin.group(4)))
    assert low <= (major, minor) < high, (
        f"running Django {major}.{minor} outside the declared range {pin.group(0)}"
    )


def test_mailers_is_not_a_setting():
    """8.1: the setting Django silently ignored is gone."""
    assert not hasattr(settings, "MAILERS")


def test_default_auto_field_is_bigautofield():
    """7.5"""
    from core.apps import CoreConfig

    assert CoreConfig.default_auto_field == "django.db.models.BigAutoField"


def test_the_resolved_urlconf_exposes_nothing_outside_api_and_admin():
    """The surface is /api/ plus the admin, and nothing else."""
    prefixes = {str(pattern.pattern) for pattern in get_resolver().url_patterns}
    assert prefixes <= {"api/", "admin/"}, prefixes
