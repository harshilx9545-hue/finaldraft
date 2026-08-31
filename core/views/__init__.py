"""View package.

Importing the submodules here is what populates `NON_TENANT_VIEWS`: the
`@non_tenant(...)` decorators run at import time, and `check_tenant_scoping` needs
the registry filled before it walks the URLconf.
"""
from core.views import auth, billing, catalogue, profiles, webhooks  # noqa: F401

__all__ = ["auth", "billing", "catalogue", "profiles", "webhooks"]
