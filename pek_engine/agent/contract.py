"""The Product agent's decision contract.

The agent reads the engine's uncertain outputs (review queue, brand/product
alias suggestions, rejected near-matches) and emits structured, auditable
decisions. It NEVER overrides a hard gate: a conflict can only be rejected, not
merged. Every decision defaults to requiring human approval unless its
confidence clears the auto-apply threshold (and only alias decisions may
auto-apply).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional

# decision kinds
BRAND_ALIAS = "brand_alias"
PRODUCT_ALIAS = "product_alias"
MERGE = "merge"
SPLIT = "split"
FIX_FIELD = "fix_field"
REJECT = "reject"

# verdicts
APPROVE = "approve"
REJECT_V = "reject"
NEEDS_HUMAN = "needs_human"


@dataclass
class AgentDecision:
    decision_id: str
    kind: str
    verdict: str
    confidence: float
    rationale: str
    subject: dict
    evidence: list = field(default_factory=list)
    writes_to: Optional[str] = None       # brand_aliases | product_aliases | rejected_matches
    requires_human: bool = True
    backend: str = "heuristic"
    source_ref: Optional[str] = None       # review_id / suggestion id

    def to_dict(self) -> dict:
        return asdict(self)


def decision_id(kind: str, subject: dict) -> str:
    base = kind + "|" + "|".join(f"{k}={subject[k]}" for k in sorted(subject))
    return "dec_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
