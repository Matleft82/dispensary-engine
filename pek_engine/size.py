"""Size / weight / count normalization (spec section 11).

Weights normalize to grams for flower/pre-roll/vape/concentrate. Counts and
per-unit/total weights are parsed for pre-roll packs.
"""

from __future__ import annotations

import re

OZ_TO_G = 28.0

WORD_GRAMS = {
    "eighth": 3.5,
    "quarter": 7.0,
    "half ounce": 14.0,
    "half oz": 14.0,
    "ounce": 28.0,
    "half gram": 0.5,
}

FRACTION_OZ = {
    "1/8": 3.5, "1/4": 7.0, "1/2": 14.0, "1/16": 1.75, "1/32": 0.875,
}

_WEIGHT_CATEGORIES = {"Flower", "Pre-Rolls", "Vapes", "Concentrates"}


def _fmt_g(value: float) -> str:
    if value == int(value):
        return f"{int(value)}g"
    return f"{value:g}g"


def parse_grams(text: str) -> float | None:
    """Extract a gram weight from a lowercased text string."""
    t = (text or "").lower()

    # fraction with oz, e.g. "1/8 oz", "1/8oz"
    m = re.search(r"(\d+/\d+)\s*oz", t)
    if m and m.group(1) in FRACTION_OZ:
        return FRACTION_OZ[m.group(1)]

    # explicit grams: "3.5g", "0.5 g", "1 gram", "3.5 grams"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g\b|gram\b|grams\b|gm\b)", t)
    if m:
        return float(m.group(1))

    # explicit oz: "1oz", "1.0 oz"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:oz\b|ounce\b|ounces\b)", t)
    if m:
        return round(float(m.group(1)) * OZ_TO_G, 2)

    # bare fraction "1/8"
    m = re.search(r"\b(\d+/\d+)\b", t)
    if m and m.group(1) in FRACTION_OZ:
        return FRACTION_OZ[m.group(1)]

    # word forms
    for word, grams in WORD_GRAMS.items():
        if word in t:
            return grams

    return None


def parse_count(text: str) -> int | None:
    """Pack/piece count: 5pk, 5-pack, 10ct, 10 count, 2 pack."""
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:pk\b|pack\b|packs\b|-pack\b|ct\b|count\b|pc\b|pcs\b|piece\b|pieces\b)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*x\s*\d", t)  # "10 x 10mg" -> count 10
    if m:
        return int(m.group(1))
    return None


def parse_bare_number_grams(weight_raw: str | None, category: str | None) -> float | None:
    """Interpret a unit-less weight (e.g. '3.5', '1.0') as grams when the
    category is weight-based. Returns None otherwise."""
    if not weight_raw or category not in _WEIGHT_CATEGORIES:
        return None
    s = weight_raw.strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    return None


def resolve_size(category: str | None, search_title: str,
                 weight_raw: str | None) -> dict:
    """Resolve grams, count, unit/total weight, and a normalized_size string.

    For pre-roll packs, computes total weight = unit_weight * count when both
    are known. Never invents a total when only count is present.
    """
    count = parse_count(search_title) or parse_count(weight_raw or "")
    grams = parse_grams(search_title)
    if grams is None:
        grams = parse_grams(weight_raw or "")
    if grams is None:
        grams = parse_bare_number_grams(weight_raw, category)

    unit_weight = None
    total_weight = None
    normalized_size = None

    if category == "Pre-Rolls":
        if grams is not None and count:
            # Ambiguous menus: a gram value <= 1g is almost always per-unit
            # ("5pk 0.5g"); a larger value is almost always the pack total
            # ("5 pack 3g"). Normalize consistently so identical listings match.
            if grams <= 1.0:
                unit_weight = grams
                total_weight = round(grams * count, 3)
            else:
                total_weight = grams
                unit_weight = round(grams / count, 3)
            normalized_size = _fmt_g(total_weight)
        elif grams is not None:
            unit_weight = grams
            total_weight = grams
            normalized_size = _fmt_g(grams)
        # count-only packs leave size blank (spec: do not invent total grams)
    else:
        if grams is not None:
            normalized_size = _fmt_g(grams)

    return {
        "size_value": grams,
        "size_unit": "g" if grams is not None else None,
        "normalized_size": normalized_size,
        "unit_weight_grams": unit_weight,
        "total_weight_grams": total_weight,
        "count": count,
    }
