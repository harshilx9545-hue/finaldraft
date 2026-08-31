"""Feature: gym-saas-core, Property 11."""
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from hypothesis import given
from hypothesis import settings as hyp_settings

from core.models import User
from core.tests import factories
from core.tests.strategies import blank_emails, e164_phones, emails, malformed_phones

pytestmark = pytest.mark.django_db


# Feature: gym-saas-core, Property 11: For any string, it is accepted as a User email
# only if non-empty after trimming and unique across the Platform compared
# case-insensitively, and accepted as a User phone only if it matches
# ^\+[1-9]\d{7,14}$ and is unique among non-null phone values; rejection names the
# offending field, and any number of Users may hold a null phone.
# Validates: Requirements 10.1, 10.2, 10.3, 10.9, 10.10
@hyp_settings(max_examples=100)
@given(email=blank_emails())
def test_blank_email_is_rejected_naming_the_field(email):
    with pytest.raises((DjangoValidationError, ValueError)) as caught:
        User.objects.create_user(email=email, password="Correct-Horse-Battery-7")
    message = str(caught.value)
    assert "email" in message.lower()


@hyp_settings(max_examples=100)
@given(email=emails())
def test_email_uniqueness_is_case_insensitive(email):
    # Examples share the transaction, so isolate this generated input from the
    # preceding case-insensitive value.
    User.objects.all().delete()
    User.objects.create_user(email=email, password="Correct-Horse-Battery-7")

    with pytest.raises((IntegrityError, DjangoValidationError)):
        with transaction.atomic():
            User.objects.create_user(
                email=email.upper(), password="Correct-Horse-Battery-7"
            )


@hyp_settings(max_examples=100)
@given(phone=malformed_phones())
def test_malformed_phone_is_rejected_naming_the_field(phone):
    User.objects.all().delete()
    if not phone.strip():
        # Blank collapses to NULL by design, which is legal (10.10).
        user = User.objects.create_user(
            email=factories.unique_email(), password="Correct-Horse-Battery-7", phone=phone
        )
        assert user.phone is None
        return

    with pytest.raises(DjangoValidationError) as caught:
        User.objects.create_user(
            email=factories.unique_email(), password="Correct-Horse-Battery-7", phone=phone
        )
    assert "phone" in str(caught.value).lower()


@hyp_settings(max_examples=100)
@given(phone=e164_phones())
def test_wellformed_phone_is_accepted_and_unique(phone):
    User.objects.all().delete()
    User.objects.create_user(
        email=factories.unique_email(), password="Correct-Horse-Battery-7", phone=phone
    )

    with pytest.raises((IntegrityError, DjangoValidationError)):
        with transaction.atomic():
            User.objects.create_user(
                email=factories.unique_email(),
                password="Correct-Horse-Battery-7",
                phone=phone,
            )


def test_any_number_of_users_may_hold_a_null_phone():
    """10.10: NULL repeats freely; only concrete values must be unique."""
    for _ in range(5):
        User.objects.create_user(
            email=factories.unique_email(), password="Correct-Horse-Battery-7", phone=None
        )
    assert User.objects.filter(phone__isnull=True).count() >= 5


def test_username_is_optional_and_off_the_login_path():
    """10.9"""
    user = User.objects.create_user(
        email=factories.unique_email(), password="Correct-Horse-Battery-7"
    )
    assert user.username is None
    assert User.USERNAME_FIELD == "email"


@hyp_settings(max_examples=100)
@given(email=emails())
def test_email_is_normalised_and_trimmed(email):
    User.objects.all().delete()
    user = User.objects.create_user(
        email=f"  {email}  ", password="Correct-Horse-Battery-7"
    )
    assert user.email == user.email.strip()
    # The domain half is lowercased by Django's normalize_email.
    assert user.email.split("@")[1] == email.split("@")[1].lower()
