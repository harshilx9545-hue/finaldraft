"""Admin registration, audited.

Staff accounts are the one identity permitted to reach another Gym's records (3.10),
so every admin write on a tenant-scoped model writes an `AuditRecord` naming the
actor, the record id, the record's Gym, the operation and the timestamp. That is the
compensating control for the access: it is allowed, but never silent.

`AuditRecord` itself is registered read-only. Its manager already refuses `update()`
and `delete()`; the admin registration closes the last UI path to editing it (22.2).
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from core.models import (
    Attendance,
    AuditRecord,
    BodyMetric,
    CreditNote,
    DietPlan,
    EmailVerificationToken,
    Equipment,
    Exercise,
    FormCheck,
    Gym,
    Invoice,
    InvoiceSequence,
    Membership,
    MembershipPlan,
    MemberProfile,
    Notification,
    OwnerProfile,
    PasswordResetToken,
    Payment,
    RecoveryAttempt,
    SaasPlan,
    SaasSubscription,
    StrengthStandard,
    TrainerProfile,
    User,
    WebhookEvent,
    WorkoutLog,
    WorkoutSplit,
)
from core.services.audit import (
    ACTION_ADMIN_WRITE,
    ACTION_CREATE,
    ACTION_SOFT_DELETE,
    diff,
    record,
    snapshot,
)


class AuditedModelAdmin(admin.ModelAdmin):
    """Base for every tenant-scoped model: audits saves and deletes.

    The before-snapshot is taken in `save_model` rather than in a signal so the
    acting user is available. Signals do not know who is asking.
    """

    def save_model(self, request, obj, form, change):
        before = snapshot(obj.__class__.objects.filter(pk=obj.pk).first()) if change and obj.pk else {}
        super().save_model(request, obj, form, change)
        after = snapshot(obj)
        changes = diff(before, after) if change else {
            name: [None, value] for name, value in after.items()
        }
        record(
            ACTION_ADMIN_WRITE if change else ACTION_CREATE,
            obj,
            actor=request.user,
            changes=changes,
        )

    def delete_model(self, request, obj):
        record(
            ACTION_SOFT_DELETE,
            obj,
            actor=request.user,
            changes={"deleted_via": [None, "admin"]},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record(
                ACTION_SOFT_DELETE,
                obj,
                actor=request.user,
                changes={"deleted_via": [None, "admin_bulk"]},
            )
        super().delete_queryset(request, queryset)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Email is the identifier, so the stock username-keyed fieldsets do not fit."""

    ordering = ["email"]
    list_display = ["email", "role", "email_verified", "is_staff", "is_active"]
    list_filter = ["role", "email_verified", "is_staff", "is_active"]
    search_fields = ["email", "phone", "first_name", "last_name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "phone", "username")}),
        ("Role", {"fields": ("role", "email_verified")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),
    )


@admin.register(Gym)
class GymAdmin(AuditedModelAdmin):
    list_display = ["name", "slug", "timezone", "is_active", "created_at"]
    list_filter = ["is_active", "timezone"]
    search_fields = ["name", "slug", "contact_email", "gstin"]
    readonly_fields = ["created_at"]


@admin.register(Invoice)
class InvoiceAdmin(AuditedModelAdmin):
    list_display = ["number", "gym", "payer_user", "total_amount", "currency", "status", "issue_date"]
    list_filter = ["status", "currency", "financial_year"]
    search_fields = ["number", "payer_user__email"]
    # Settled invoices are immutable; the numbering fields never change at all.
    readonly_fields = ["number", "financial_year", "sequence_no"]


@admin.register(Payment)
class PaymentAdmin(AuditedModelAdmin):
    list_display = ["invoice", "amount", "currency", "status", "gateway", "paid_at"]
    list_filter = ["status", "gateway", "currency", "method"]
    search_fields = ["gateway_order_ref", "gateway_payment_ref", "invoice__number"]
    # Never editable: the key is an integrity guard, not data.
    readonly_fields = ["idempotency_key", "created_at"]


@admin.register(AuditRecord)
class AuditRecordAdmin(admin.ModelAdmin):
    """Read-only in every direction. The trail is worthless if it is editable."""

    list_display = ["created_at", "action", "model_label", "object_id", "actor_user", "gym"]
    list_filter = ["action", "model_label"]
    search_fields = ["object_id", "actor_user__email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RecoveryAttempt)
class RecoveryAttemptAdmin(admin.ModelAdmin):
    """Read-only, for the same reason `AuditRecord` is.

    This ledger is what the discount-abuse guard and the stopping rule count, so an
    editable admin form here would not merely spoil an audit trail: it would be a
    supported way to grant a member a second discount or a fourth dunning attempt.
    """

    list_display = [
        "created_at", "gym", "invoice", "tier", "tool_called", "outcome",
        "amount_recovered",
    ]
    list_filter = ["outcome", "tier", "tool_called"]
    search_fields = ["invoice__number", "member__user__email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "kind", "received_at", "processed_at", "reconciliation_required"]
    list_filter = ["kind", "reconciliation_required"]
    search_fields = ["event_id"]
    readonly_fields = ["event_id", "kind", "raw_payload", "received_at"]


@admin.register(EmailVerificationToken)
@admin.register(PasswordResetToken)
class TokenAdmin(admin.ModelAdmin):
    """Hashes only. There is nothing here an operator could misuse."""

    list_display = ["user", "expires_at", "consumed_at", "created_at"]
    readonly_fields = ["token_hash", "created_at"]


# Tenant-scoped models: audited base.
for model in (
    OwnerProfile,
    TrainerProfile,
    MemberProfile,
    MembershipPlan,
    Membership,
    SaasSubscription,
    InvoiceSequence,
    CreditNote,
    Equipment,
    StrengthStandard,
):
    admin.site.register(model, AuditedModelAdmin)

# Platform-owned and member-reachable models with no Gym FK of their own.
for model in (
    SaasPlan,
    Attendance,
    DietPlan,
    WorkoutSplit,
    Exercise,
    WorkoutLog,
    BodyMetric,
    FormCheck,
    Notification,
):
    admin.site.register(model)
