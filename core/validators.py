"""Field validators shared across the model layer."""
import re
from zoneinfo import available_timezones

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

# E.164: leading +, first digit non-zero, 8-15 digits total.
validate_e164 = RegexValidator(
    regex=r"^\+[1-9]\d{7,14}$",
    message="Phone must be in E.164 format, e.g. +919876543210.",
    code="invalid_phone",
)

validate_gym_slug = RegexValidator(
    regex=r"^[a-z0-9]+(-[a-z0-9]+)*$",
    message="Slug may contain only lowercase letters, digits and single hyphens.",
    code="invalid_slug",
)

validate_gstin = RegexValidator(
    regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
    message="Enter a valid 15-character GSTIN.",
    code="invalid_gstin",
)

# Kept deliberately small: the currencies the platform can actually settle.
SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD"}


def validate_currency(value):
    """ISO-4217 alphabetic code, restricted to what the gateway account supports."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value or ""):
        raise ValidationError(
            "Currency must be a three-letter uppercase ISO 4217 code.",
            code="invalid_currency",
        )
    if value not in SUPPORTED_CURRENCIES:
        raise ValidationError(
            "%(value)s is not a supported settlement currency.",
            code="unsupported_currency",
            params={"value": value},
        )


def validate_timezone(value):
    """Must be a name the standard library recognises, so date maths is unambiguous."""
    if value not in available_timezones():
        raise ValidationError(
            "%(value)s is not a valid IANA timezone name.",
            code="invalid_timezone",
            params={"value": value},
        )
