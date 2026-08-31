"""DRF serializers.

Four rules hold throughout, and they are why several of these are plain
`Serializer` rather than `ModelSerializer`:

1. `gym` is never read from the request body. It comes from the resolved
   `RequestContext`, and a client-supplied `gym` key is popped and discarded (2.3).
2. Cross-Gym references are rejected with the *field* named, so a client can fix
   the request rather than guess (2.6, 2.7).
3. `MemberProfile` exposes no settable active or status field — that state is
   derived — while `join_date` is settable, because back-dated onboarding is real
   (20.4, 20.9).
4. No serializer declares a card-data field. There is no code path that could
   accept one (23.3).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.models import (
    Gym,
    Invoice,
    Membership,
    MembershipPlan,
    MemberProfile,
    Payment,
    SaasPlan,
    TrainerProfile,
)
from core.scoping import get_context, resolve_profile
from core.validators import validate_e164, validate_gstin, validate_timezone

User = get_user_model()

#: Popped from every incoming payload before validation. Tenancy and privilege are
#: server-side decisions.
CLIENT_CONTROLLED_DENYLIST = (
    "gym",
    "gym_id",
    "role",
    "is_staff",
    "is_superuser",
    "email_verified",
    "status",
    "is_active_member",
    "active",
)


class TenantScopedSerializerMixin:
    """Injects the context Gym and refuses client-supplied tenancy.

    `to_internal_value` is the interception point rather than `validate`, so the
    denied keys never reach field validation and cannot appear in an error message
    that would confirm they are meaningful.
    """

    def to_internal_value(self, data):
        if isinstance(data, dict):
            data = {
                key: value
                for key, value in data.items()
                if key not in CLIENT_CONTROLLED_DENYLIST
            }
        return super().to_internal_value(data)

    @property
    def tenant_context(self):
        request = self.context.get("request")
        return get_context(request) if request is not None else None

    @property
    def tenant_gym(self):
        ctx = self.tenant_context
        return getattr(ctx, "gym", None)

    def assert_same_gym(self, instance, field_name):
        """Field-named rejection for a reference belonging to another Gym."""
        gym = self.tenant_gym
        if instance is None or gym is None:
            return instance
        if getattr(instance, "gym_id", None) != gym.pk:
            raise serializers.ValidationError(
                {field_name: f"That {field_name} belongs to a different gym."}
            )
        return instance

    def create(self, validated_data):
        validated_data["gym"] = self.tenant_gym
        return super().create(validated_data)


# ============ TENANT ============

class GymSerializer(serializers.ModelSerializer):
    """`slug` and `created_at` are read-only.

    The slug is derived once at registration and appears in every invoice number
    already issued, so changing it would orphan the numbered series. `created_at` is
    never serialised at all (1.1).
    """

    class Meta:
        model = Gym
        fields = [
            "id",
            "name",
            "slug",
            "contact_email",
            "contact_phone",
            "timezone",
            "gstin",
            "is_active",
        ]
        read_only_fields = ["id", "slug", "is_active"]

    def validate_gstin(self, value):
        if value in ("", None):
            return None
        validate_gstin(value)
        return value


# ============ CATALOGUE ============

class SaasPlanSerializer(serializers.ModelSerializer):
    """Platform catalogue. Readable by any authenticated user, tenant or not (15.9)."""

    class Meta:
        model = SaasPlan
        fields = [
            "id",
            "name",
            "price",
            "currency",
            "billing_interval_months",
            "max_members_allowed",
        ]
        read_only_fields = fields


class MembershipPlanSerializer(TenantScopedSerializerMixin, serializers.ModelSerializer):
    """Gym-scoped packages. `max_members_allowed` lives on SaasPlan only (4.3)."""

    class Meta:
        model = MembershipPlan
        fields = [
            "id",
            "name",
            "price",
            "currency",
            "duration_days",
            "includes_trainer",
            "includes_diet",
        ]
        read_only_fields = ["id"]

    def validate_name(self, value):
        """Per-gym, case-insensitive uniqueness, reported against the name field.

        The database constraint is `UniqueConstraint("gym", Lower("name"))`. DRF
        cannot derive a validator from a constraint that contains an expression, so
        without this the duplicate would reach the INSERT and surface as a 500
        instead of the field-named 400 a client can act on (2.4).
        """
        gym = self.tenant_gym
        if gym is None:
            return value

        clash = MembershipPlan.objects.filter(gym=gym, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                "This gym already offers a plan with this name."
            )
        return value


# ============ PROFILES ============

class TrainerProfileSerializer(TenantScopedSerializerMixin, serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = TrainerProfile
        fields = ["id", "email", "full_name", "specialization", "status"]
        read_only_fields = ["id", "email", "full_name"]

    def get_full_name(self, profile):
        return profile.user.get_full_name() or profile.user.email


class TrainerInviteSerializer(serializers.Serializer):
    """Owner-initiated trainer creation. The Gym comes from the owner's context."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(
        max_length=16, required=False, allow_blank=True, validators=[validate_e164]
    )
    specialization = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value.strip())
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate_phone(self, value):
        """Phone is unique platform-wide (10.3), so a clash is a 400 naming phone.

        Without this the duplicate reaches the unique index and surfaces as a 500.
        """
        if not value:
            return None
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )
        return value


class MemberProfileSerializer(TenantScopedSerializerMixin, serializers.ModelSerializer):
    """Read/update view of a member.

    `is_active` and `current_period_end` are read-only computed values. There is
    deliberately no writable status field: active state is derived from membership
    dates and invoice settlement, so a client could only ever set it wrong (20.4).
    """

    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    current_period_end = serializers.SerializerMethodField()

    class Meta:
        model = MemberProfile
        fields = [
            "id",
            "email",
            "full_name",
            "plan",
            "trainer",
            "join_date",
            "goal",
            "photo_url",
            "is_active",
            "current_period_end",
        ]
        read_only_fields = ["id", "email", "full_name", "is_active", "current_period_end"]

    def get_full_name(self, profile):
        return profile.user.get_full_name() or profile.user.email

    def get_is_active(self, profile):
        from core.services.memberships import is_member_active

        return is_member_active(profile)

    def get_current_period_end(self, profile):
        from core.services.memberships import latest_end_date

        return latest_end_date(profile)

    def validate_trainer(self, value):
        return self.assert_same_gym(value, "trainer")

    def validate_plan(self, value):
        return self.assert_same_gym(value, "plan")


class MemberInviteSerializer(MemberProfileSerializer):
    """Owner or trainer creating a member. Routed through the seat service."""

    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(
        max_length=16, required=False, allow_blank=True, validators=[validate_e164]
    )

    class Meta(MemberProfileSerializer.Meta):
        fields = MemberProfileSerializer.Meta.fields + [
            "first_name",
            "last_name",
            "phone",
        ]

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value.strip())
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate_phone(self, value):
        """Same platform-wide uniqueness rule as the trainer invite (10.3)."""
        if not value:
            return None
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )
        return value


class MeSerializer(serializers.Serializer):
    """The caller's identity, role, tenant, and derived membership state (20.10)."""

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True, allow_null=True)
    role = serializers.CharField(read_only=True)
    email_verified = serializers.BooleanField(read_only=True)
    gym = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    is_active_member = serializers.SerializerMethodField()
    current_period_end = serializers.SerializerMethodField()
    member_profile_id = serializers.SerializerMethodField()

    def get_gym(self, user):
        profile = resolve_profile(user)
        return GymSerializer(profile.gym).data if profile else None

    def get_subscription_status(self, user):
        from core.services.subscriptions import effective_status

        profile = resolve_profile(user)
        if profile is None:
            return None
        return effective_status(getattr(profile.gym, "subscription", None))

    def get_is_active_member(self, user):
        from core.services.memberships import is_member_active

        profile = resolve_profile(user)
        if profile is None or user.role != "member":
            return None
        return is_member_active(profile)

    def get_current_period_end(self, user):
        """Latest Membership end date, or null when the member holds none (20.10)."""
        from core.services.memberships import latest_end_date

        profile = resolve_profile(user)
        if profile is None or user.role != "member":
            return None
        return latest_end_date(profile)

    def get_member_profile_id(self, user):
        """The caller's own MemberProfile pk, or null for a non-member role.

        A member needs this identifier to reach `GET /api/members/{id}` for their
        own record. `MemberSelfScope.has_object_permission` already admits that
        request — `_owning_member_id` returns `obj.pk` for a MemberProfile and is
        compared against `ctx.profile.pk` — so only the identifier was missing.
        Nothing else about the request changes: no route, no queryset, no gate.

        Null for owner and trainer, following `get_is_active_member` and
        `get_current_period_end`, because neither role holds a MemberProfile.
        """
        profile = resolve_profile(user)
        if profile is None or user.role != "member":
            return None
        return profile.pk


class MeUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile edits. Role and tenancy are not among them (11.6)."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]

    def validate_phone(self, value):
        if not value:
            return None
        validate_e164(value)
        clash = User.objects.filter(phone=value).exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )
        return value


# ============ REGISTRATION AND AUTH ============

class OwnerRegistrationSerializer(serializers.Serializer):
    """Validates the payload; the service performs the atomic write.

    `role`, `gym`, `is_staff` and `is_superuser` are not declared fields, so DRF
    drops them. Registration always produces an owner (11.3, 12.6).
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(
        max_length=16, required=False, allow_blank=True, validators=[validate_e164]
    )

    business_name = serializers.CharField(max_length=200)
    gym_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=16, validators=[validate_e164])
    timezone_name = serializers.CharField(
        max_length=64, required=False, default="Asia/Kolkata", validators=[validate_timezone]
    )
    gstin = serializers.CharField(
        max_length=15, required=False, allow_blank=True, validators=[validate_gstin]
    )

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value.strip())
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate_phone(self, value):
        if not value:
            return None
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError(
                "An account with this phone number already exists."
            )
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        apply_password_validators(
            attrs["password"],
            email=attrs["email"],
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        return attrs

    def create(self, validated_data):
        from core.services.registration import register_owner

        return register_owner(
            email=validated_data["email"],
            password=validated_data["password"],
            business_name=validated_data["business_name"],
            contact_phone=validated_data["contact_phone"],
            gym_name=validated_data.get("gym_name") or None,
            contact_email=validated_data.get("contact_email") or None,
            timezone_name=validated_data.get("timezone_name") or "Asia/Kolkata",
            gstin=validated_data.get("gstin") or None,
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            phone=validated_data.get("phone") or None,
        )


def apply_password_validators(password, *, email="", first_name="", last_name="", user=None):
    """Run Django's configured validators, reporting against the password field (14.1)."""
    probe = user or User(email=email, first_name=first_name, last_name=last_name)
    try:
        validate_password(password, user=probe)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)}) from exc


class RegistrationResponseSerializer(serializers.Serializer):
    gym = GymSerializer(read_only=True)
    user = serializers.SerializerMethodField()
    tokens = serializers.SerializerMethodField()

    def get_user(self, instance):
        user = instance["user"]
        return {
            "id": user.pk,
            "email": user.email,
            "role": user.role,
            "email_verified": user.email_verified,
        }

    def get_tokens(self, instance):
        from core.services.auth_tokens import issue_tokens

        return issue_tokens(instance["user"])


class LoginSerializer(serializers.Serializer):
    """Email or phone, plus password. Failures are indistinguishable (10.6)."""

    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordResetRequestSerializer(serializers.Serializer):
    """Only an email. The response is always 202, so nothing is disclosed (14.4)."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs


# ============ MEMBERSHIPS ============

class MembershipSerializer(serializers.ModelSerializer):
    """`end_date` is computed on save and never accepted from a client."""

    status = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "plan", "start_date", "end_date", "status"]
        read_only_fields = ["id", "end_date", "status"]

    def get_status(self, membership):
        from core.services.memberships import status_of, today_for

        return status_of(membership, today_for(membership.member.gym))


# ============ BILLING ============

class InvoiceSerializer(serializers.ModelSerializer):
    """Tax fields stay null when the issuer has no GSTIN; null is not zero (19.5)."""

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "financial_year",
            "sequence_no",
            "taxable_value",
            "cgst",
            "sgst",
            "igst",
            "hsn_sac",
            "total_amount",
            "currency",
            "status",
            "issue_date",
            "due_date",
            "membership",
            "saas_subscription",
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    """No `idempotency_key` and no card data: neither belongs in a response (23.3)."""

    class Meta:
        model = Payment
        fields = [
            "id",
            "invoice",
            "amount",
            "currency",
            "status",
            "gateway",
            "gateway_order_ref",
            "gateway_payment_ref",
            "method",
            "paid_at",
            "recorded_on",
            "refund_of",
        ]
        read_only_fields = fields


class ReceiptSerializer(serializers.Serializer):
    """Available to the payer once the Payment reaches `succeeded` (19.9)."""

    payment = PaymentSerializer(read_only=True)
    invoice = InvoiceSerializer(read_only=True)
    gym = GymSerializer(read_only=True)
    issued_to = serializers.SerializerMethodField()

    def get_issued_to(self, instance):
        user = instance["invoice"].payer_user
        return {
            "name": user.get_full_name() or user.email,
            "email": user.email,
        }
