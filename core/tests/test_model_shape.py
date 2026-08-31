"""Model shape and schema assertions (task 4.7).

Schema facts do not vary with input, so these are examples.
Validates: Requirements 1.1, 1.3, 2.1, 4.1, 4.2, 4.3, 16.1, 16.2, 19.1, 19.2, 21.1,
21.2, 23.1
"""
from decimal import Decimal

import pytest
from django.apps import apps

from core import models as core_models
from core.models import (
    Equipment,
    Gym,
    Invoice,
    Membership,
    MembershipPlan,
    MemberProfile,
    OwnerProfile,
    Payment,
    SaasPlan,
    SaasSubscription,
    StrengthStandard,
    TrainerProfile,
    User,
)

#: Field-name fragments that would mean card data reached the database (23.1).
CARD_DATA_TOKENS = (
    "cardnumber",
    "cardno",
    "cvv",
    "cvc",
    "pan",
    "expiry",
    "expmonth",
    "expyear",
    "cardholder",
    "trackdata",
)


def field(model, name):
    return model._meta.get_field(name)


# ============ TENANCY ============

@pytest.mark.parametrize(
    "model",
    [OwnerProfile, TrainerProfile, MemberProfile, MembershipPlan, Equipment],
)
def test_gym_fk_is_non_nullable(model):
    """2.1, 1.3: a tenant-scoped row with no Gym is unfilterable and therefore unsafe."""
    gym_field = field(model, "gym")
    assert gym_field.null is False
    assert gym_field.related_model is Gym


def test_strength_standard_gym_fk_is_nullable_and_scoped():
    """2.2, 2.5: a null Gym is the platform-wide default row."""
    assert field(StrengthStandard, "gym").null is True
    assert StrengthStandard._meta.unique_together == (
        ("gym", "exercise_name", "gender"),
    )


def test_gym_slug_uniqueness_is_case_insensitive():
    """1.4"""
    names = {constraint.name for constraint in Gym._meta.constraints}
    assert "gym_slug_ci_unique" in names


def test_membership_plan_name_is_unique_per_gym():
    """2.4"""
    names = {constraint.name for constraint in MembershipPlan._meta.constraints}
    assert "membershipplan_name_ci_unique_per_gym" in names


# ============ IDENTITY ============

def test_email_is_the_login_identifier():
    """10.1, 10.9"""
    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []
    assert field(User, "email").unique is True
    assert field(User, "username").unique is False
    assert field(User, "username").null is True


def test_phone_is_nullable_and_unique():
    """10.3, 10.10"""
    phone = field(User, "phone")
    assert phone.null is True
    assert phone.unique is True


def test_role_defaults_to_member_and_is_choice_bound():
    """11.1, 11.2"""
    role = field(User, "role")
    assert role.default == "member"
    assert {value for value, _ in role.choices} == {"owner", "trainer", "member"}


def test_email_verified_flag_exists():
    assert field(User, "email_verified").default is False


# ============ PLANS ============

def test_seat_limit_lives_only_on_saas_plan():
    """4.3: MembershipPlan must not carry max_members_allowed."""
    assert field(SaasPlan, "max_members_allowed").null is True
    with pytest.raises(Exception):
        field(MembershipPlan, "max_members_allowed")


def test_membership_plan_duration_is_bounded():
    """4.4, 20.3"""
    limits = [
        validator.limit_value
        for validator in field(MembershipPlan, "duration_days").validators
        if hasattr(validator, "limit_value")
    ]
    assert 1 in limits and 3650 in limits


def test_member_profile_has_no_stored_status_and_a_settable_join_date():
    """20.4, 20.9"""
    with pytest.raises(Exception):
        field(MemberProfile, "status")
    join_date = field(MemberProfile, "join_date")
    assert join_date.auto_now_add is False
    assert join_date.editable is True


def test_plan_fk_targets_membership_plan():
    """4.2"""
    assert field(MemberProfile, "plan").related_model is MembershipPlan


# ============ SUBSCRIPTION ============

def test_saas_subscription_shape():
    """21.1, 21.2"""
    assert field(SaasSubscription, "gym").one_to_one
    assert {value for value, _ in field(SaasSubscription, "status").choices} == {
        "trialing",
        "active",
        "past_due",
        "cancelled",
    }


# ============ MEMBERSHIP ============

def test_membership_end_date_is_not_client_settable():
    assert field(Membership, "end_date").editable is False


def test_membership_end_after_start_constraint_exists():
    names = {constraint.name for constraint in Membership._meta.constraints}
    assert "membership_end_after_start" in names


# ============ MONEY ============

def test_invoice_shape_and_constraints():
    """19.1, 19.2"""
    for name in (
        "number",
        "payer_user",
        "gym",
        "saas_subscription",
        "membership",
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
        "financial_year",
        "sequence_no",
        "deleted_at",
    ):
        assert field(Invoice, name) is not None

    for name in ("cgst", "sgst", "igst", "hsn_sac"):
        # Nullable, because "not applicable" is not the same as zero.
        assert field(Invoice, name).null is True

    names = {constraint.name for constraint in Invoice._meta.constraints}
    assert "invoice_seq_unique_per_gym_fy" in names
    assert "invoice_number_unique_per_gym" in names

    assert {value for value, _ in field(Invoice, "status").choices} == {
        "open",
        "settled",
        "void",
        "refunded",
    }


def test_payment_shape_and_constraints():
    """16.1, 16.2, 16.3, 16.4, 16.5, 16.7"""
    assert field(Payment, "idempotency_key").unique is True
    assert field(Payment, "recorded_on").auto_now_add is False
    assert field(Payment, "refund_of").related_model is Payment

    assert {value for value, _ in field(Payment, "status").choices} == {
        "pending",
        "succeeded",
        "failed",
        "refunded",
        "cancelled",
    }

    names = {constraint.name for constraint in Payment._meta.constraints}
    assert "payment_amount_positive" in names
    assert "payment_gateway_ref_unique_when_present" in names

    minimums = [
        validator.limit_value
        for validator in field(Payment, "amount").validators
        if hasattr(validator, "limit_value")
    ]
    assert Decimal("0.01") in minimums


def test_invoice_sequence_is_unique_per_gym_and_year():
    from core.models import InvoiceSequence

    names = {constraint.name for constraint in InvoiceSequence._meta.constraints}
    assert "invoiceseq_unique_per_gym_fy" in names


def test_financial_models_have_no_hard_delete_path():
    """22.3"""
    for model in (Invoice, Payment, Membership):
        assert model.hard_delete_allowed is False


def test_audit_record_manager_is_append_only():
    """22.2"""
    from core.models import AuditRecord

    with pytest.raises(NotImplementedError):
        AuditRecord.objects.all().update(action="tampered")
    with pytest.raises(NotImplementedError):
        AuditRecord.objects.all().delete()


def test_tokens_store_only_hashes():
    from core.models import EmailVerificationToken, PasswordResetToken

    for model in (EmailVerificationToken, PasswordResetToken):
        field_names = {f.name for f in model._meta.concrete_fields}
        assert "token_hash" in field_names
        assert "token" not in field_names
        assert "expires_at" in field_names
        assert "consumed_at" in field_names


# ============ CARD DATA ============

def test_no_model_declares_a_card_data_field():
    """23.1: there must be no column card data could land in."""
    offenders = []
    for model in apps.get_app_config("core").get_models():
        for model_field in model._meta.concrete_fields:
            normalised = model_field.name.lower().replace("_", "")
            if any(token in normalised for token in CARD_DATA_TOKENS):
                offenders.append(f"{model.__name__}.{model_field.name}")
    assert not offenders, f"card-data fields present: {offenders}"


def test_webhook_event_and_audit_record_exist_with_the_documented_shape():
    """18.7, 18.9, 22.1"""
    from core.models import AuditRecord, WebhookEvent

    assert field(WebhookEvent, "event_id").unique is True
    assert field(WebhookEvent, "reconciliation_required").default is False
    for name in ("actor_user", "action", "model_label", "object_id", "gym", "changes"):
        assert field(AuditRecord, name) is not None
