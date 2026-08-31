"""Feature: gym-saas-core, Property 18."""
from decimal import Decimal

from hypothesis import given, settings

from core.services.money import from_minor_units, to_minor_units
from core.tests.strategies import supported_currencies, two_dp_decimals


# Feature: gym-saas-core, Property 18: For any Decimal amount with exactly two
# decimal places, converting the amount to the Payment_Gateway's minor-unit integer
# representation and back yields the original amount.
# Validates: Requirements 17.4, 17.3
@settings(max_examples=500)
@given(amount=two_dp_decimals(), currency=supported_currencies())
def test_minor_unit_round_trip(amount, currency):
    assert from_minor_units(to_minor_units(amount, currency), currency) == amount


@settings(max_examples=500)
@given(amount=two_dp_decimals())
def test_minor_units_are_paise_for_inr(amount):
    """INR minor units are paise: the integer is the amount times 100."""
    assert to_minor_units(amount, "INR") == int((amount * 100).to_integral_value())


@settings(max_examples=500)
@given(amount=two_dp_decimals())
def test_conversion_is_monotonic(amount):
    """A larger amount never converts to a smaller integer."""
    larger = amount + Decimal("0.01")
    assert to_minor_units(larger) > to_minor_units(amount)


def test_half_up_rounding_not_bankers():
    """0.125 rounds to 0.13, not 0.12: an invoice line is not banker's-rounded."""
    from core.services.money import quantize_money

    assert quantize_money(Decimal("0.125")) == Decimal("0.13")
    assert quantize_money(Decimal("0.135")) == Decimal("0.14")
