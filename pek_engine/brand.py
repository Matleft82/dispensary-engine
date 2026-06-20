"""Brand normalization and alias resolution (spec sections 7, 8)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from . import text_clean


def _brand_key(name: str) -> str:
    """Normalized brand key: lowercase, strip punctuation/apostrophes/space."""
    s = text_clean.normalize_unicode(name or "").lower()
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _display(name: str) -> str:
    return re.sub(r"\s+", " ", text_clean.normalize_unicode(name or "")).strip()


class BrandResolver:
    """Resolves raw brand strings to canonical brands using a seed alias table."""

    def __init__(self) -> None:
        # normalized_key -> (canonical_name, brand_id)
        self._alias: dict[str, tuple[str, str]] = {}
        # set of canonical keys (for title-prefix detection)
        self._canonical_keys: set[str] = set()
        self.suggestions: dict[str, dict] = {}

    @classmethod
    def from_seed_csv(cls, csv_path: str | Path) -> "BrandResolver":
        resolver = cls()
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                canonical = _display(row.get("canonical_brand", ""))
                if not canonical:
                    continue
                resolver._register(canonical, canonical)
                raw_aliases = row.get("aliases") or ""
                for alias in raw_aliases.split("|"):
                    alias = _display(alias)
                    if alias:
                        resolver._register(alias, canonical)
        return resolver

    def _register(self, alias: str, canonical: str) -> None:
        key = _brand_key(alias)
        if not key:
            return
        brand_id = "brand_" + _brand_key(canonical).replace(" ", "_")
        self._alias[key] = (canonical, brand_id)
        self._canonical_keys.add(_brand_key(canonical))

    def resolve(self, source_brand: str | None) -> dict:
        """Resolve a raw brand string.

        Returns dict with normalized_brand, brand_id, brand_confidence,
        alias_type, known (bool).
        """
        raw = _display(source_brand or "")
        if not raw:
            return {
                "normalized_brand": None, "brand_id": None,
                "brand_confidence": 0.0, "alias_type": None, "known": False,
            }

        key = _brand_key(raw)
        if key in self._alias:
            canonical, brand_id = self._alias[key]
            # exact canonical match vs alias formatting variant
            confidence = 1.0 if _brand_key(canonical) == key else 0.97
            alias_type = "approved" if confidence < 1.0 else "canonical"
            return {
                "normalized_brand": canonical, "brand_id": brand_id,
                "brand_confidence": confidence, "alias_type": alias_type,
                "known": True,
            }

        # Unknown brand: keep a cleaned display form, flag as a suggestion.
        cleaned = _display(raw)
        self.suggestions.setdefault(key, {
            "raw_brand_value": raw,
            "normalized_raw_value": key,
            "suggested_canonical": cleaned,
            "approval_status": "needs_review",
            "alias_type": "new_brand",
            "count": 0,
            "example_titles": [],
        })
        self.suggestions[key]["count"] += 1
        return {
            "normalized_brand": cleaned,
            "brand_id": "brand_" + key.replace(" ", "_"),
            "brand_confidence": 0.6, "alias_type": "new_brand", "known": False,
        }

    def lookup_known(self, candidate: str) -> tuple[str, str] | None:
        """Return (canonical, brand_id) if candidate matches a known brand."""
        key = _brand_key(candidate)
        if key in self._alias:
            return self._alias[key]
        return None

    def add_suggestion_example(self, source_brand: str | None, title: str) -> None:
        key = _brand_key(_display(source_brand or ""))
        s = self.suggestions.get(key)
        if s is not None and len(s["example_titles"]) < 5:
            s["example_titles"].append(title)
