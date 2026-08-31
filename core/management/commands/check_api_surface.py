"""Deployment gate: the Phase 1 surface must not include deferred categories (24.6).

The models for workout tracking, body metrics, form checks, diet plans, attendance,
equipment and notifications exist, which makes routing them a one-line accident. This
command fails the build when a URL pattern name, path segment, or view queryset model
matches any of those categories.

Checking the view's model as well as the path matters: a route named `/api/logs`
serving `WorkoutLog` would pass a name-only check.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.management.commands.check_tenant_scoping import is_admin_route, iter_view_classes
from core.scoping import view_label

#: Category -> the tokens that betray it in a route name or path segment.
DEFERRED_CATEGORIES = {
    "workout tracking": ("workout", "exercise", "split", "workoutlog", "strength-standard"),
    "body metrics": ("body-metric", "bodymetric", "metrics", "measurement"),
    "form checks": ("form-check", "formcheck"),
    "diet plans": ("diet", "meal", "nutrition"),
    "attendance": ("attendance", "check-in", "checkin", "check-out"),
    "equipment": ("equipment", "machine"),
    "notifications": ("notification", "notify", "push", "sms"),
}

#: Models that must not be reachable through any route.
DEFERRED_MODELS = frozenset(
    {
        "workoutsplit",
        "exercise",
        "workoutlog",
        "bodymetric",
        "formcheck",
        "dietplan",
        "attendance",
        "equipment",
        "notification",
        "strengthstandard",
    }
)

#: Routes the Phase 1 surface must expose (24.2, 24.3, 24.4). Checked by name so a
#: rename is caught rather than silently dropping an endpoint.
REQUIRED_ROUTE_NAMES = frozenset(
    {
        "register-owner",
        "login",
        "token-refresh",
        "logout",
        "verify-email",
        "password-reset",
        "password-reset-confirm",
        "saas-plan-list",
        "membership-plan-list",
        "me",
        "trainer-list",
        "member-list",
        "invoice-list",
        "invoice-detail",
        "invoice-pay",
        "payment-receipt",
        "razorpay-webhook",
    }
)


def _tokens(value):
    return str(value or "").lower().replace("_", "-")


def deferred_match(name, route):
    """(category, token) for the first deferred category the route betrays."""
    haystack = f"{_tokens(name)} {_tokens(route)}"
    for category, tokens in DEFERRED_CATEGORIES.items():
        for token in tokens:
            if token in haystack:
                return category, token
    return None


def model_name_for(view_class):
    queryset = getattr(view_class, "queryset", None)
    model = getattr(queryset, "model", None)
    if model is None:
        serializer = getattr(view_class, "serializer_class", None)
        model = getattr(getattr(serializer, "Meta", None), "model", None)
    return model.__name__.lower() if model is not None else None


def find_violations():
    violations = []
    seen_names = set()

    for name, route, view_class in iter_view_classes():
        if is_admin_route(route):
            continue
        seen_names.add(name)

        match = deferred_match(name, route)
        if match is not None:
            category, token = match
            violations.append(
                f"Route {route!r} (name {name!r}) matches the deferred category "
                f"{category!r} on token {token!r}. Phase 1 exposes no endpoint for it."
            )

        model = model_name_for(view_class)
        if model in DEFERRED_MODELS:
            violations.append(
                f"Route {route!r} serves the deferred model {model!r} through "
                f"{view_label(view_class)}."
            )

    missing = sorted(REQUIRED_ROUTE_NAMES - seen_names)
    if missing:
        violations.append(
            "Required Phase 1 routes are not registered: " + ", ".join(missing) + "."
        )

    return violations


class Command(BaseCommand):
    help = "Fail when the API surface exposes a deferred category or drops a Phase 1 route."

    def handle(self, *args, **options):
        import core.views  # noqa: F401

        violations = find_violations()
        if violations:
            for message in violations:
                self.stderr.write(self.style.ERROR(message))
            raise CommandError(f"{len(violations)} API surface violation(s).")

        self.stdout.write(
            self.style.SUCCESS(
                "API surface conformance: Phase 1 routes present, no deferred "
                "category exposed."
            )
        )
