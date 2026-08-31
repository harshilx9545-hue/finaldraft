"""Managers: email-keyed user creation, soft-delete scoping, append-only audit."""
from django.contrib.auth.base_user import BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Creates users keyed on email. `username` is optional and never used to log in."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        email = (email or "").strip()
        if not email:
            raise ValueError("A user must have an email address.")
        email = self.normalize_email(email)
        # Phone is optional.  Treat whitespace-only input as the documented
        # absence of a phone before model validation applies E.164 to concrete
        # values.
        if "phone" in extra_fields:
            extra_fields["phone"] = (extra_fields["phone"] or "").strip() or None
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password", "last_login"])
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        # A platform operator holds no profile and no gym; `role` keeps its model
        # default and is never consulted for staff accounts.
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Case-insensitive login lookup on the email identifier.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager that hides soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Explicit escape hatch for reports that must include deleted rows."""


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise NotImplementedError("Audit records are append-only.")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Audit records are append-only.")


class AppendOnlyManager(models.Manager):
    """Audit records are written once and never changed."""

    def get_queryset(self):
        return AppendOnlyQuerySet(self.model, using=self._db)
