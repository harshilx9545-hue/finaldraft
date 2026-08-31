"""Root URL configuration.

The API lives under /api/. The admin is the only surface a platform operator has,
since staff accounts hold no gym profile and are refused by every tenant endpoint.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
