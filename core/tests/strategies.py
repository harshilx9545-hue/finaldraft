"""Shared hypothesis strategies.

Pure-value strategies live at the top; model-backed ones (which need a database)
are at the bottom and are imported lazily so this module stays importable during
collection before Django's app registry is ready.

Every generator deliberately includes the edge cases the design calls out, mixed
in with `st.one_of` rather than left to chance: hypothesis will find them, but
naming them makes the intent reviewable and keeps shrinking fast.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from zoneinfo import available_timezones

from hypothesis import strategies as st

# ============ MONEY ============

#: Amounts at the boundaries the design names: exactly zero, the smallest
#: chargeable amount, and the widest value a Decimal(12, 2) column can hold.
MONEY_EDGE_CASES = [
    Decimal("0.00"),
    Decimal("0.01"),
    Decimal("0.99"),
    Decimal("1.00"),
    Decimal("0.125").quantize(Decimal("0.01")),  # ROUND_HALF_UP lands on 0.13
    Decimal("9999999999.99"),
]


def two_dp_decimals(min_value="0.00", max_value="9999999999.99"):
    """Decimals with exactly two decimal places, inside a Decimal(12, 2) column."""
    generated = st.decimals(
        min_value=Decimal(min_value),
        max_value=Decimal(max_value),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    )
    edges = [
        value
        for value in MONEY_EDGE_CASES
        if Decimal(min_value) <= value <= Decimal(max_value)
    ]
    if not edges:
        return generated
    return st.one_of(generated, st.sampled_from(edges))


def payable_amounts():
    """Amounts a Payment may legally carry: >= 0.01."""
    return two_dp_decimals(min_value="0.01")


def unpayable_amounts():
    """Amounts a Payment must reject: zero, or negative."""
    return st.one_of(
        st.just(Decimal("0.00")),
        st.decimals(
            min_value=Decimal("-9999999999.99"),
            max_value=Decimal("-0.01"),
            allow_nan=False,
            allow_infinity=False,
            places=2,
        ),
    )


# ============ IDENTIFIERS ============

def e164_phones():
    """Well-formed E.164: leading +, non-zero first digit, 8-15 digits total."""
    return st.builds(
        lambda head, tail: f"+{head}{tail}",
        head=st.integers(min_value=1, max_value=9),
        tail=st.text(alphabet="0123456789", min_size=7, max_size=14),
    )


#: Shapes the E.164 validator must refuse. Kept explicit because "rejected without
#: touching stored phone values" (Property 10) is about these exact inputs.
MALFORMED_PHONES = [
    "",
    " ",
    "\t",
    "1234567890",          # no +
    "+0123456789",         # leading zero after +
    "+123",                # too short
    "+1234567890123456",   # too long
    "+12 34 56 789",       # spaces
    "+91-98765-43210",     # hyphens
    "++919876543210",
    "+abcdefghij",
    "not-a-phone",
]


def malformed_phones():
    return st.sampled_from(MALFORMED_PHONES)


def emails():
    """Deliberately simple: uniqueness and case folding matter here, not RFC 5322."""
    local = st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=1,
        max_size=20,
    )
    domain = st.sampled_from(["example.com", "Example.COM", "gym.test", "mail.example.co.in"])
    return st.builds(lambda l, d: f"{l}@{d}", l=local, d=domain)


#: Strings that must never be accepted as an email (10.1, 10.2).
BLANK_EMAILS = ["", " ", "   ", "\t", "\n", " \t\n "]


def blank_emails():
    return st.sampled_from(BLANK_EMAILS)


# ============ BUSINESS NAMES AND SLUGS ============

#: Names whose derivation exercises a specific branch of the slug service:
#: emptiness, whitespace-only, punctuation-only, non-Latin scripts that
#: transliterate to nothing, accented Latin that transliterates to something,
#: and lengths that force truncation at 60 characters.
BUSINESS_NAME_EDGE_CASES = [
    "",
    " ",
    "   \t\n ",
    "---",
    "!!!",
    "@#$%^&*()",
    "___",
    "💪🏋️",                      # emoji only -> transliterates to empty
    "ジム",                        # katakana -> transliterates to empty
    "джим",                       # cyrillic -> transliterates to empty
    "健身房",                      # han -> transliterates to empty
    "Café Fitnesse",             # accents survive transliteration
    "Ürban Gÿm",
    "  Iron   Pit  ",            # collapsing runs and trimming edges
    "Iron--Pit",
    "-Iron Pit-",
    "A",
    "9",
    "a" * 60,
    "a" * 61,
    "a" * 200,
    "Gym " * 40,
]


def unicode_business_names():
    """Any Unicode string, weighted toward the derivation edge cases.

    Control characters (category "Cc", which includes the NUL byte) are excluded:
    Django's ProhibitNullCharactersValidator rejects them with a 400 before
    registration logic ever runs, which is correct behaviour but not something
    any of the atomicity/derivation properties are written to assert against.
    Generating them just produces failures unrelated to the property under test.
    """
    return st.one_of(
        st.sampled_from(BUSINESS_NAME_EDGE_CASES),
        st.text(
            alphabet=st.characters(blacklist_categories=["Cc"]),
            min_size=0,
            max_size=80,
        ),
        st.text(
            alphabet=st.characters(
                categories=["Lu", "Ll", "Nd", "Zs", "Po", "So", "Sk", "Mn"]
            ),
            min_size=0,
            max_size=80,
        ),
    )


def collision_counts():
    """Number of pre-existing colliding slugs the derivation must route around.

    Capped at 49: the service allows suffixes 2..51, so 49 prior collisions is the
    largest count that must still succeed (Property 7).
    """
    return st.integers(min_value=1, max_value=49)


# ============ TIME ============

#: Zones chosen for behaviour rather than variety: a half-hour offset with no DST,
#: two southern-hemisphere DST zones, a zone with a historic offset change, and UTC.
NOTABLE_TIMEZONES = [
    "Asia/Kolkata",        # +05:30, no DST
    "UTC",
    "America/New_York",    # spring-forward / fall-back
    "Australia/Sydney",    # southern-hemisphere DST
    "Pacific/Chatham",     # +12:45 / +13:45
    "Pacific/Kiritimati",  # +14:00, the extreme
    "Europe/London",
    "America/Sao_Paulo",   # DST abolished mid-history
]


def iana_timezones():
    """Valid IANA names, weighted toward the ones that break naive date maths."""
    return st.one_of(
        st.sampled_from(NOTABLE_TIMEZONES),
        st.sampled_from(sorted(available_timezones())),
    )


def invalid_timezones():
    return st.sampled_from(
        ["", " ", "Not/AZone", "Asia/Kolkatta", "IST", "GMT+5:30", "Mars/Olympus"]
    )


#: Dates that make period arithmetic interesting: leap day, the day before and
#: after it, DST transition days, financial-year boundaries, and month ends.
DATE_EDGE_CASES = [
    datetime.date(2024, 2, 28),
    datetime.date(2024, 2, 29),   # leap day
    datetime.date(2024, 3, 1),
    datetime.date(2023, 2, 28),   # non-leap February end
    datetime.date(2024, 3, 10),   # US spring forward
    datetime.date(2024, 11, 3),   # US fall back
    datetime.date(2024, 10, 6),   # AU spring forward
    datetime.date(2025, 3, 31),   # last day of Indian FY 2024-25
    datetime.date(2025, 4, 1),    # first day of Indian FY 2025-26
    datetime.date(2024, 12, 31),
    datetime.date(2025, 1, 1),
]


def dates():
    return st.one_of(
        st.sampled_from(DATE_EDGE_CASES),
        st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2035, 12, 31)),
    )


def durations_valid():
    """`duration_days` values a MembershipPlan must accept: 1..3650 inclusive."""
    return st.one_of(
        st.sampled_from([1, 2, 30, 31, 365, 366, 3649, 3650]),
        st.integers(min_value=1, max_value=3650),
    )


def durations_invalid():
    """`duration_days` values a MembershipPlan must refuse: <= 0 or > 3650."""
    return st.one_of(
        st.sampled_from([0, -1, 3651, 3652, 10_000]),
        st.integers(min_value=-3650, max_value=0),
        st.integers(min_value=3651, max_value=100_000),
    )


def membership_periods():
    """(start_date, duration_days) pairs for a valid membership period."""
    return st.tuples(dates(), durations_valid())


def clock_offsets():
    """Offsets that straddle the 72h verification and 60m reset expiry boundaries."""
    return st.one_of(
        st.sampled_from(
            [
                datetime.timedelta(seconds=0),
                datetime.timedelta(minutes=59, seconds=59),
                datetime.timedelta(minutes=60),
                datetime.timedelta(minutes=60, seconds=1),
                datetime.timedelta(hours=71, minutes=59, seconds=59),
                datetime.timedelta(hours=72),
                datetime.timedelta(hours=72, seconds=1),
            ]
        ),
        st.timedeltas(
            min_value=datetime.timedelta(seconds=0),
            max_value=datetime.timedelta(days=10),
        ),
    )


# ============ CURRENCY ============

def supported_currencies():
    from core.validators import SUPPORTED_CURRENCIES

    return st.sampled_from(sorted(SUPPORTED_CURRENCIES))


def invalid_currencies():
    return st.one_of(
        st.sampled_from(["", "I", "IN", "INRR", "inr", "In1", "123", "₹₹₹", "XYZ"]),
        st.text(min_size=0, max_size=5).filter(lambda v: not v.isupper() or len(v) != 3),
    )


# ============ GSTIN ============

#: A structurally valid GSTIN: 2-digit state code, 5 letters, 4 digits, letter,
#: alphanumeric, literal Z, checksum character.
def gstins():
    return st.builds(
        lambda state, pan_alpha, pan_num, pan_last, entity, check: (
            f"{state}{pan_alpha}{pan_num}{pan_last}{entity}Z{check}"
        ),
        state=st.text(alphabet="0123456789", min_size=2, max_size=2),
        pan_alpha=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=5, max_size=5),
        pan_num=st.text(alphabet="0123456789", min_size=4, max_size=4),
        pan_last=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        entity=st.sampled_from("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        check=st.sampled_from("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    )


# ============ CONFIGURATION ============

#: The three SMTP variables Property 40 permutes.
SMTP_VARIABLES = ["EMAIL_HOST", "EMAIL_PORT", "DEFAULT_FROM_EMAIL"]


def smtp_variable_subsets():
    """Every subset of the SMTP variables, as the set to *omit* from the env."""
    return st.sets(st.sampled_from(SMTP_VARIABLES), min_size=0, max_size=3)


def valid_hosts():
    return st.one_of(
        st.sampled_from(
            [
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "::1",
                "example.com",
                "api.example.com",
                ".example.com",
                "gym-app.example.co.in",
                "10.0.0.1",
            ]
        ),
    )


def invalid_hosts():
    return st.sampled_from(
        ["*", "", " ", ".*", "*.example.com", "exa mple.com", "-example.com", "example-.com"]
    )


def secret_keys():
    """Keys including the `django-insecure-` prefix production must refuse."""
    return st.one_of(
        st.just(""),
        st.builds(lambda tail: f"django-insecure-{tail}", tail=st.text(min_size=1, max_size=40)),
        st.text(min_size=20, max_size=60).filter(
            lambda value: not value.startswith("django-insecure-") and value.strip() != ""
        ),
    )


def throttle_rates():
    """Configured per-minute rates, including values below the floor of 5."""
    return st.one_of(
        st.sampled_from([0, 1, 4, 5, 6, 100]),
        st.integers(min_value=-10, max_value=1000),
    )


# ============ CARD DATA ============

#: Field names the payment endpoints must refuse outright (23.4). Values are
#: deliberately fake.
CARD_DATA_FIELD_NAMES = [
    "card_number",
    "cardNumber",
    "card",
    "pan",
    "cvv",
    "cvc",
    "card_cvv",
    "expiry",
    "exp_month",
    "exp_year",
    "card_expiry",
    "cardholder_name",
    "track_data",
]


def card_data_field_names():
    return st.sampled_from(CARD_DATA_FIELD_NAMES)


def nested_card_data_bodies():
    """Request bodies hiding a card-data key at a random nesting depth."""

    def wrap(name, depth):
        body = {name: "4111111111111111"}
        for level in range(depth):
            body = {f"level_{level}": body}
        return body

    return st.builds(wrap, name=card_data_field_names(), depth=st.integers(0, 4))


# ============ MODEL-BACKED STRATEGIES ============
# Everything below touches the database, so these must only be drawn inside a test
# marked `django_db`. They are kept as composite strategies rather than
# `from_model()` because the factories enforce service-layer rules that
# `from_model()` would bypass.


@st.composite
def gyms(draw, *, with_subscription=True, max_members=None, timezone_name=None):
    """A persisted Gym with a random valid timezone."""
    from core.tests.factories import make_gym

    return make_gym(
        timezone_name=timezone_name or draw(iana_timezones()),
        with_subscription=with_subscription,
        max_members=max_members,
        gstin=draw(st.one_of(st.none(), gstins())),
    )


def users(*, role="member", gym=None):
    """A persisted User with the matching profile for `role`.

    Built with `st.builds` rather than `@st.composite`: there is nothing random to
    draw here, and hypothesis deprecates a composite that never calls `draw()`.
    """

    def build():
        from core.tests.factories import make_gym, make_member, make_owner, make_trainer

        target_gym = gym or make_gym()
        if role == "owner":
            return make_owner(target_gym)
        if role == "trainer":
            return make_trainer(target_gym)
        return make_member(target_gym)

    return st.builds(build)


def roles():
    return st.sampled_from(["owner", "trainer", "member"])


def subscription_statuses():
    return st.sampled_from(["trialing", "active", "past_due", "cancelled"])


#: (url name, kwargs-needed, methods) for every tenant-scoped endpoint. Used by the
#: isolation, non-disclosure, role-monotonicity and write-gate properties so a new
#: endpoint is covered by all of them at once.
TENANT_SCOPED_ENDPOINTS = [
    ("core:me", False, ["get", "patch"]),
    ("core:gym-detail", False, ["get", "patch"]),
    ("core:trainer-list", False, ["get", "post"]),
    ("core:member-list", False, ["get", "post"]),
    ("core:member-detail", True, ["get", "patch"]),
    ("core:membership-plan-list", False, ["get", "post"]),
    ("core:membership-plan-detail", True, ["get", "patch"]),
    ("core:invoice-list", False, ["get"]),
    ("core:invoice-detail", True, ["get"]),
    ("core:invoice-pay", True, ["post"]),
    ("core:payment-receipt", True, ["get"]),
]

#: Endpoints that take no path argument, so a test can hit them without seeding an id.
SIMPLE_TENANT_ENDPOINTS = [
    (name, methods) for name, needs_pk, methods in TENANT_SCOPED_ENDPOINTS if not needs_pk
]


def tenant_scoped_endpoints(*, with_pk=None):
    """Endpoint descriptors. `with_pk=False` yields only the argument-free ones."""
    pool = TENANT_SCOPED_ENDPOINTS
    if with_pk is True:
        pool = [row for row in TENANT_SCOPED_ENDPOINTS if row[1]]
    elif with_pk is False:
        pool = [row for row in TENANT_SCOPED_ENDPOINTS if not row[1]]
    return st.sampled_from(pool)


def http_methods(*, unsafe_only=False, safe_only=False):
    safe = ["get", "head", "options"]
    unsafe = ["post", "patch", "put", "delete"]
    if unsafe_only:
        return st.sampled_from(unsafe)
    if safe_only:
        return st.sampled_from(safe)
    return st.sampled_from(safe + unsafe)


# ============ GATEWAY ============

@st.composite
def gateway_events(draw, *, order_ref=None, kind=None):
    """A webhook payload shaped like a real Razorpay delivery.

    Half the drawn events carry card-data keys, so every consumer of this strategy
    also proves the stripping rule rather than needing a separate test for it.
    """
    from core.services.gateway import EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_FAILED
    from core.tests.fakes import build_event_payload

    return build_event_payload(
        event_id=draw(
            st.text(alphabet="abcdef0123456789", min_size=8, max_size=16).map(
                lambda tail: f"evt_{tail}"
            )
        ),
        kind=kind or draw(st.sampled_from([EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_FAILED])),
        order_ref=order_ref,
        payment_ref=draw(
            st.text(alphabet="abcdef0123456789", min_size=8, max_size=14).map(
                lambda tail: f"pay_{tail}"
            )
        ),
        method=draw(st.sampled_from(["upi", "card", "netbanking", "wallet"])),
        amount_minor=draw(st.integers(min_value=1, max_value=10_000_000)),
        currency="INR",
        include_card_data=draw(st.booleans()),
    )


def delivery_counts():
    """How many times a webhook is delivered. 1 is the normal case; more is the test."""
    return st.integers(min_value=1, max_value=5)


def gateway_failure_modes():
    from core.tests.fakes import FAILURE_MODES

    return st.sampled_from([mode for mode in FAILURE_MODES if mode is not None])
