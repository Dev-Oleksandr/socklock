"""Variant IDs like SLM-20261109-K7QX-v3. Designers paste them into the Meta ad name."""
import random
import re
from datetime import date

# No 0/O/1/I, so a designer can read and retype the ID without mistakes.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Finds a variant ID anywhere inside an ad name, e.g. "UGC | SLM-20261109-K7QX-v3 | 9x16".
# The look-arounds stop us from matching inside a longer word or number.
VARIANT_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])SLM-(\d{8})-([A-Za-z0-9]{4})-v(\d+)(?![0-9])",
    re.IGNORECASE,
)


def new_generation_id(day=None, rng=random):
    """'SLM-<yyyymmdd>-<4 random chars>'. One ID per generate run."""
    day = day or date.today()
    suffix = "".join(rng.choice(ALPHABET) for _ in range(4))
    return f"SLM-{day:%Y%m%d}-{suffix}"


def variant_id(generation_id, n):
    """'SLM-20261109-K7QX' + 3 -> 'SLM-20261109-K7QX-v3'"""
    return f"{generation_id}-v{n}"


def generation_id_of(variant):
    """'SLM-20261109-K7QX-v3' -> 'SLM-20261109-K7QX'"""
    return variant.rsplit("-v", 1)[0]


def find_variant_id(ad_name):
    """Return the variant ID inside an ad name (normalized), or None for a control ad."""
    match = VARIANT_ID_RE.search(ad_name or "")
    if match is None:
        return None
    day, suffix, n = match.groups()
    return f"SLM-{day}-{suffix.upper()}-v{int(n)}"
