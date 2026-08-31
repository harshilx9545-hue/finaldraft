"""Decimal money <-> gateway minor units.

Razorpay takes amounts as integers in the currency's minor unit (paise for INR).
Doing that conversion in one place, with an explicit rounding mode, is what keeps
the stored Decimal and the amount actually charged from drifting apart.
"""
from decimal import ROUND_HALF_UP, Decimal

#: Number of minor units in one major unit, per currency. Every currency the
#: platform settles in happens to be two-decimal, but the table is explicit so
#: adding a zero-decimal currency (JPY) or three-decimal one (KWD) is a data
#: change rather than a code change.
MINOR_UNIT_EXPONENT = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AED": 2,
    "SGD": 2,
    "AUD": 2,
    "CAD": 2,
}

DEFAULT_CURRENCY = "INR"


def exponent_for(currency=DEFAULT_CURRENCY):
    """Minor-unit exponent for a currency, defaulting to 2 for anything unlisted."""
    return MINOR_UNIT_EXPONENT.get((currency or DEFAULT_CURRENCY).upper(), 2)


def quantize_money(amount, currency=DEFAULT_CURRENCY):
    """Snap a Decimal to the currency's stored precision using ROUND_HALF_UP.

    Banker's rounding (Python's Decimal default) would round 0.125 down to 0.12,
    which is not how an invoice line is expected to behave.
    """
    places = Decimal(1).scaleb(-exponent_for(currency))
    return Decimal(amount).quantize(places, rounding=ROUND_HALF_UP)


def to_minor_units(amount, currency=DEFAULT_CURRENCY):
    """Decimal major units -> integer minor units. 12.34 INR -> 1234 paise."""
    scaled = quantize_money(amount, currency).scaleb(exponent_for(currency))
    # The value is already integral after quantize+scaleb; quantize again at 0
    # places only to drop the exponent so int() is exact.
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor_units(minor, currency=DEFAULT_CURRENCY):
    """Integer minor units -> Decimal major units. 1234 paise -> Decimal("12.34")."""
    if int(minor) != minor:
        raise ValueError("Minor units must be a whole number.")
    return quantize_money(Decimal(int(minor)).scaleb(-exponent_for(currency)), currency)
