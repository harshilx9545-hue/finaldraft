"""Feature: gym-saas-core, Property 38.

The models for workout tracking, body metrics, form checks, diet plans, attendance,
equipment and notifications all exist, which makes routing one of them a one-line
accident. This property walks the resolved URLconf and asserts two things about
*every* pattern: it does not reach a deferred model, and if it is tenant-scoped it
carries the shared filtering component.

The second half is the same check `check_tenant_scoping` performs. Having it here as
well is deliberate: the management command is a deployment gate that someone has to
remember to run, and this test runs on every commit.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.management.commands.check_api_surface import (
    DEFERRED_CATEGORIES,
    DEFERRED_MODELS,
    REQUIRED_ROUTE_NAMES,
    deferred_match,
    model_name_for,
)
from core.management.commands.check_tenant_scoping import (
    classify,
    is_admin_route,
    iter_view_classes,
)
from core.scoping import NON_TENANT_GROUPS, TenantScopedQuerysetMixin, view_label

#: Every non-admin pattern in the resolved URLconf, resolved once.
PATTERNS = [
    (name, route, view_class)
    for name, route, view_class in iter_view_classes()
    if not is_admin_route(route)
]

PATTERN_INDEXES = list(range(len(PATTERNS)))


# Feature: gym-saas-core, Property 38: For any pattern in the resolved URLconf, the
# pattern does not route to a view over WorkoutSplit, Exercise, WorkoutLog, BodyMetric,
# FormCheck, DietPlan, Attendance, Equipment, or Notification, and every pattern
# classified as tenant-scoped has the shared tenant-filtering component in its view's
# MRO.
# Validates: Requirements 24.5, 3.7, 3.8
@settings(max_examples=100)
@given(index=st.sampled_from(PATTERN_INDEXES))
def test_no_pattern_reaches_a_deferred_category_or_skips_the_tenant_filter(index):
    name, route, view_class = PATTERNS[index]

    # 24.5: neither the route name, the path, nor the served model may betray a
    # deferred category.
    assert deferred_match(name, route) is None, (
        f"route {route!r} (name {name!r}) matches a deferred category"
    )
    assert model_name_for(view_class) not in DEFERRED_MODELS, (
        f"route {route!r} serves deferred model {model_name_for(view_class)!r}"
    )

    # 3.7/3.8: anything not on the closed allowlist must filter by gym.
    kind = classify(view_class)
    if kind == "tenant_scoped":
        assert TenantScopedQuerysetMixin in view_class.__mro__, (
            f"{view_label(view_class)} (route {route!r}) is tenant-scoped but does "
            "not use the shared filtering component"
        )


def test_every_phase_one_route_is_registered():
    """24.2/24.3/24.4: the surface is a fixed set, so a dropped route is a failure."""
    registered = {name for name, _route, _view in PATTERNS}
    missing = REQUIRED_ROUTE_NAMES - registered
    assert not missing, f"Phase 1 routes not registered: {sorted(missing)}"


def test_the_non_tenant_allowlist_is_exactly_the_nine_documented_groups():
    """3.7: the allowlist is closed. A tenth group is a design change, not a tweak."""
    registered_groups = {
        getattr(view_class, "non_tenant_group", None) for _name, _route, view_class in PATTERNS
    }
    registered_groups.discard(None)

    assert registered_groups == set(NON_TENANT_GROUPS), (
        f"allowlist drift: {registered_groups ^ set(NON_TENANT_GROUPS)}"
    )
    assert len(NON_TENANT_GROUPS) == 9


@settings(max_examples=100)
@given(category=st.sampled_from(sorted(DEFERRED_CATEGORIES)))
def test_no_route_name_or_path_mentions_a_deferred_category(category):
    """Checked per category so a failure names which one leaked."""
    for name, route, _view in PATTERNS:
        match = deferred_match(name, route)
        assert match is None or match[0] != category, (
            f"route {route!r} exposes deferred category {category!r}"
        )


def test_the_deferred_models_exist_but_are_unreachable():
    """The point of the check: the models are present, so absence is enforced."""
    from django.apps import apps

    served = {model_name_for(view_class) for _name, _route, view_class in PATTERNS}
    declared = {model.__name__.lower() for model in apps.get_app_config("core").get_models()}

    for deferred in DEFERRED_MODELS:
        assert deferred in declared, f"{deferred} should still be a model"
        assert deferred not in served, f"{deferred} is reachable through a route"


def test_no_pattern_is_left_unclassified():
    """Every route is either allowlisted, context-resolved, or tenant-filtered."""
    for name, route, view_class in PATTERNS:
        kind = classify(view_class)
        assert kind in {"non_tenant", "context_resolved", "tenant_scoped"}, (
            f"{route!r} ({name!r}) has no classification"
        )
        if kind == "context_resolved":
            from core.management.commands.check_tenant_scoping import (
                CONTEXT_RESOLVED_VIEWS,
            )

            # A context-resolved exemption must carry a written justification.
            assert CONTEXT_RESOLVED_VIEWS[view_label(view_class)].strip()
