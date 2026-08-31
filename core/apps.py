from django.apps import AppConfig


class CoreConfig(AppConfig):
    # Declared on the app rather than relying on the project-level default, so the
    # generated baseline uses BigAutoField even if settings are loaded differently.
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
