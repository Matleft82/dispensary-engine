"""ProductAgent: turn the engine's uncertain outputs into auditable decisions,
then (optionally) apply approved decisions back into the alias / rejected-match
tables so the deterministic core gets stronger next batch."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from . import contract as C
from .backends import HeuristicBackend

# Review issue types that are hard conflicts -> the agent may only reject/record,
# never merge. Mirrors the engine's hard gates.
_CONFLICT_ISSUES = {
    "extract_type_conflict", "hardware_conflict", "size_conflict",
    "ratio_conflict", "infusion_conflict",
}


class ProductAgent:
    def __init__(self, backend=None, approve_at: float = 0.92) -> None:
        self.backend = backend or HeuristicBackend()
        self.approve_at = approve_at

    # -- adjudication --------------------------------------------------------
    def review_brand_suggestions(self, suggestions: list[dict]) -> list[C.AgentDecision]:
        out = []
        for s in suggestions:
            subject = {
                "raw_brand_value": s.get("raw_brand_value"),
                "closest_approved_brand": s.get("closest_approved_brand"),
                "closest_approved_similarity": s.get("closest_approved_similarity"),
                "count": s.get("count"),
            }
            verdict, conf, rationale, ev = self.backend.grade(C.BRAND_ALIAS, subject)
            out.append(self._mk(C.BRAND_ALIAS, subject, verdict, conf, rationale, ev,
                                writes_to="brand_aliases",
                                source_ref=s.get("normalized_raw_value")))
        return out

    def review_product_suggestions(self, suggestions: list[dict]) -> list[C.AgentDecision]:
        out = []
        for s in suggestions:
            subject = {"brand": s.get("brand"), "value_a": s.get("value_a"),
                       "value_b": s.get("value_b"), "similarity": s.get("similarity")}
            verdict, conf, rationale, ev = self.backend.grade(C.PRODUCT_ALIAS, subject)
            out.append(self._mk(C.PRODUCT_ALIAS, subject, verdict, conf, rationale, ev,
                                writes_to="product_aliases"))
        return out

    def review_queue(self, items: list[dict]) -> list[C.AgentDecision]:
        out = []
        for it in items:
            issue = it.get("issue_type", "")
            subject = {"issue_type": issue, "review_id": it.get("review_id"),
                       "mcp_ids": it.get("candidate_mcp_ids"),
                       "titles": it.get("source_titles_compared")}
            if issue in _CONFLICT_ISSUES:
                out.append(self._mk(
                    C.REJECT, subject, C.REJECT_V, 0.9,
                    f"Hard {issue}: products must not merge.",
                    [issue, "hard_gate"], writes_to="rejected_matches",
                    requires_human=False, source_ref=it.get("review_id")))
            elif issue == "possible_product_alias":
                sim = _sim_from_reason(it.get("reason_for_review", ""))
                subject["similarity"] = sim
                verdict, conf, rationale, ev = self.backend.grade(C.PRODUCT_ALIAS, subject)
                out.append(self._mk(C.PRODUCT_ALIAS, subject, verdict, conf, rationale,
                                    ev, writes_to="product_aliases",
                                    source_ref=it.get("review_id")))
            else:  # missing data etc. -> agent cannot decide alone
                out.append(self._mk(
                    C.FIX_FIELD, subject, C.NEEDS_HUMAN, 0.4,
                    f"{issue or 'uncertain'}: needs human/data, not auto-decidable.",
                    [issue], requires_human=True, source_ref=it.get("review_id")))
        return out

    def _mk(self, kind, subject, verdict, conf, rationale, ev, *,
            writes_to=None, requires_human=None, source_ref=None) -> C.AgentDecision:
        if requires_human is None:
            requires_human = not (verdict == C.APPROVE and conf >= self.approve_at
                                  and kind in (C.BRAND_ALIAS, C.PRODUCT_ALIAS))
        return C.AgentDecision(
            decision_id=C.decision_id(kind, subject), kind=kind, verdict=verdict,
            confidence=round(conf, 3), rationale=rationale, subject=subject,
            evidence=ev, writes_to=writes_to, requires_human=requires_human,
            backend=self.backend.name, source_ref=source_ref)

    def adjudicate_outputs(self, out_dir: str | Path) -> list[C.AgentDecision]:
        out_dir = Path(out_dir)
        decisions: list[C.AgentDecision] = []
        decisions += self.review_brand_suggestions(_load(out_dir / "brand_alias_suggestions.json"))
        decisions += self.review_product_suggestions(_load(out_dir / "product_alias_suggestions.json"))
        decisions += self.review_queue(_load(out_dir / "review_queue.json"))
        return decisions

    # -- write-back (apply approved decisions) -------------------------------
    def apply(self, decisions: list[C.AgentDecision], data_dir: str | Path,
              include_human_pending: bool = False) -> dict:
        """Append auto-approved decisions to the editable tables. Decisions that
        require human approval are skipped unless include_human_pending=True."""
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        applied = {"brand_aliases": 0, "product_aliases": 0, "rejected_matches": 0}
        brand_rows, product_rows, rejected_rows = [], [], []
        for d in decisions:
            if d.requires_human and not include_human_pending:
                continue
            if d.verdict != C.APPROVE and d.kind != C.REJECT:
                continue
            if d.kind == C.BRAND_ALIAS:
                brand_rows.append([d.subject.get("closest_approved_brand"),
                                   d.subject.get("raw_brand_value")])
            elif d.kind == C.PRODUCT_ALIAS:
                product_rows.append([d.subject.get("brand"),
                                     d.subject.get("value_a"),
                                     d.subject.get("value_b")])
            elif d.kind == C.REJECT:
                rejected_rows.append(d.to_dict())
        applied["brand_aliases"] = _append_csv(
            data_dir / "brand_aliases_approved.csv",
            ["canonical_brand", "alias"], brand_rows)
        applied["product_aliases"] = _append_csv(
            data_dir / "product_aliases_approved.csv",
            ["brand", "value_a", "value_b"], product_rows)
        applied["rejected_matches"] = _append_jsonl(
            data_dir / "rejected_matches_memory.jsonl", rejected_rows)
        return applied


def summarize(decisions: list[C.AgentDecision]) -> dict:
    summary = {"total": len(decisions), "auto_approved": 0, "needs_human": 0,
               "rejected": 0, "by_kind": {}}
    for d in decisions:
        summary["by_kind"][d.kind] = summary["by_kind"].get(d.kind, 0) + 1
        if d.kind == C.REJECT:
            summary["rejected"] += 1
        elif d.requires_human:
            summary["needs_human"] += 1
        elif d.verdict == C.APPROVE:
            summary["auto_approved"] += 1
    return summary


def _sim_from_reason(reason: str) -> float:
    import re
    m = re.search(r"similarity\s+([0-9.]+)", reason)
    return float(m.group(1)) if m else 0.0


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _append_csv(path: Path, header: list[str], rows: list[list]) -> int:
    if not rows:
        return 0
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if not exists:
            w.writerow(header)
        w.writerows(rows)
    return len(rows)


def _append_jsonl(path: Path, rows: list[dict]) -> int:
    if not rows:
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)
