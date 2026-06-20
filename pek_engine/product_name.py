"""Product name / strain / flavor extraction (spec section 9).

The identity is what's left after removing brand, size, form, extract,
infusion, hardware, potency, and descriptor words. This is where the
"descriptor leaked into identity" defect (e.g. 'Angie Sativa/Hybrid Wax
Budder' vs 'Angie Wax Budder') is fixed.
"""

from __future__ import annotations

import re

from . import rules, text_clean


def _build_strip_phrases() -> list[str]:
    phrases: set[str] = set()
    for _, kws in rules.HARDWARE_PATTERNS:
        phrases.update(kws)
    for _, kws in rules.FLOWER_SUBFORMS:
        phrases.update(kws)
    for _, kws in rules.PREROLL_SUBFORMS:
        phrases.update(kws)
    for _, kws in rules.EDIBLE_FORM_PATTERNS:
        phrases.update(kws)
    for _, kws in rules.EXTRACT_PATTERNS:
        phrases.update(kws)
    for _, kws in rules.INFUSION_PATTERNS:
        phrases.update(kws)
    phrases.update(rules.NON_INFUSED_MARKERS)
    phrases.update(k.lower() for k in rules.CATEGORY_MAP)
    # only strip multi-word / unambiguous phrases here; single tokens handled later
    return sorted((p for p in phrases if " " in p or "-" in p), key=len, reverse=True)


_STRIP_PHRASES = _build_strip_phrases()

_SIZE_PATTERNS = [
    r"\d+\s*x\s*\d+\s*mg",
    r"\d+(?:\.\d+)?\s*mg(?:\s*(?:thc|cbd|cbn|cbg|cbc))?",
    r"\d+(?:\.\d+)?\s*(?:g|gram|grams|gm|oz|ounce|ounces|ml)\b",
    r"\d+\s*(?:pk|pack|packs|-pack|ct|count|pc|pcs|piece|pieces)\b",
    r"\b\d+/\d+\s*(?:oz)?\b",
    r"\b\d+\s*:\s*\d+\b",
    r"\d+(?:\.\d+)?\s*%",
    r"\b510\b",
    r"\bthc\b", r"\bcbd\b", r"\bcbn\b", r"\bcbg\b", r"\bcbc\b",
]


def extract_product_name(search_title: str, source_brand: str | None,
                         normalized_brand: str | None) -> tuple[str | None, float]:
    """Return (normalized_product_name, extraction_confidence)."""
    t = f" {search_title} "

    # remove brand mentions (source + canonical)
    for brand in {source_brand, normalized_brand}:
        if brand:
            b = text_clean.search_title(brand)
            if b:
                t = re.sub(rf"\b{re.escape(b)}\b", " ", t)

    # remove size / potency tokens
    for pat in _SIZE_PATTERNS:
        t = re.sub(pat, " ", t)

    # remove known multi-word phrases (forms, extracts, infusions, categories)
    for phrase in _STRIP_PHRASES:
        t = re.sub(rf"\b{re.escape(phrase)}\b", " ", t)

    # tokenize and drop descriptors, single category/form tokens, bare numbers
    tokens = re.findall(r"[a-z0-9'./#+]+", t)
    keep: list[str] = []
    for tok in tokens:
        if tok in rules.DESCRIPTOR_WORDS:
            continue
        # Keep numeric tokens — they are often identity (Mac 1, Gelato 33,
        # Blueberry 2.0). Size/potency numbers were already stripped above.
        if len(tok) == 1 and not tok.isdigit() and tok not in ("z",):
            continue
        keep.append(tok)

    # collapse duplicate consecutive tokens
    deduped: list[str] = []
    for tok in keep:
        if not deduped or deduped[-1] != tok:
            deduped.append(tok)

    if not deduped:
        return None, 0.1

    name = " ".join(deduped)
    name = re.sub(r"\s+", " ", name).strip(" -.")
    display = _title_case(name)

    confidence = 0.9 if len(deduped) <= 6 else 0.6
    if len(deduped) == 1 and len(deduped[0]) <= 2:
        confidence = 0.3
    return display, confidence


def _title_case(name: str) -> str:
    def cap(word: str) -> str:
        if word.isupper():
            return word
        return word[:1].upper() + word[1:] if word else word
    return " ".join(cap(w) for w in name.split())
