"""Optional embeddings recall layer (suggestion-only, gated).

Philosophy: *embeddings propose, hard gates dispose.* This module only
surfaces candidate pairs the deterministic PEK path may have missed; it never
auto-merges. Every candidate it produces is still subject to the hard gates in
`matching._classify_conflict` before a human ever sees a "merge" suggestion.

Default backend is a dependency-free hashed character-n-gram vector with cosine
similarity (offline, deterministic). The `Embedder` interface lets a stronger
model (e.g. sentence-transformers) be dropped in later without touching callers.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from .text_clean import fold_accents, normalize_unicode

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _prep(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(fold_accents(normalize_unicode(text or "")).lower()))


class CharNgramEmbedder:
    """Hashed char-n-gram TF vector + cosine. No external dependencies."""

    def __init__(self, n: int = 3) -> None:
        self.n = n

    def embed(self, text: str) -> dict[str, float]:
        s = f" {_prep(text)} "
        if len(s) <= self.n:
            grams = [s.strip()] if s.strip() else []
        else:
            grams = [s[i:i + self.n] for i in range(len(s) - self.n + 1)]
        vec: dict[str, float] = defaultdict(float)
        for g in grams:
            vec[g] += 1.0
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    @staticmethod
    def similarity(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(g, 0.0) for g, w in a.items())


def candidate_pairs(items: list, key_fn, text_fn, embedder=None,
                    threshold: float = 0.78):
    """Yield (item_a, item_b, similarity) for same-bucket items whose embedded
    text similarity >= threshold and < 1.0 (distinct but close).

    `key_fn` buckets items conservatively (e.g. brand+category) so we never
    compare across unrelated products and stay tractable (no global O(n^2)).
    """
    embedder = embedder or CharNgramEmbedder()
    buckets: dict[object, list] = defaultdict(list)
    for it in items:
        buckets[key_fn(it)].append(it)

    for group in buckets.values():
        if len(group) < 2:
            continue
        vecs = [embedder.embed(text_fn(it)) for it in group]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                sim = embedder.similarity(vecs[i], vecs[j])
                if threshold <= sim < 1.0:
                    yield group[i], group[j], round(sim, 3)
