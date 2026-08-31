"""Default-deny for a declaration-less view (task 7.9).

Validates: Requirements 15.6

`RoleAllowed` is the project's DEFAULT_PERMISSION_CLASS and refuses any view that does
not declare `allowed_roles`. This test registers exactly such a view and asserts it is
closed: 401 unauthenticated, 403 authenticated. A new endpoint that forgets its
declaration therefore fails shut rather than open.
"""
import pytest
from django.urls import path
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from core.permissions import RoleAllowed
from core.tests import factories

pytestmark = pytest.mark.django_db


class UndeclaredView(APIView):
    """Deliberately declares no `allowed_roles`. Nothing else is wrong with it."""

    permission_classes = [RoleAllowed]

    def get(self, request):
        return Response({"leaked": True})


urlpatterns = [path("undeclared", UndeclaredView.as_view(), name="undeclared")]


def test_declaration_less_view_denies_anonymous_with_401():
    request = APIRequestFactory().get("/undeclared")
    response = UndeclaredView.as_view()(request)
    assert response.status_code == 401


def test_declaration_less_view_denies_an_authenticated_owner_with_403():
    tenant = factories.make_tenant()
    request = APIRequestFactory().get("/undeclared")
    force_authenticate(request, user=tenant["owner"].user)

    response = UndeclaredView.as_view()(request)
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["owner", "trainer", "member"])
def test_no_role_can_reach_a_declaration_less_view(role):
    tenant = factories.make_tenant()
    user = {"owner": tenant["owner"], "trainer": tenant["trainer"], "member": tenant["member"]}[
        role
    ].user

    request = APIRequestFactory().get("/undeclared")
    force_authenticate(request, user=user)
    assert UndeclaredView.as_view()(request).status_code == 403


def test_declaring_allowed_roles_opens_the_view():
    """The inverse, so the test above is not passing for some unrelated reason."""

    class DeclaredView(UndeclaredView):
        allowed_roles = {"owner"}

    tenant = factories.make_tenant()
    request = APIRequestFactory().get("/declared")
    force_authenticate(request, user=tenant["owner"].user)

    assert DeclaredView.as_view()(request).status_code == 200
