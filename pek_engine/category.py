"""Category canonicalization to the minimal bucket set (spec sections 5, 29)."""

from __future__ import annotations

from . import rules, text_clean


def _match_category(text: str) -> str | None:
    """Return canonical category for the longest matching keyword in text."""
    text = (text or "").lower()
    best = None
    best_len = 0
    for keyword, canonical in rules.CATEGORY_MAP.items():
        if keyword in text and len(keyword) > best_len:
            best = canonical
            best_len = len(keyword)
    return best


def canonical_category(raw_category: str | None, raw_subcategory: str | None,
                       raw_title: str | None) -> tuple[str | None, list[str]]:
    """Fold raw category/subcategory/title into a canonical category.

    Priority: explicit category, then subcategory, then title keywords.
    Title can resolve when category/subcategory are blank or unmapped.
    """
    evidence: list[str] = []
    search = text_clean.search_title(raw_title or "")

    by_cat = _match_category(raw_category or "")
    by_sub = _match_category(raw_subcategory or "")
    by_title = _match_category(search)

    # Strong, unambiguous title signals that should override a coarse category.
    if "hash hole" in search or "hash-hole" in search or "hashhole" in search:
        evidence.append("title:hash_hole->Pre-Rolls")
        return "Pre-Rolls", evidence
    if "rso" in search:
        evidence.append("title:rso->Concentrates")
        return "Concentrates", evidence

    for label, value in (("category", by_cat), ("subcategory", by_sub), ("title", by_title)):
        if value:
            evidence.append(f"{label}:{value}")

    result = by_cat or by_sub or by_title
    return result, evidence
