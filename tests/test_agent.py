"""Product agent tests: gating + write-back."""

from __future__ import annotations

import json

from pek_engine.agent import ProductAgent, summarize
from pek_engine.agent import contract as C
from pek_engine.agent.backends import HeuristicBackend, LLMBackend


def test_brand_alias_auto_approves_high_similarity():
    a = ProductAgent()
    decs = a.review_brand_suggestions([{
        "raw_brand_value": "Botanist", "closest_approved_brand": "The Botanist",
        "closest_approved_similarity": 0.95, "count": 66,
        "normalized_raw_value": "botanist"}])
    d = decs[0]
    assert d.verdict == C.APPROVE
    assert d.requires_human is False
    assert d.writes_to == "brand_aliases"


def test_brand_alias_low_similarity_needs_human():
    a = ProductAgent()
    decs = a.review_brand_suggestions([{
        "raw_brand_value": "Totally New Co", "closest_approved_brand": None,
        "closest_approved_similarity": None, "count": 1}])
    assert decs[0].requires_human is True
    assert decs[0].verdict == C.NEEDS_HUMAN


def test_hard_conflict_review_is_rejected_never_merged():
    a = ProductAgent()
    decs = a.review_queue([{
        "review_id": "r1", "issue_type": "extract_type_conflict",
        "candidate_mcp_ids": ["m1", "m2"],
        "source_titles_compared": ["Live Resin Cart", "Distillate Cart"]}])
    d = decs[0]
    assert d.kind == C.REJECT
    assert d.writes_to == "rejected_matches"
    assert d.verdict == C.REJECT_V


def test_apply_writes_only_auto_approved(tmp_path):
    a = ProductAgent()
    decs = (
        a.review_brand_suggestions([{
            "raw_brand_value": "Botanist", "closest_approved_brand": "The Botanist",
            "closest_approved_similarity": 0.95, "count": 66}])
        + a.review_queue([{"review_id": "r1", "issue_type": "extract_type_conflict",
                           "candidate_mcp_ids": ["m1", "m2"],
                           "source_titles_compared": ["a", "b"]}])
        + a.review_queue([{"review_id": "r2", "issue_type": "missing_critical_data",
                           "candidate_mcp_ids": ["m3", "m4"],
                           "source_titles_compared": ["c", "d"]}])
    )
    applied = a.apply(decs, tmp_path)
    assert applied["brand_aliases"] == 1
    assert applied["rejected_matches"] == 1
    # the missing-data item requires a human and must NOT be written
    assert (tmp_path / "brand_aliases_approved.csv").exists()


def test_llm_backend_falls_back_on_bad_output():
    def bad_llm(prompt: str) -> str:
        return "not json"
    backend = LLMBackend(bad_llm, fallback=HeuristicBackend())
    verdict, conf, rationale, ev = backend.grade(
        C.PRODUCT_ALIAS, {"value_a": "Mango", "value_b": "Mango", "similarity": 0.99})
    assert verdict == C.APPROVE  # fell back to heuristic
    assert "fallback" in rationale.lower()


def test_summarize_counts():
    a = ProductAgent()
    decs = a.review_product_suggestions([
        {"brand": "X", "value_a": "Blue Dream", "value_b": "Blue Dream 2", "similarity": 0.99},
        {"brand": "X", "value_a": "Foo", "value_b": "Bar", "similarity": 0.5},
    ])
    s = summarize(decs)
    assert s["total"] == 2
    assert s["auto_approved"] >= 1
