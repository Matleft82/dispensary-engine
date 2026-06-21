"""Adjudication backends. `HeuristicBackend` is the offline default; `LLMBackend`
is an optional reasoning backend that takes a user-supplied `llm_fn` callable so
no vendor SDK is hard-wired.

Both return a `(verdict, confidence, rationale, evidence)` tuple for one
candidate. Neither can approve a hard-gate conflict — that filtering happens in
the agent before a backend is consulted; backends only grade alias/uncertain
candidates."""

from __future__ import annotations

import json
from typing import Callable

from . import contract as C


class HeuristicBackend:
    """Deterministic thresholds over available signals. No API key needed."""

    name = "heuristic"

    def __init__(self, approve_at: float = 0.92, human_floor: float = 0.78) -> None:
        self.approve_at = approve_at
        self.human_floor = human_floor

    def grade(self, kind: str, subject: dict) -> tuple[str, float, str, list]:
        sim = float(subject.get("similarity")
                    or subject.get("closest_approved_similarity") or 0.0)
        evidence = [f"similarity={sim:.3f}"]
        count = subject.get("count")
        if count:
            evidence.append(f"occurrences={count}")
        if kind == C.BRAND_ALIAS:
            target = subject.get("closest_approved_brand")
            evidence.append(f"closest_approved={target}")
            if not target:
                return (C.NEEDS_HUMAN, 0.3,
                        "No close approved brand; treat as a brand-new brand.", evidence)
            if sim >= self.approve_at:
                return (C.APPROVE, sim,
                        f"'{subject.get('raw_brand_value')}' ~= approved "
                        f"'{target}' (sim {sim:.2f}).", evidence)
            if sim >= self.human_floor:
                return (C.NEEDS_HUMAN, sim,
                        f"Plausible alias of '{target}' but below auto-threshold.",
                        evidence)
            return (C.NEEDS_HUMAN, sim,
                    "Low similarity to any approved brand; human should confirm.",
                    evidence)
        # product alias
        if sim >= self.approve_at:
            return (C.APPROVE, sim,
                    f"'{subject.get('value_a')}' ~= '{subject.get('value_b')}' "
                    f"(sim {sim:.2f}); likely the same product name.", evidence)
        if sim >= self.human_floor:
            return (C.NEEDS_HUMAN, sim,
                    "Names are similar but identity differences are possible.",
                    evidence)
        return (C.NEEDS_HUMAN, sim,
                "Weak similarity; human should confirm or reject.", evidence)


class LLMBackend:
    """Optional reasoning backend. `llm_fn(prompt:str)->str` must return JSON:
    {"verdict": "approve|reject|needs_human", "confidence": 0..1,
     "rationale": "..."}. Falls back to the heuristic on any failure."""

    name = "llm"

    def __init__(self, llm_fn: Callable[[str], str],
                 fallback: HeuristicBackend | None = None) -> None:
        self.llm_fn = llm_fn
        self.fallback = fallback or HeuristicBackend()

    def grade(self, kind: str, subject: dict) -> tuple[str, float, str, list]:
        prompt = self._prompt(kind, subject)
        try:
            raw = self.llm_fn(prompt)
            data = json.loads(raw)
            verdict = data["verdict"]
            if verdict not in (C.APPROVE, C.REJECT_V, C.NEEDS_HUMAN):
                raise ValueError(f"bad verdict {verdict!r}")
            conf = float(data.get("confidence", 0.5))
            rationale = str(data.get("rationale", "")).strip() or "(no rationale)"
            return verdict, conf, rationale, [f"llm:{verdict}", f"confidence={conf:.2f}"]
        except Exception as exc:  # network/parse error -> deterministic fallback
            v, c, r, e = self.fallback.grade(kind, subject)
            return v, c, f"[llm fallback: {type(exc).__name__}] {r}", e

    @staticmethod
    def _prompt(kind: str, subject: dict) -> str:
        return (
            "You are a cannabis product-catalog adjudicator. Decide if these two "
            "values refer to the SAME canonical product/brand. Be conservative: a "
            "missed match is better than a false match. Never merge across "
            "different extract types, hardware, size, or ratio.\n"
            f"Kind: {kind}\nSubject: {json.dumps(subject, ensure_ascii=False)}\n"
            'Respond ONLY as JSON: {"verdict":"approve|reject|needs_human",'
            '"confidence":0..1,"rationale":"..."}'
        )
