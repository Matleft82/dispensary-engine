"""Extract type and infusion type normalization (spec sections 13, 14).

These are matching-critical. Live Resin != Live Rosin, Rosin != Resin,
Uninfused != Infused, and Unknown extract != a known extract.
"""

from __future__ import annotations

from . import rules

# Extract type matters for matching in these categories.
_EXTRACT_CATEGORIES = {"Vapes", "Concentrates"}


def detect_extract(text: str) -> str | None:
    """Return the most specific extract type found, else None."""
    for canonical, keywords in rules.EXTRACT_PATTERNS:
        for kw in keywords:
            if kw in text:
                return canonical
    return None


def resolve_extract(category: str | None, text: str) -> str | None:
    extract = detect_extract(text)
    if category in _EXTRACT_CATEGORIES:
        return extract  # None means Unknown (blocks auto-match with a known type)
    # Flower/edibles etc: extract not identity-critical; only report if present.
    return extract


def resolve_infusion(category: str | None, text: str) -> str | None:
    """Infusion type, primarily for pre-rolls and infused flower."""
    t = text or ""

    if category not in ("Pre-Rolls", "Flower"):
        return None

    for marker in rules.NON_INFUSED_MARKERS:
        if marker in t:
            return "None"

    if "infused" in t or category == "Pre-Rolls":
        specific = None
        for canonical, keywords in rules.INFUSION_PATTERNS:
            for kw in keywords:
                if kw in t:
                    specific = canonical
                    break
            if specific:
                break
        if specific:
            return specific
        # Pre-roll with no infusion signal -> treat as uninfused.
        if category == "Pre-Rolls":
            return "None"

    return None


def concentrate_subform(extract_type: str | None, current_subform: str | None) -> str | None:
    """For concentrates, the extract type often is the sellable subform."""
    if current_subform:
        return current_subform
    if extract_type in rules.CONCENTRATE_FORM_FROM_EXTRACT:
        return extract_type
    return None
