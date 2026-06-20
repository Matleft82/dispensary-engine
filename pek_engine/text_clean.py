"""Text normalization (spec section 3).

Produces a human display title and a lowercased search title used for parsing.
Never destroys the original source title.
"""

from __future__ import annotations

import re
import unicodedata

from . import rules

# Separators that should become spaces for parsing. In this dataset a lone
# " l " is a pipe artifact (e.g. "Mellow L Blue Raspberry L 10ct Gummies").
_SEPARATORS = ["|", "/", "•", "_", "~", "›", ">"]
_APOSTROPHES = ["\u2019", "\u2018", "\u02bc", "`"]


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for ap in _APOSTROPHES:
        text = text.replace(ap, "'")
    # normalize dashes
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return text


def display_title(raw_title: str) -> str:
    """Readable title: unicode-normalized, collapsed whitespace, kept case."""
    text = normalize_unicode(raw_title or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_decorations(text: str) -> str:
    """Remove menu noise like SALE/NEW/Staff Pick from a lowercased string."""
    for token in rules.DECORATION_TOKENS:
        text = re.sub(rf"\b{re.escape(token)}\b", " ", text)
    return text


def search_title(raw_title: str, strip_noise: bool = True) -> str:
    """Lowercased, separator-cleaned title for parsing/extraction."""
    text = normalize_unicode(raw_title or "").lower()
    # Replace the " l " pipe artifact first (needs surrounding spaces).
    text = re.sub(r"\s+l\s+", " | ", text)
    for sep in _SEPARATORS:
        text = text.replace(sep, " ")
    text = text.replace("|", " ")
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s.:/-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if strip_noise:
        text = strip_decorations(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def segments(raw_title: str) -> list[str]:
    """Split the raw title into pipe/dash-delimited segments (lowercased)."""
    text = normalize_unicode(raw_title or "").lower()
    text = re.sub(r"\s+l\s+", " | ", text)
    for sep in _SEPARATORS:
        text = text.replace(sep, "|")
    parts = [p.strip(" -") for p in text.split("|")]
    return [p for p in parts if p]


def normalize_key_token(text: str) -> str:
    """Collapse a string to a stable key token: lowercase alnum + underscores."""
    text = normalize_unicode(text or "").lower()
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")
