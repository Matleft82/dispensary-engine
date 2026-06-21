"""Cannabis eligibility gate (spec section 4).

Accessories/merch/non-cannabis stay in raw inventory but never create a
cannabis PEK or MCP.
"""

from __future__ import annotations

from . import rules, text_clean
from .models import (
    EXCLUDED_ACCESSORY,
    EXCLUDED_MERCH,
    EXCLUDED_NON_CANNABIS,
    ELIGIBLE,
)


def classify(raw_category: str | None, raw_subcategory: str | None,
             raw_title: str | None) -> str:
    """Return a comparison_status: eligible_cannabis or an excluded_* value."""
    cat = (raw_category or "").lower().strip()
    sub = (raw_subcategory or "").lower().strip()

    for keyword, status in rules.EXCLUDED_CATEGORY_KEYWORDS.items():
        if keyword in cat or keyword in sub:
            return status

    search = text_clean.search_title(raw_title or "")
    for keyword in rules.EXCLUDED_TITLE_KEYWORDS:
        # Only exclude on title when category is unhelpful; keep it conservative.
        if keyword in search and not _looks_cannabis(cat, sub):
            return EXCLUDED_NON_CANNABIS

    return ELIGIBLE


def _looks_cannabis(cat: str, sub: str) -> bool:
    for keyword in rules.CATEGORY_MAP:
        if keyword in cat or keyword in sub:
            return True
    return False
