"""Feature: gym-saas-core, Property 21.

Three layers guard a Payment amount and they are tested as three layers, because
each one catches something the others cannot:

* `MinValueValidator` / `DecimalValidator` on the field — reached by `full_clean()`,
  which is what names the offending field for the API error envelope.
* The `payment_amount_positive` CheckConstraint — reached by *any* insert, including
  one that skips validation entirely, which is the only guard that holds against a
  careless `objects.create()` or a raw shell session.
* `validate_currency` — restricts the code to a three-letter ISO 4217 value the
  gateway account can actually settle.
"""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from hypothesis import given, settings
from hypothesis import strategies as st

from core.models import Payment
from core.services.money import to_minor_units
from core.tests import factories
from core.tests.strategies import (
    invalid_currencies,
    payable_amounts,
    supported_currencies,
    unpayable_amounts,
)

#: Smallest chargeable amount, from requirement 16.5.
MINIMUM_AMOUNT = Decimal("0.01")

#: Decimal(12, 2): ten whole digits plus two decimal places.
WIDEST_AMOUNT = Decimal("9999999999.99")

#: Values that cannot be stored in a Decimal(12, 2) column at all, as opposed to
#: values that are merely too small to charge.
UNREPRESENTABLE_AMOUNTS = [
    Decimal("0.001"),            # three decimal places
    Decimal("0.005"),
    Decimal("1.234"),
    Decimal("12.345"),
    Decimal("10000000000.00"),   # eleven whole digits
    Decimal("99999999999.99"),
    Decimal("123456789012.34"),
]


def unsaved_payment(**overrides):
    """A Payment instance that validates without touching the database.

    The FKs are set by `attname`, so `clean_fields()` validates the integer values
    it was given and issues no query. That keeps this property pure: the field-level
    acceptance rule is a property of the field declaration, not of any stored row.
    """
    fields = {
        "invoice_id": 1,
        "gym_id": 1,
        "amount": Decimal("100.00"),
        "currency": "INR",
        "status": "pending",
        "gateway": "razorpay",
        "idempotency_key": "idem-property-21",
        "recorded_on": datetime.date(2025, 6, 1),
    }
    fields.update(overrides)
    return Payment(**fields)


#: Relations are excluded from validation here because `ForeignKey.validate()`
#: queries for the referenced row. Their existence is not what this property is
#: about, and excluding them keeps the amount/currency rule provable as a pure
#: property of the field declaration.
RELATION_FIELDS = ["invoice", "gym", "refund_of"]


def validate(payment):
    """Field-level validation only.

    `validate_unique` and `validate_constraints` are off deliberately: both need the
    database, and both are covered by their own tests below. What is under test here
    is the declared field validation and the field name it reports.
    """
    payment.full_clean(
        exclude=RELATION_FIELDS, validate_unique=False, validate_constraints=False
    )


# Feature: gym-saas-core, Property 21: For any Decimal value, it is accepted as a
# Payment amount if and only if it is greater than or equal to 0.01 and representable
# in 12 digits with 2 decimal places, rejection names the amount field, and for any
# three-letter string it is accepted as a currency if and only if it is a valid
# ISO 4217 code, with INR applied as the default.
# Validates: Requirements 16.5, 16.6, 16.8
@settings(max_examples=100)
@given(amount=st.one_of(payable_amounts(), unpayable_amounts()))
def test_amount_accepted_exactly_when_at_least_one_paisa(amount):
    """The biconditional for two-decimal amounts inside the column width."""
    amount = Decimal(amount)
    should_be_accepted = amount >= MINIMUM_AMOUNT

    payment = unsaved_payment(amount=amount)

    if should_be_accepted:
        validate(payment)
        assert payment.amount == amount
    else:
        with pytest.raises(DjangoValidationError) as caught:
            validate(payment)
        # 16.6 requires the error to name the amount field.
        assert "amount" in caught.value.message_dict


@settings(max_examples=100)
@given(amount=st.sampled_from(UNREPRESENTABLE_AMOUNTS))
def test_amounts_outside_twelve_digits_two_places_are_refused(amount):
    """The representability half of the biconditional (16.5)."""
    with pytest.raises(DjangoValidationError) as caught:
        validate(unsaved_payment(amount=amount))
    assert "amount" in caught.value.message_dict


def test_the_two_boundary_amounts_are_accepted():
    """0.01 is chargeable and 9999999999.99 fits; both are on the accepted side."""
    for amount in (MINIMUM_AMOUNT, WIDEST_AMOUNT):
        validate(unsaved_payment(amount=amount))


# ============ CURRENCY ============

@settings(max_examples=100)
@given(currency=supported_currencies())
def test_supported_iso_codes_are_accepted(currency):
    payment = unsaved_payment(currency=currency)
    validate(payment)
    assert payment.currency == currency


@settings(max_examples=100)
@given(currency=invalid_currencies())
def test_non_iso_or_unsettleable_codes_are_refused_naming_currency(currency):
    with pytest.raises(DjangoValidationError) as caught:
        validate(unsaved_payment(currency=currency))
    assert "currency" in caught.value.message_dict


def test_currency_defaults_to_inr():
    """16.8: INR is the declared default, not merely the value tests happen to pass."""
    assert Payment._meta.get_field("currency").default == "INR"
    assert unsaved_payment(currency=None).currency is None  # explicit None is not a default
    assert Payment(invoice_id=1, gym_id=1).currency == "INR"


# ============ DATABASE-LEVEL GUARDS ============

@pytest.mark.django_db
def test_check_constraint_refuses_a_non_positive_amount_that_skips_validation():
    """22.6 must hold for every stored row, including inserts that skip full_clean."""
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    invoice = factories.make_invoice(gym, owner.user, taxable="100.00")

    for amount in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(
                    invoice=invoice,
                    gym=gym,
                    amount=amount,
                    currency="INR",
                    status="pending",
                    idempotency_key=f"idem-constraint-{amount}",
                    recorded_on=gym.today(),
                )

    assert not Payment.all_objects.filter(invoice=invoice).exists()


@pytest.mark.django_db
def test_created_payment_currency_matches_its_invoice_and_round_trips_to_minor_units():
    """Currency consistency: the Payment settles in the currency the Invoice states."""
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    invoice = factories.make_invoice(gym, owner.user, taxable="1234.56")

    from core.services.payments import create_order

    result = create_order(invoice, actor=owner.user)
    payment = result["payment"]
    order = result["order"]

    assert payment.currency == invoice.currency
    assert order.currency == invoice.currency
    # The integer handed to the gateway is the stored Decimal, exactly.
    assert order.amount_minor == to_minor_units(payment.amount, payment.currency)
    assert payment.amount == invoice.total_amount
