"""Feature: gym-saas-core, Property 7."""
import re
import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from core.services.slugs import (
    FALLBACK_BASE,
    MAX_SLUG_LENGTH,
    derive_unique_slug,
    slugify_business_name,
)
from core.tests.strategies import collision_counts, unicode_business_names

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# Feature: gym-saas-core, Property 7: For any Unicode business name string, the
# derived Gym slug matches ^[a-z0-9]+(-[a-z0-9]+)*$, is at most 60 characters,
# equals `gym` as its derivation base when the transliterated name is empty, and for
# any number k of pre-existing colliding slugs with 1 <= k <= 49, the derived slug is
# unique across Gyms compared case-insensitively and still at most 60 characters.
# Validates: Requirements 1.9, 1.10, 1.11, 1.4
@settings(max_examples=500)
@given(name=unicode_business_names(), k=collision_counts())
def test_slug_derivation_is_well_formed_and_collision_free(name, k):
    base = slugify_business_name(name)

    # Well-formed and bounded, for any input at all.
    assert SLUG_PATTERN.match(base), f"{base!r} from {name!r}"
    assert 1 <= len(base) <= MAX_SLUG_LENGTH

    # A name that transliterates to nothing falls back to the literal `gym`.
    ascii_survivors = re.sub(r"[^a-z0-9]+", "", base)
    transliterated = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    if not re.sub(r"[^a-z0-9]+", "", transliterated):
        assert base == FALLBACK_BASE
    assert ascii_survivors  # never an empty or hyphen-only slug

    # Simulate k prior collisions, compared case-insensitively as the DB does.
    taken = {base.upper()}
    for suffix in range(2, 2 + k - 1):
        taken.add(f"{base[: MAX_SLUG_LENGTH - len(str(suffix)) - 1].strip('-') or FALLBACK_BASE}-{suffix}".upper())

    derived = derive_unique_slug(name, lambda candidate: candidate.upper() in taken)

    assert SLUG_PATTERN.match(derived), derived
    assert len(derived) <= MAX_SLUG_LENGTH
    assert derived.upper() not in taken


@settings(max_examples=500)
@given(name=unicode_business_names())
def test_derivation_is_deterministic(name):
    """Same input, same slug: the base must not depend on ordering or randomness."""
    assert slugify_business_name(name) == slugify_business_name(name)


@given(name=st.just("Iron Pit"))
def test_first_candidate_is_the_bare_base_when_free(name):
    assert derive_unique_slug(name, lambda candidate: False) == "iron-pit"
