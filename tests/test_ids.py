import random
import re
from datetime import date

from socklock import ids


def test_generation_and_variant_id_format():
    generation_id = ids.new_generation_id(date(2026, 11, 9), random.Random(1))
    assert re.fullmatch(r"SLM-20261109-[A-Z2-9]{4}", generation_id)
    variant = ids.variant_id(generation_id, 3)
    assert variant == generation_id + "-v3"
    assert ids.generation_id_of(variant) == generation_id
    assert ids.find_variant_id(variant) == variant


def test_ids_are_random():
    rng = random.Random(42)
    made = {ids.new_generation_id(date(2026, 11, 9), rng) for _ in range(200)}
    assert len(made) > 190


def test_find_variant_id_inside_ad_names():
    assert ids.find_variant_id("UGC laundry | SLM-20261109-K7QX-v3 | US | 9x16") == "SLM-20261109-K7QX-v3"
    assert ids.find_variant_id("ugc_SLM-20261109-K7QX-v12_1x1") == "SLM-20261109-K7QX-v12"
    # lower case and leading zero are normalized
    assert ids.find_variant_id("slm-20261109-k7qx-V03 copy") == "SLM-20261109-K7QX-v3"


def test_no_id_means_control():
    assert ids.find_variant_id("CTRL laundry-pile mod-11 | US") is None
    assert ids.find_variant_id("") is None
    assert ids.find_variant_id(None) is None
    assert ids.find_variant_id("SLM-2026-K7QX-v1") is None        # date too short
    assert ids.find_variant_id("XSLM-20261109-K7QX-v1") is None   # part of a longer word
    assert ids.find_variant_id("SLM-20261109-K7QX") is None       # generation id, no variant
