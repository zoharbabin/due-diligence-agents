"""Agent cost tracking, model selection profiles, and budget management (Issue #129).

Provides:
1. ModelProfile — preset model configurations (economy/standard/premium)
2. CostTracker — per-agent, per-step token/cost tracking with budget limits
3. AgentCostEntry — individual usage record
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pricing (per 1M tokens, Claude model family, as of 2026-03)
# Update these when model pricing changes.
# ---------------------------------------------------------------------------

_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
}

# Fallback for unknown models
_DEFAULT_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------


class ModelProfile(BaseModel):
    """Preset model configuration for different cost/quality trade-offs."""

    name: str = Field(description="Profile name: economy, standard, premium")
    specialist_model: str = Field(description="Model for specialist agents (legal, finance, commercial, producttech)")
    judge_model: str = Field(description="Model for the Judge agent")
    executive_synthesis_model: str = Field(description="Model for Executive Synthesis agent")
    red_flag_scanner_model: str = Field(description="Model for Red Flag Scanner agent")

    _AGENT_MAPPING: dict[str, str] = {
        "legal": "specialist_model",
        "finance": "specialist_model",
        "commercial": "specialist_model",
        "producttech": "specialist_model",
        "judge": "judge_model",
        "executive_synthesis": "executive_synthesis_model",
        "red_flag_scanner": "red_flag_scanner_model",
    }

    def get_model_for_agent(self, agent_name: str) -> str:
        """Return the model ID for a given agent name."""
        field = self._AGENT_MAPPING.get(agent_name, "specialist_model")
        return getattr(self, field, self.specialist_model)


def get_model_profiles() -> dict[str, ModelProfile]:
    """Return the three preset model profiles."""
    return {
        "economy": ModelProfile(
            name="economy",
            specialist_model="claude-haiku-4-5-20251001",
            judge_model="claude-haiku-4-5-20251001",
            executive_synthesis_model="claude-sonnet-4-6",
            red_flag_scanner_model="claude-haiku-4-5-20251001",
        ),
        "standard": ModelProfile(
            name="standard",
            specialist_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            executive_synthesis_model="claude-sonnet-4-6",
            red_flag_scanner_model="claude-haiku-4-5-20251001",
        ),
        "premium": ModelProfile(
            name="premium",
            specialist_model="claude-sonnet-4-6",
            judge_model="claude-sonnet-4-6",
            executive_synthesis_model="claude-opus-4-6",
            red_flag_scanner_model="claude-sonnet-4-6",
        ),
    }


# ---------------------------------------------------------------------------
# Cost entry model
# ---------------------------------------------------------------------------


class AgentCostEntry(BaseModel):
    """Single usage record for an agent invocation."""

    agent_name: str
    step: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Cost tracker
# ---------------------------------------------------------------------------


class CostTracker:
    """Tracks token usage and costs across a pipeline run.

    Thread-safe: uses a lock to protect ``entries`` since multiple agents
    may record usage concurrently from different asyncio tasks.

    Parameters
    ----------
    budget_limit_usd:
        Optional hard budget limit in USD.  When set, ``is_budget_exceeded()``
        returns True once cumulative cost exceeds this value.
    """

    def __init__(self, budget_limit_usd: float | None = None) -> None:
        import threading

        self.budget_limit_usd = budget_limit_usd
        self.entries: list[AgentCostEntry] = []
        self._lock = threading.Lock()

    def record(
        self,
        agent_name: str,
        step: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> AgentCostEntry:
        """Record a usage entry and return it.  Thread-safe."""
        cost = _estimate_cost(model, input_tokens, output_tokens)
        entry = AgentCostEntry(
            agent_name=agent_name,
            step=step,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            cost_usd=cost,
        )
        with self._lock:
            self.entries.append(entry)
        return entry

    def total_cost(self) -> float:
        """Return total cumulative cost in USD."""
        return sum(e.cost_usd for e in self.entries)

    def total_tokens(self) -> int:
        """Return total tokens (input + output) across all entries."""
        return sum(e.total_tokens for e in self.entries)

    def cost_by_agent(self) -> dict[str, float]:
        """Return cost breakdown by agent name."""
        result: dict[str, float] = defaultdict(float)
        for e in self.entries:
            result[e.agent_name] += e.cost_usd
        return dict(result)

    def cost_by_step(self) -> dict[str, float]:
        """Return cost breakdown by pipeline step."""
        result: dict[str, float] = defaultdict(float)
        for e in self.entries:
            result[e.step] += e.cost_usd
        return dict(result)

    def is_budget_exceeded(self) -> bool:
        """Return True if total cost exceeds the budget limit."""
        if self.budget_limit_usd is None:
            return False
        return self.total_cost() > self.budget_limit_usd

    def remaining_budget(self) -> float:
        """Return remaining budget in USD, or inf if no limit set."""
        if self.budget_limit_usd is None:
            return float("inf")
        return max(0.0, self.budget_limit_usd - self.total_cost())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tracker state for reporting."""
        return {
            "total_cost": round(self.total_cost(), 4),
            "total_tokens": self.total_tokens(),
            "budget_limit_usd": self.budget_limit_usd,
            "budget_remaining": round(self.remaining_budget(), 4) if self.budget_limit_usd else None,
            "by_agent": {k: round(v, 4) for k, v in self.cost_by_agent().items()},
            "by_step": {k: round(v, 4) for k, v in self.cost_by_step().items()},
            "entries": [e.model_dump() for e in self.entries],
        }
