"""Matching: exact-PEK grouping, hard-gate near-match analysis, scoring.

Strategy (spec sections 19-24):
  * DPLs with an identical PEK collapse into one MCP (exact_pek).
  * Within a (brand, category, product) bucket, distinct PEKs are compared.
    A hard-gate conflict (extract/hardware/infusion) becomes a rejected
    near-match. A missing-field difference becomes a review candidate.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from . import embeddings
from . import mcp as mcp_mod
from .models import (
    DataQualityFlag,
    ELIGIBLE,
    MCP,
    MCPDPLLink,
    NormalizedDPL,
    ReviewItem,
)
from .text_clean import normalize_key_token as tok


def _link(mcp_id: str, dpl: NormalizedDPL, method: str, confidence: float,
          reasons: list[str], needs_review: bool) -> MCPDPLLink:
    return MCPDPLLink(
        link_id="link_" + uuid.uuid4().hex[:16],
        mcp_id=mcp_id,
        dpl_id=dpl.dpl_id,
        match_confidence=confidence,
        match_method=method,
        match_reasons=reasons,
        needs_review=needs_review,
    )


def _review(issue_type: str, risk: str, dpls: list[NormalizedDPL],
            mcp_ids: list[str], reason: str, action: str,
            batch_id: str) -> ReviewItem:
    return ReviewItem(
        review_id="rev_" + uuid.uuid4().hex[:16],
        batch_id=batch_id,
        issue_type=issue_type,
        risk_level=risk,
        dpl_ids=[d.dpl_id for d in dpls],
        candidate_mcp_ids=mcp_ids,
        source_titles_compared=[d.source_product_title for d in dpls],
        reason_for_review=reason,
        recommended_action=action,
    )


def build_mcps(eligible: list[NormalizedDPL], batch_id: str, now: str):
    """Group eligible DPLs by PEK into MCPs and links."""
    by_pek: dict[str, list[NormalizedDPL]] = defaultdict(list)
    for d in eligible:
        by_pek[d.proposed_pek].append(d)

    mcps: list[MCP] = []
    links: list[MCPDPLLink] = []
    for pek, dpls in by_pek.items():
        mcp = mcp_mod.build_mcp(pek, dpls, now)
        mcps.append(mcp)
        method = "exact_pek" if len(dpls) > 1 else "provisional_new_mcp"
        for d in dpls:
            needs_review = bool([n for n in d.source_notes if "missing" in n]) \
                or d.extraction_confidence < 0.6
            reasons = ["exact_pek_match"] if len(dpls) > 1 else ["new_pek"]
            if needs_review:
                reasons.extend(d.source_notes)
            links.append(_link(mcp.mcp_id, d, method, d.extraction_confidence,
                               reasons, needs_review))
    return mcps, links, by_pek


# --- hard-gate comparison of two PEK-distinct products in the same bucket ---

def _classify_conflict(a: MCP, b: MCP) -> tuple[str, str, str] | None:
    """Return (kind, issue_type, recommended_action) for two same-bucket MCPs.

    kind is 'rejected' (must not merge) or 'review' (possibly same product).
    """
    if (a.extract_type or "") != (b.extract_type or ""):
        if a.extract_type and b.extract_type:
            return ("rejected", "extract_type_conflict", "do_not_merge")
        return ("review", "missing_critical_data", "confirm_extract_type")
    if (a.hardware_type or "") != (b.hardware_type or ""):
        if a.hardware_type and b.hardware_type:
            return ("rejected", "hardware_conflict", "do_not_merge")
        return ("review", "missing_critical_data", "confirm_hardware")
    if (a.infusion_type or "") != (b.infusion_type or ""):
        if a.infusion_type and b.infusion_type:
            return ("rejected", "infusion_type_conflict", "do_not_merge")
        return ("review", "missing_critical_data", "confirm_infusion")
    if (a.normalized_size or "") != (b.normalized_size or ""):
        if a.normalized_size and b.normalized_size:
            return ("rejected", "size_conflict", "do_not_merge")
        return ("review", "missing_size", "confirm_size")
    if (a.count or 0) != (b.count or 0):
        if a.count and b.count:
            return ("rejected", "size_conflict", "do_not_merge")
        return ("review", "missing_critical_data", "confirm_count")
    ratio_a, ratio_b = a.ratio or "", b.ratio or ""
    prof_a, prof_b = a.cannabinoid_profile or "", b.cannabinoid_profile or ""
    # Only a hard reject when both sides state a different numeric ratio.
    if ratio_a and ratio_b and ratio_a != ratio_b:
        return ("rejected", "ratio_conflict", "do_not_merge")
    # A blank ratio/profile on one side is missing data, not a conflict.
    if ratio_a != ratio_b or prof_a != prof_b:
        return ("review", "missing_critical_data", "confirm_ratio_or_profile")
    return None


def analyze_near_matches(mcps: list[MCP], rep_dpl: dict[str, NormalizedDPL],
                         batch_id: str):
    """Find same-product near-matches across distinct PEKs.

    Buckets by (brand, category, product). Same identity but different PEK =>
    a structured review or rejected near-match record.
    """
    reviews: list[ReviewItem] = []
    rejected: list[dict] = []
    alias_suggestions: dict[str, dict] = {}

    bucket: dict[tuple, list[MCP]] = defaultdict(list)
    for m in mcps:
        key = (tok(m.normalized_brand), m.normalized_category,
               tok(m.canonical_product_name))
        bucket[key].append(m)

    for key, group in bucket.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                verdict = _classify_conflict(a, b)
                if verdict is None:
                    continue
                kind, issue, action = verdict
                da, db = rep_dpl[a.mcp_id], rep_dpl[b.mcp_id]
                if kind == "rejected":
                    rejected.append({
                        "rejected_match_id": "rej_" + uuid.uuid4().hex[:16],
                        "mcp_id_1": a.mcp_id, "mcp_id_2": b.mcp_id,
                        "title_1": a.canonical_title, "title_2": b.canonical_title,
                        "why_they_look_similar": "same brand + category + product name",
                        "why_they_should_not_match": issue,
                        "rule_learned": f"{issue}: do not merge across this difference",
                        "confidence": 0.95,
                    })
                else:
                    reviews.append(_review(
                        issue, "medium", [da, db], [a.mcp_id, b.mcp_id],
                        f"Same brand/category/product but {issue} between PEKs.",
                        action, batch_id))

    # Embeddings recall layer: surface close MCPs the exact-product bucket
    # missed (typos, reorders, "Blueberry 2.0" vs "Blueberry #2"). Gated:
    # every pair still passes through _classify_conflict, so a hard conflict
    # (different size/extract/etc.) is NOT proposed as a merge.
    seen_pairs: set[frozenset] = set()
    for a, b, sim in embeddings.candidate_pairs(
            mcps,
            key_fn=lambda m: (tok(m.normalized_brand), m.normalized_category),
            text_fn=lambda m: m.canonical_product_name or m.search_title,
            threshold=0.80):
        pair = frozenset((a.mcp_id, b.mcp_id))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        verdict = _classify_conflict(a, b)
        same_product = tok(a.canonical_product_name) == tok(b.canonical_product_name)
        if verdict is not None and verdict[0] == "rejected":
            # Embeddings think they're close, but a hard gate says no. Trust
            # the gate; do not propose a merge.
            continue
        if same_product:
            continue  # already handled by the exact-product bucket above
        sid = tok(a.normalized_brand) + "|" + tok(a.canonical_product_name) \
            + "|" + tok(b.canonical_product_name)
        alias_suggestions[sid] = {
            "brand": a.normalized_brand, "category": a.normalized_category,
            "value_a": a.canonical_product_name,
            "value_b": b.canonical_product_name,
            "similarity": sim, "method": "char_ngram_embedding",
            "approval_status": "needs_review", "scope": "brand_specific",
        }
        da, db = rep_dpl[a.mcp_id], rep_dpl[b.mcp_id]
        reviews.append(_review(
            "possible_product_alias", "low", [da, db], [a.mcp_id, b.mcp_id],
            f"Embedding similarity {sim} between product names; possible alias.",
            "confirm_or_reject_alias", batch_id))

    return reviews, rejected, alias_suggestions


def data_quality_flags(dpls: list[NormalizedDPL], batch_id: str) -> list[DataQualityFlag]:
    flags: list[DataQualityFlag] = []
    note_to_problem = {
        "missing_size": ("missing_size", "No parseable size/weight"),
        "missing_mg": ("missing_mg", "No parseable milligram potency"),
        "missing_product_identity": ("title_too_generic", "Could not extract product identity"),
        "missing_extract_type": ("missing_extract_type", "Extract type required for category but absent"),
        "unmapped_category": ("possible_wrong_source_category", "Category could not be mapped"),
    }
    for d in dpls:
        if d.comparison_status != ELIGIBLE:
            continue
        if not d.normalized_brand:
            flags.append(DataQualityFlag(
                "flag_" + uuid.uuid4().hex[:16], batch_id, d.dpl_id,
                d.source_dispensary, "missing_brand",
                "No brand resolved from source or title", "manual brand review", 0.8))
        for note in d.source_notes:
            if note in note_to_problem:
                ptype, desc = note_to_problem[note]
                flags.append(DataQualityFlag(
                    "flag_" + uuid.uuid4().hex[:16], batch_id, d.dpl_id,
                    d.source_dispensary, ptype, desc, None, 0.7))
    return flags
