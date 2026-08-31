"""Deployment gate: every tenant-scoped view must carry the shared filter (3.9).

With FK tenancy, a view that forgets to filter by gym is the entire isolation risk.
Code review does not catch it reliably, so this command does: it walks the resolved
URLconf, classifies every view as tenant-scoped unless it is registered in
`NON_TENANT_VIEWS`, and exits non-zero when a tenant-scoped view lacks
`TenantScopedQuerysetMixin` in its MRO.

Run in CI alongside `manage.py check --deploy` and `check_api_surface`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.urls import get_resolver

from core.scoping import (
    NON_TENANT_GROUPS,
    NON_TENANT_VIEWS,
    TenantScopedQuerysetMixin,
    view_label,
)

#: Views that resolve their tenant from the caller's own profile with no id in the
#: path, so there is no queryset over other tenants to filter. Each one must say why.
CONTEXT_RESOLVED_VIEWS = {
    "core.views.profiles.MeView": (
        "reads request.user and that user's own profile; no queryset over any "
        "tenant-scoped model"
    ),
}


def iter_view_classes(resolver=None, prefix=""):
    """Yield (pattern_name, route, view_class) for every resolved pattern."""
    resolver = resolver or get_resolver()

    for pattern in resolver.url_patterns:
        route = prefix + str(getattr(pattern, "pattern", ""))
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            yield from iter_view_classes(pattern, prefix=route)
            continue

        callback = getattr(pattern, "callback", None)
        if callback is None:
            continue
        # DRF's as_view() attaches the class as `cls`; Django's generic views use
        # `view_class`.
        view_class = getattr(callback, "cls", None) or getattr(
            callback, "view_class", None
        )
        if view_class is None:
            continue
        yield (getattr(pattern, "name", None), route, view_class)


def is_admin_route(route):
    return route.startswith("admin/")


def classify(view_class):
    """`non_tenant`, `context_resolved`, or `tenant_scoped`."""
    label = view_label(view_class)
    if label in NON_TENANT_VIEWS or getattr(view_class, "is_non_tenant", False):
        return "non_tenant"
    if label in CONTEXT_RESOLVED_VIEWS:
        return "context_resolved"
    return "tenant_scoped"


def find_violations():
    """Tenant-scoped views missing the shared mixin, as a list of message strings."""
    violations = []
    for name, route, view_class in iter_view_classes():
        if is_admin_route(route):
            continue
        if classify(view_class) != "tenant_scoped":
            continue
        if TenantScopedQuerysetMixin not in view_class.__mro__:
            violations.append(
                f"{view_label(view_class)} (route {route!r}, name {name!r}) is "
                "tenant-scoped but does not have TenantScopedQuerysetMixin in its "
                "MRO."
            )
    return violations


def find_allowlist_drift():
    """The allowlist must stay at exactly the nine documented groups (3.7)."""
    registered_groups = set()
    for _, route, view_class in iter_view_classes():
        if is_admin_route(route):
            continue
        group = getattr(view_class, "non_tenant_group", None)
        if group:
            registered_groups.add(group)

    unexpected = sorted(registered_groups - set(NON_TENANT_GROUPS))
    return unexpected


class Command(BaseCommand):
    help = "Fail when a tenant-scoped view does not use the shared gym filter."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Print the classification of every route instead of only failures.",
        )

    def handle(self, *args, **options):
        # Importing the view package is what runs the @non_tenant decorators.
        import core.views  # noqa: F401

        if options.get("list"):
            for name, route, view_class in sorted(
                iter_view_classes(), key=lambda row: row[1]
            ):
                if is_admin_route(route):
                    continue
                self.stdout.write(
                    f"{classify(view_class):>16}  {route:<40} {view_label(view_class)}"
                )

        violations = find_violations()
        drift = find_allowlist_drift()

        if drift:
            violations.append(
                "Non-tenant allowlist contains unrecognised groups: "
                f"{', '.join(drift)}."
            )

        if violations:
            for message in violations:
                self.stderr.write(self.style.ERROR(message))
            raise CommandError(
                f"{len(violations)} tenant-scoping violation(s). "
                "Every tenant-scoped view must use TenantScopedQuerysetMixin."
            )

        self.stdout.write(
            self.style.SUCCESS("Tenant scoping conformance: every route accounted for.")
        )
