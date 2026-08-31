"""Gym slug derivation.

A slug is derived from the business name, never supplied by the client, so two
gyms cannot race for a name that looks available in the UI.
"""
import re
import unicodedata

MAX_SLUG_LENGTH = 60
MAX_COLLISION_ATTEMPTS = 50
FALLBACK_BASE = "gym"


class SlugExhausted(Exception):
    """Raised when every candidate within the attempt budget is taken."""


def slugify_business_name(name):
    """Transliterate to ASCII, lowercase, collapse separators, trim to length.

    Falls back to "gym" when the name contains nothing that survives
    transliteration (for example a name written entirely in emoji).
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not hyphenated:
        return FALLBACK_BASE
    return hyphenated[:MAX_SLUG_LENGTH].strip("-")


def derive_unique_slug(name, exists):
    """Return a slug not already taken, per the case-insensitive `exists` callable.

    `exists` receives a candidate slug and returns True when it is taken. The
    first candidate is the bare base; collisions append -2, -3, ... with the base
    truncated so every candidate stays inside the 60 character limit.
    """
    base = slugify_business_name(name)
    if not exists(base):
        return base

    for suffix in range(2, MAX_COLLISION_ATTEMPTS + 2):
        tail = f"-{suffix}"
        trimmed = base[: MAX_SLUG_LENGTH - len(tail)].strip("-") or FALLBACK_BASE
        candidate = f"{trimmed}{tail}"
        if not exists(candidate):
            return candidate

    raise SlugExhausted(
        f"Could not derive a free slug for {name!r} within "
        f"{MAX_COLLISION_ATTEMPTS} attempts."
    )
