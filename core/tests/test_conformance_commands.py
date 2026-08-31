"""Unit tests for the two conformance commands (task 16.4).

Validates: Requirements 3.9, 24.6

A gate that cannot fail is not a gate. Both commands are therefore tested twice:
once against the real URLconf, where they must pass, and once against a URLconf that
deliberately contains the violation they exist to catch, where they must exit
non-zero.

The non-conforming URLconfs are built here rather than added to the project, so the
project's own surface stays clean while the detector is still exercised on a real
resolved URLconf.
"""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import path
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Equipment, MembershipPlan, WorkoutLog
from core.permissions import RoleAllowed
from core.scoping import TenantScopedQuerysetMixin


# ============ NON-CONFORMING VIEWS ============

class UnscopedPlanListView(ListAPIView):
    """Tenant-scoped model, no filtering component. Exactly what 3.9 must catch."""

    queryset = MembershipPlan.objects.all()
    permission_classes = [RoleAllowed]
    allowed_roles = {"owner"}

    def get(self, request, *args, **kwargs):
        return Response([])


class ScopedPlanListView(TenantScopedQuerysetMixin, ListAPIView):
    """The conforming counterpart, so a pass is not a false negative."""

    queryset = MembershipPlan.objects.all()
    permission_classes = [RoleAllowed]
    allowed_roles = {"owner"}

    def get(self, request, *args, **kwargs):
        return Response([])


class WorkoutLogListView(TenantScopedQuerysetMixin, ListAPIView):
    """A deferred-category model behind an innocuous route name (24.6)."""

    queryset = WorkoutLog.objects.all()
    gym_field = "member__gym"
    permission_classes = [RoleAllowed]
    allowed_roles = {"owner"}

    def get(self, request, *args, **kwargs):
        return Response([])


class EquipmentView(TenantScopedQuerysetMixin, APIView):
    queryset = Equipment.objects.all()
    permission_classes = [RoleAllowed]
    allowed_roles = {"owner"}

    def get(self, request):
        return Response([])


# ============ URLCONFS ============

def _core_patterns():
    """The real Phase 1 patterns, so the required-route check still passes."""
    from core import urls as core_urls
    from django.urls import include

    return [path("api/", include((core_urls.urlpatterns, "core"), namespace="core"))]


class ConformingURLConf:
    urlpatterns = _core_patterns()


class UnscopedViewURLConf:
    """Adds a tenant-scoped view that skips the shared filter."""

    urlpatterns = _core_patterns() + [
        path("api/leaky-plans", UnscopedPlanListView.as_view(), name="leaky-plans")
    ]


class ScopedExtraViewURLConf:
    urlpatterns = _core_patterns() + [
        path("api/extra-plans", ScopedPlanListView.as_view(), name="extra-plans")
    ]


class DeferredNameURLConf:
    """A deferred category betrayed by the route name."""

    urlpatterns = _core_patterns() + [
        path("api/workouts", ScopedPlanListView.as_view(), name="workout-list")
    ]


class DeferredModelURLConf:
    """A deferred category betrayed only by the served model, not the name."""

    urlpatterns = _core_patterns() + [
        path("api/history", WorkoutLogListView.as_view(), name="history")
    ]


class DeferredEquipmentURLConf:
    urlpatterns = _core_patterns() + [
        path("api/gear", EquipmentView.as_view(), name="gear")
    ]


class MissingRouteURLConf:
    """Drops the Phase 1 surface entirely."""

    urlpatterns = [path("api/extra", ScopedPlanListView.as_view(), name="extra")]


# ============ check_tenant_scoping ============

@pytest.mark.django_db
def test_check_tenant_scoping_passes_on_the_real_urlconf():
    call_command("check_tenant_scoping")


@pytest.mark.django_db
def test_check_tenant_scoping_passes_with_a_conforming_extra_view():
    with override_settings(ROOT_URLCONF=ScopedExtraViewURLConf):
        call_command("check_tenant_scoping")


@pytest.mark.django_db
def test_check_tenant_scoping_fails_on_a_view_without_the_shared_filter():
    """3.9: the gate must reject exactly this shape."""
    with override_settings(ROOT_URLCONF=UnscopedViewURLConf):
        with pytest.raises(CommandError) as caught:
            call_command("check_tenant_scoping")

    message = str(caught.value)
    assert "tenant-scoping violation" in message


@pytest.mark.django_db
def test_check_tenant_scoping_reports_the_offending_view():
    from core.management.commands.check_tenant_scoping import find_violations

    with override_settings(ROOT_URLCONF=UnscopedViewURLConf):
        violations = find_violations()

    assert len(violations) == 1
    assert "UnscopedPlanListView" in violations[0]
    assert "TenantScopedQuerysetMixin" in violations[0]


@pytest.mark.django_db
def test_check_tenant_scoping_list_mode_classifies_every_route(capsys):
    call_command("check_tenant_scoping", "--list")
    printed = capsys.readouterr().out
    assert "non_tenant" in printed
    assert "tenant_scoped" in printed
    assert "core.views.webhooks.RazorpayWebhookView" in printed


@pytest.mark.django_db
def test_the_non_tenant_decorator_refuses_an_unrecognised_group():
    """The allowlist cannot be widened by inventing a group name (3.7)."""
    from core.scoping import non_tenant

    with pytest.raises(ValueError) as caught:
        non_tenant("some-new-group")
    assert "allowlisted non-tenant groups" in str(caught.value)


# ============ check_api_surface ============

@pytest.mark.django_db
def test_check_api_surface_passes_on_the_real_urlconf():
    call_command("check_api_surface")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "urlconf,expected_fragment",
    [
        (DeferredNameURLConf, "workout"),
        (DeferredModelURLConf, "workoutlog"),
        (DeferredEquipmentURLConf, "equipment"),
    ],
)
def test_check_api_surface_fails_on_a_deferred_category(urlconf, expected_fragment):
    """24.6: caught by name, by path segment, or by the model behind the view."""
    with override_settings(ROOT_URLCONF=urlconf):
        with pytest.raises(CommandError) as caught:
            call_command("check_api_surface")
        assert "API surface violation" in str(caught.value)

        from core.management.commands.check_api_surface import find_violations

        reported = " ".join(find_violations()).lower()
        assert expected_fragment in reported


@pytest.mark.django_db
def test_check_api_surface_fails_when_a_phase_one_route_is_missing():
    with override_settings(ROOT_URLCONF=MissingRouteURLConf):
        with pytest.raises(CommandError):
            call_command("check_api_surface")

        from core.management.commands.check_api_surface import find_violations

        reported = " ".join(find_violations())
        assert "Required Phase 1 routes are not registered" in reported


@pytest.mark.django_db
def test_check_api_surface_ignores_the_admin_routes():
    """The admin legitimately reaches every model; it is not part of the API surface."""
    from core.management.commands.check_api_surface import find_violations

    violations = find_violations()
    assert violations == [], violations
