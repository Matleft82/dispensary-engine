"""Product agent: human-in-the-loop adjudicator that turns uncertain engine
outputs into auditable alias / rejection decisions feeding the deterministic core."""

from .agent import ProductAgent, summarize
from .backends import HeuristicBackend, LLMBackend
from .contract import AgentDecision

__all__ = ["ProductAgent", "summarize", "HeuristicBackend", "LLMBackend",
           "AgentDecision"]
