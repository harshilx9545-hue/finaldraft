import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from core.managers import (
    AllObjectsManager,
    AppendOnlyManager,
    SoftDeleteManager,
    UserManager,
)
from core.validators import (
    validate_currency,
    validate_e164,
    validate_gstin,
    validate_gym_slug,
    validate_timezone,
)


# ============ ABSTRACT BASES ============

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Financial and membership rows are never hard-deleted."""
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: Subclasses that must never lose a row set this False. `delete()` then
    #: soft-deletes instead, so there is no hard-delete path at all - not through
    #: the ORM, not through the admin, not through a careless shell session (22.3).
    hard_delete_allowed = True

    #: Subclasses whose soft delete and restore are themselves modifications that
    #: must be attributable set this True (22.1). Set on Payment, Invoice and
    #: Membership. Left False for the profile models, whose soft delete is already
    #: audited by `services.seats`, so that they do not get two records for one act.
    audit_soft_delete = False

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False):
        if self.hard_delete_allowed:
            return super().delete(using=using, keep_parents=keep_parents)
        # Deliberately not an exception: callers (including the admin's delete
        # action) get the intended behaviour rather than a 500.
        self.soft_delete()
        return (0, {})

    def soft_delete(self, save=True, *, actor=None):
        self.deleted_at = timezone.now()
        if save:
            self.save(update_fields=["deleted_at"])
            if self.audit_soft_delete:
                # Local import: core.services.audit imports AuditRecord from this
                # module, so a module-level import here would be circular.
                from core.services.audit import record_soft_delete

                record_soft_delete(self, actor=actor)

    def restore(self, save=True, *, actor=None):
        previous = self.deleted_at
        self.deleted_at = None
        if save:
            self.save(update_fields=["deleted_at"])
            if self.audit_soft_delete:
                from core.services.audit import record_restore

                record_restore(self, previous, actor=actor)


# ============ TENANT ============

class Gym(models.Model):
    """The tenant boundary. Every scoped row carries an FK to exactly one Gym."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60, unique=True, validators=[validate_gym_slug])
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=16, validators=[validate_e164])
    timezone = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
        validators=[validate_timezone],
        help_text="IANA name. All membership date maths is evaluated here, not in server-local time.",
    )
    gstin = models.CharField(
        max_length=15, null=True, blank=True, validators=[validate_gstin]
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)  # immutable, never serialised

    class Meta:
        constraints = [
            # Slug uniqueness is case-insensitive so "IronPit" and "ironpit" collide.
            models.UniqueConstraint(Lower("slug"), name="gym_slug_ci_unique"),
        ]

    def __str__(self):
        return self.name

    @property
    def tzinfo(self):
        return ZoneInfo(self.timezone)

    def today(self):
        """Current date in the gym's own timezone."""
        return timezone.now().astimezone(self.tzinfo).date()


# ============ USERS & ROLES ============

class User(AbstractUser):
    """Email is the login identifier. `username` is retained but optional and unused for auth."""

    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("trainer", "Trainer"),
        ("member", "Member"),
    ]

    # AbstractUser declares username unique; loosen it so email can be the identifier.
    username = models.CharField(max_length=150, blank=True, null=True, unique=False)
    email = models.EmailField(unique=True)
    phone = models.CharField(
        max_length=16, null=True, blank=True, unique=True, validators=[validate_e164]
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]

    def __str__(self):
        return f"{self.email} ({self.role})"

    def clean(self):
        super().clean()
        if not (self.email or "").strip():
            raise ValidationError({"email": "Email is required."})
        self.email = UserManager.normalize_email(self.email.strip())
        # Empty string would collide on the unique index; only NULL may repeat.
        if not self.phone:
            self.phone = None
        if not self.username:
            self.username = None

    @property
    def is_platform_operator(self):
        """Staff accounts hold no profile and no gym; admin is their only surface."""
        return bool(self.is_staff or self.is_superuser)


class OwnerProfile(SoftDeleteModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="owner_profile")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="owner_profiles")
    business_name = models.CharField(max_length=200)  # legal name; not rewritten by a Gym rename
    kyc_document_url = models.URLField(blank=True)  # link to Cloudinary, not the file itself
    kyc_status = models.CharField(
        max_length=15,
        choices=[("pending", "Pending"), ("verified", "Verified"), ("rejected", "Rejected")],
        default="pending",
    )

    def __str__(self):
        return self.business_name


class TrainerProfile(SoftDeleteModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="trainer_profile")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="trainer_profiles")
    specialization = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=10, choices=[("active", "Active"), ("inactive", "Inactive")], default="active"
    )

    def __str__(self):
        return self.user.get_full_name() or self.user.email


class MemberProfile(SoftDeleteModel):
    GOAL_CHOICES = [
        ("strength", "Strength"),
        ("aesthetics", "Aesthetics"),
        ("cut", "Cutting"),
        ("bulk", "Bulking"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="member_profile")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="member_profiles")
    plan = models.ForeignKey(
        "MembershipPlan", on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    trainer = models.ForeignKey(
        TrainerProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_members",
    )
    # Explicit and settable: back-dated joins are a real onboarding case.
    join_date = models.DateField()
    goal = models.CharField(max_length=15, choices=GOAL_CHOICES, blank=True)
    photo_url = models.URLField(blank=True)

    # No stored `status`. Active state is derived from Membership dates + Invoice settlement.

    class Meta:
        ordering = ["-join_date"]

    def __str__(self):
        return self.user.get_full_name() or self.user.email


# ============ PLANS & SUBSCRIPTION (Platform bills the Gym) ============

class SaasPlan(models.Model):
    """Platform-owned tier. Not gym-scoped: every Gym picks from the same catalogue."""

    name = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    currency = models.CharField(max_length=3, default="INR", validators=[validate_currency])
    billing_interval_months = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    max_members_allowed = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(100000)],
        help_text="NULL means unlimited seats.",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SaasSubscription(TimeStampedModel):
    STATUS_CHOICES = [
        ("trialing", "Trialing"),
        ("active", "Active"),
        ("past_due", "Past Due"),
        ("cancelled", "Cancelled"),
    ]

    gym = models.OneToOneField(Gym, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(SaasPlan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="trialing")
    start_date = models.DateField()
    current_period_end = models.DateField()
    gateway_subscription_ref = models.CharField(max_length=120, null=True, blank=True)

    def __str__(self):
        return f"{self.gym} - {self.plan} ({self.status})"

    @property
    def permits_writes(self):
        """Read-only once billing lapses; paying the SaaS invoice is the exception."""
        return self.status in {"trialing", "active"}


# ============ MEMBERSHIP PLANS (Gym bills the Member) ============

class MembershipPlan(models.Model):
    """Gym-scoped package. Seat limits live on SaasPlan, never here."""

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="membership_plans")
    name = models.CharField(max_length=100)
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    currency = models.CharField(max_length=3, default="INR", validators=[validate_currency])
    duration_days = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3650)]
    )
    includes_trainer = models.BooleanField(default=False)
    includes_diet = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "gym", Lower("name"), name="membershipplan_name_ci_unique_per_gym"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.gym})"


class Membership(SoftDeleteModel):
    """One paid period. Status is derived from dates, never stored."""

    hard_delete_allowed = False
    audit_soft_delete = True

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="memberships")
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="memberships")
    start_date = models.DateField()
    end_date = models.DateField(editable=False)  # computed on save, never client-supplied

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="membership_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.member} {self.start_date}..{self.end_date}"

    def save(self, *args, **kwargs):
        # Inclusive period: a 30-day plan starting on the 1st ends on the 30th.
        self.end_date = self.start_date + datetime.timedelta(days=self.plan.duration_days - 1)
        super().save(*args, **kwargs)

    def status_on(self, today):
        if today < self.start_date:
            return "upcoming"
        if today <= self.end_date:
            return "active"
        return "expired"


# ============ INVOICING ============

class InvoiceSequence(models.Model):
    """Lockable counter: makes per-gym, per-financial-year numbering gapless."""

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="invoice_sequences")
    financial_year = models.CharField(max_length=7)  # e.g. "2025-26", April-March
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint("gym", "financial_year", name="invoiceseq_unique_per_gym_fy"),
        ]

    def __str__(self):
        return f"{self.gym.slug}/{self.financial_year} -> {self.next_value}"


class Invoice(SoftDeleteModel):
    """Serves both money flows: Platform to Gym_Owner, and Gym to Member."""

    STATUS_CHOICES = [
        ("open", "Open"),
        ("settled", "Settled"),
        ("void", "Void"),
        ("refunded", "Refunded"),
    ]

    #: Financial fields that are frozen once the invoice is settled (19.7).
    IMMUTABLE_WHEN_SETTLED = ("taxable_value", "cgst", "sgst", "igst", "total_amount", "currency")

    hard_delete_allowed = False
    audit_soft_delete = True

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="invoices")
    payer_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="invoices")

    # Exactly one of these is populated, which is what distinguishes the two flows.
    saas_subscription = models.ForeignKey(
        SaasSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )

    number = models.CharField(max_length=40)          # "{slug}/{fy}/{00001}"
    financial_year = models.CharField(max_length=7)
    sequence_no = models.PositiveIntegerField()

    taxable_value = models.DecimalField(max_digits=12, decimal_places=2)
    cgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    igst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hsn_sac = models.CharField(max_length=8, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR", validators=[validate_currency])

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    issue_date = models.DateField()
    due_date = models.DateField()

    class Meta:
        ordering = ["-issue_date", "-sequence_no"]
        constraints = [
            models.UniqueConstraint(
                "gym", "financial_year", "sequence_no", name="invoice_seq_unique_per_gym_fy"
            ),
            models.UniqueConstraint("gym", "number", name="invoice_number_unique_per_gym"),
            models.CheckConstraint(
                condition=Q(saas_subscription__isnull=False, membership__isnull=True)
                | Q(saas_subscription__isnull=True, membership__isnull=False),
                name="invoice_exactly_one_subject",
            ),
        ]

    def __str__(self):
        return f"{self.number} ({self.status})"

    def clean(self):
        """Refuse a financial-field change on a settled invoice.

        Enforced at the model layer as well as in the service so the admin and any
        future code path inherit the rule. The service raises the 409 the API
        contract requires; this raises the ValidationError the ORM understands.
        """
        super().clean()
        if self.pk is None:
            return

        previous = (
            type(self)
            .all_objects.filter(pk=self.pk)
            .values("status", *self.IMMUTABLE_WHEN_SETTLED)
            .first()
        )
        if not previous or previous["status"] != "settled":
            return

        changed = [
            name
            for name in self.IMMUTABLE_WHEN_SETTLED
            if previous[name] != getattr(self, name)
        ]
        if changed:
            raise ValidationError(
                {
                    name: (
                        "A settled invoice cannot be amended. Issue a credit note "
                        "instead."
                    )
                    for name in changed
                }
            )

    @property
    def tax_total(self):
        return sum(
            (component for component in (self.cgst, self.sgst, self.igst) if component is not None),
            Decimal("0.00"),
        )


class CreditNote(models.Model):
    """A settled invoice is never edited; corrections are issued as credit notes."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    number = models.CharField(max_length=40, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    issue_date = models.DateField()

    def __str__(self):
        return f"{self.number} against {self.invoice.number}"


# ============ PAYMENTS ============

class Payment(SoftDeleteModel):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
        ("cancelled", "Cancelled"),
    ]
    METHOD_CHOICES = [("upi", "UPI"), ("card", "Card"), ("netbanking", "Netbanking")]

    hard_delete_allowed = False
    audit_soft_delete = True

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="payments")

    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    currency = models.CharField(max_length=3, default="INR", validators=[validate_currency])
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")

    gateway = models.CharField(max_length=20, default="razorpay")
    gateway_order_ref = models.CharField(max_length=120, null=True, blank=True)
    gateway_payment_ref = models.CharField(max_length=120, null=True, blank=True)
    # Guards a repeat of the same logical operation; WebhookEvent guards gateway retries.
    idempotency_key = models.CharField(max_length=64, unique=True)

    method = models.CharField(max_length=12, choices=METHOD_CHOICES, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    recorded_on = models.DateField()  # explicit, so reconciliations can back-date
    created_at = models.DateTimeField(auto_now_add=True)
    refund_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=Decimal("0.01")), name="payment_amount_positive"
            ),
            models.UniqueConstraint(
                "gateway_payment_ref",
                condition=Q(gateway_payment_ref__isnull=False),
                name="payment_gateway_ref_unique_when_present",
            ),
        ]

    def __str__(self):
        return f"{self.invoice.number} - {self.amount} {self.currency} ({self.status})"

    def clean(self):
        super().clean()
        if self.pk is not None:
            previous = type(self).all_objects.filter(pk=self.pk).values("status").first()
            # A settled payment never walks backwards into pending.
            if previous and previous["status"] == "succeeded" and self.status == "pending":
                raise ValidationError(
                    {"status": "A succeeded payment cannot return to pending."}
                )
        if self.status == "succeeded" and self.paid_at is None:
            self.paid_at = timezone.now()


# ============ SUPPORTING RECORDS ============

class WebhookEvent(models.Model):
    """Gateway delivery log. `event_id` uniqueness is what makes replay harmless."""

    event_id = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=60)
    raw_payload = models.JSONField(default=dict)  # card-data keys stripped before storage
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    matched_payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhook_events"
    )
    reconciliation_required = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.kind} {self.event_id}"


class AuditRecord(models.Model):
    """Append-only. No update or delete path exists, by manager and by policy."""

    actor_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_records"
    )
    gym = models.ForeignKey(
        Gym, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_records"
    )
    action = models.CharField(max_length=20)  # create | update | soft_delete | restore
    model_label = models.CharField(max_length=60)
    object_id = models.CharField(max_length=40)
    changes = models.JSONField(default=dict)  # {field: [before, after]}
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.model_label}#{self.object_id}"


# ============ AI REVENUE RECOVERY ============

class RecoveryAttempt(models.Model):
    """Append-only record of one automated dunning decision and what came of it.

    Written by `core.services.recovery_agent` for *every* decision, including the
    ones the guardrails refused. A blocked row is the interesting one: it is the
    evidence that a language model asked for something it was not allowed to have
    and did not get it. Dropping those rows would hide precisely the failure mode
    this ledger exists to prove is contained.

    Immutable three ways over, because an audit trail an operator can quietly
    rewrite is not an audit trail: `AppendOnlyManager` refuses `update()` and
    `delete()` on any queryset, `save()` refuses a second write to the same row, and
    `delete()` refuses outright. The stopping rule is derived by *counting* these
    rows, so mutability here would also be a way to defeat the rate limit.
    """

    #: Outcomes that count as an automated contact with the member and therefore
    #: consume one of the attempts the stopping rule allows. Refusals and handoffs
    #: deliberately do not: being told "no" by a guardrail is not a dunning message,
    #: and charging the member's attempt budget for it would let a misbehaving model
    #: silence a legitimate reminder it never sent.
    CONTACT_OUTCOMES = ("reminder_sent", "discount_applied")

    OUTCOME_CHOICES = [
        ("reminder_sent", "Reminder sent"),
        ("discount_applied", "Discount applied, payment link issued"),
        ("escalated_to_human", "Escalated to a human"),
        ("payment_observed", "Payment observed"),
        ("stopped_attempt_limit", "Stopped: attempt limit reached"),
        ("stopped_already_settled", "Stopped: invoice already settled"),
        ("stopped_human_owned", "Stopped: already handed to a human"),
        ("blocked_discount_cap", "Blocked: discount above the hard cap"),
        ("blocked_duplicate_discount", "Blocked: invoice already discounted"),
        ("blocked_tenant_boundary", "Blocked: cross-tenant argument"),
        ("blocked_unknown_tool", "Blocked: tool not in the schema"),
        ("blocked_invoice_immutable", "Blocked: invoice is settled and immutable"),
        ("blocked_no_target", "Blocked: no overdue invoice for that member"),
        ("blocked_invalid_arguments", "Blocked: arguments were not usable"),
        ("gateway_unavailable", "Gateway unavailable, nothing charged"),
    ]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="recovery_attempts"
    )
    # Direct Gym FK even though the invoice already has one: every tenant-scoped row
    # in this app carries its own, and the batch report filters on it.
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="recovery_attempts")
    member = models.ForeignKey(
        MemberProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovery_attempts",
    )

    tier = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    days_overdue = models.IntegerField()

    tool_called = models.CharField(max_length=60)
    #: Exactly what was passed to the tool, after the guardrails rewrote anything.
    #: Keeps the model's request and the executed call side by side.
    arguments_passed = models.JSONField(default=dict)
    llm_reasoning_text = models.TextField(blank=True)

    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES)
    #: What the tool returned, or why it refused. Kept separate from
    #: `arguments_passed` so the request and the effect never blur together when the
    #: trail is read back.
    result_detail = models.JSONField(default=dict)
    #: What this attempt actually collected. Non-zero only on `payment_observed`, so
    #: the batch report's recovered figure is a sum over the ledger rather than a
    #: number the agent asserts about itself.
    amount_recovered = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    currency = models.CharField(max_length=3, default="INR", validators=[validate_currency])
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        # Tie-break on pk: rows written inside one batch can share a timestamp, and
        # the per-invoice audit log in the report has to read back in order.
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["gym", "outcome"], name="recovery_gym_outcome_idx"),
            models.Index(fields=["invoice", "outcome"], name="recovery_inv_outcome_idx"),
        ]

    def __str__(self):
        return f"tier{self.tier} {self.tool_called} -> {self.outcome}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise NotImplementedError("Recovery attempts are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Recovery attempts are append-only.")


class TokenBase(models.Model):
    """Only hashes are stored, so a database leak yields no usable token."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="%(class)ss")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def is_usable(self):
        return self.consumed_at is None and timezone.now() <= self.expires_at


class EmailVerificationToken(TokenBase):
    """72 hour lifetime."""


class PasswordResetToken(TokenBase):
    """60 minute lifetime."""


# ============ EQUIPMENT (shared: member + owner both see) ============

class Equipment(models.Model):
    CATEGORY_CHOICES = [("cardio", "Cardio"), ("strength", "Strength"), ("free_weights", "Free Weights")]

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name="equipment")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    image_url = models.URLField(blank=True)     # Cloudinary link
    video_url = models.URLField(blank=True)     # "how to use" demo video, Cloudinary link
    how_to_use_text = models.TextField(blank=True)
    machine_status = models.CharField(
        max_length=15, choices=[("working", "Working"), ("maintenance", "Under Maintenance")],
        default="working",
    )

    def __str__(self):
        return self.name


# ============ ATTENDANCE ============

class Attendance(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="attendance_logs")
    check_in_time = models.DateTimeField(auto_now_add=True)
    check_out_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.member} - {self.check_in_time.date()}"


# ============ DIET ============

class DietPlan(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="diet_plans")
    trainer = models.ForeignKey(TrainerProfile, on_delete=models.SET_NULL, null=True)
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Diet for {self.member}"


# ============ WORKOUT TRACKING ============

class WorkoutSplit(models.Model):
    DAY_CHOICES = [("mon", "Monday"), ("tue", "Tuesday"), ("wed", "Wednesday"),
                   ("thu", "Thursday"), ("fri", "Friday"), ("sat", "Saturday"), ("sun", "Sunday")]

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="workout_splits")
    day_of_week = models.CharField(max_length=3, choices=DAY_CHOICES)
    muscle_groups = models.CharField(max_length=200)  # comma-separated e.g. "chest,triceps"
    assigned_by = models.CharField(max_length=10, choices=[("trainer", "Trainer"), ("ai", "AI")])

    class Meta:
        unique_together = ("member", "day_of_week")

    def __str__(self):
        return f"{self.member} - {self.day_of_week}"


class Exercise(models.Model):
    split = models.ForeignKey(WorkoutSplit, on_delete=models.CASCADE, related_name="exercises")
    name = models.CharField(max_length=100)
    target_muscle = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class StrengthStandard(models.Model):
    """Reference table: bodyweight ratio needed for each tier, per exercise.

    A null `gym` is the platform-wide default row; a gym may override it.
    """
    TIER_FIELDS = ["beginner", "novice", "intermediate", "advanced", "elite"]

    gym = models.ForeignKey(
        Gym, on_delete=models.CASCADE, null=True, blank=True, related_name="strength_standards"
    )
    exercise_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=[("m", "Male"), ("f", "Female")])
    ratio_beginner = models.DecimalField(max_digits=4, decimal_places=2)
    ratio_novice = models.DecimalField(max_digits=4, decimal_places=2)
    ratio_intermediate = models.DecimalField(max_digits=4, decimal_places=2)
    ratio_advanced = models.DecimalField(max_digits=4, decimal_places=2)
    ratio_elite = models.DecimalField(max_digits=4, decimal_places=2)

    class Meta:
        unique_together = ("gym", "exercise_name", "gender")
        constraints = [
            # `unique_together` does not constrain rows where `gym` is NULL, because
            # SQL treats NULL as distinct from NULL. Without this partial constraint
            # the platform could hold two contradictory reference standards for the
            # same exercise and gender, and the shared-row lookup in 2.2
            # (`gym=mine OR gym IS NULL`) would return both (2.5).
            models.UniqueConstraint(
                fields=["exercise_name", "gender"],
                condition=Q(gym__isnull=True),
                name="strengthstandard_platform_key_unique",
            ),
        ]

    def __str__(self):
        return f"{self.exercise_name} ({self.gender})"

    def tier_for_ratio(self, lifted_to_bodyweight_ratio):
        """Given (weight lifted / bodyweight), return the tier name."""
        if lifted_to_bodyweight_ratio >= self.ratio_elite:
            return "elite"
        if lifted_to_bodyweight_ratio >= self.ratio_advanced:
            return "advanced"
        if lifted_to_bodyweight_ratio >= self.ratio_intermediate:
            return "intermediate"
        if lifted_to_bodyweight_ratio >= self.ratio_novice:
            return "novice"
        return "beginner"


class WorkoutLog(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="workout_logs")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="logs")
    date = models.DateField(auto_now_add=True)
    weight = models.DecimalField(max_digits=6, decimal_places=2)
    reps = models.PositiveIntegerField()
    sets = models.PositiveIntegerField()
    calculated_tier = models.CharField(max_length=15, blank=True)  # filled in by app logic

    def __str__(self):
        return f"{self.member} - {self.exercise} - {self.date}"


class BodyMetric(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="body_metrics")
    date = models.DateField(auto_now_add=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=2)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2)
    chest_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    waist_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    arms_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.member} - {self.date}"


class FormCheck(models.Model):
    """Member uploads a recorded video; trainer reviews it asynchronously (no live call in MVP)."""
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="form_checks")
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    video_url = models.URLField()  # Cloudinary link
    reviewed_by = models.ForeignKey(TrainerProfile, on_delete=models.SET_NULL, null=True, blank=True)
    feedback_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=15,
        choices=[("pending", "Pending Review"), ("reviewed", "Reviewed")],
        default="pending",
    )
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.member} - {self.exercise} ({self.status})"


# ============ NOTIFICATIONS ============

class Notification(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name="notifications")
    notif_type = models.CharField(max_length=20, choices=[("attendance", "Attendance"), ("fee_due", "Fee Due")])
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=[("sent", "Sent"), ("failed", "Failed")], default="sent")

    def __str__(self):
        return f"{self.member} - {self.notif_type}"
