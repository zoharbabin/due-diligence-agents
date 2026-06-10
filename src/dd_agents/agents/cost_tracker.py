"""Agent cost tracking, model selection profiles, and budget management (Issue #129).

Provides:
1. ModelProfile — preset model configurations (economy/standard/premium)
2. CostTracker — per-agent, per-step token/cost tracking with budget limits
3. AgentCostEntry — individual usage record
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing (per 1M tokens, Claude model family, as of 2026-03)
# Update these when model pricing changes.
#
# dd-agents is provider/model-agnostic (see dd_agents.llm.provider), so a run
# may use a non-Claude model behind an Anthropic-compatible gateway. Pricing for
# such models is unknown here — supply it via the DD_MODEL_PRICING env var, a
# JSON object of ``{"<model-id>": {"input": <usd_per_mtok>, "output": <...>}}``.
# Unknown models fall back to Sonnet-shaped pricing AND log a one-time warning
# so the cost estimate is never silently wrong.
# ---------------------------------------------------------------------------

_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
}

# Fallback for unknown models (Sonnet-shaped — an estimate, flagged when used).
_DEFAULT_PRICING: dict[str, float] = {"input": 3.0, "output": 15.0}

# Models we've already warned about (one warning per unknown model per process).
_WARNED_UNKNOWN_MODELS: set[str] = set()
_WARNED_LOCK = threading.Lock()


def _load_pricing_overrides() -> dict[str, dict[str, float]]:
    """Parse the optional ``DD_MODEL_PRICING`` JSON env override (best-effort)."""
    raw = os.getenv("DD_MODEL_PRICING", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("DD_MODEL_PRICING is not valid JSON — ignoring it")
        return {}
    overrides: dict[str, dict[str, float]] = {}
    if isinstance(data, dict):
        for model, price in data.items():
            if isinstance(price, dict) and "input" in price and "output" in price:
                try:
                    overrides[str(model)] = {
                        "input": float(price["input"]),
                        "output": float(price["output"]),
                    }
                except (TypeError, ValueError):
                    logger.warning(
                        "DD_MODEL_PRICING entry %r has non-numeric rates — ignoring it",
                        model,
                    )
    return overrides


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a model + token counts.

    Resolution order: built-in Claude table → ``DD_MODEL_PRICING`` override →
    Sonnet-shaped default (with a one-time warning, so a non-Claude model's
    estimate is never silently presented as exact).
    """
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        pricing = _load_pricing_overrides().get(model)
    if pricing is None:
        pricing = _DEFAULT_PRICING
        # Advisory one-warning-per-unknown-model dedup. Guarded so concurrent
        # specialist tasks emit the warning deterministically (the cost value
        # itself is unaffected — it always uses the default rate here).
        with _WARNED_LOCK:
            if model not in _WARNED_UNKNOWN_MODELS:
                _WARNED_UNKNOWN_MODELS.add(model)
                logger.warning(
                    "No pricing for model %r — estimating at default (Sonnet-shaped) rates. "
                    "Set DD_MODEL_PRICING to cost it accurately.",
                    model,
                )
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def _is_estimated_pricing(model: str) -> bool:
    """True if *model*'s cost uses the default fallback (no exact rate).

    An empty model id (CLI-default path) is always estimated. Otherwise a model
    is exact only when present in the built-in table or DD_MODEL_PRICING.
    """
    if not model:
        return True
    if model in _MODEL_PRICING:
        return False
    return model not in _load_pricing_overrides()


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
            executive_synthesis_model="claude-opus-4-8",
            red_flag_scanner_model="claude-sonnet-4-6",
        ),
    }


# ---------------------------------------------------------------------------
# Cost entry model
# ---------------------------------------------------------------------------


class AgentCostEntry(BaseModel):
    """Single usage record for an agent invocation."""

    agent_name: str = Field(description="Name of the agent that produced this cost entry")
    step: str = Field(description="Pipeline step during which the agent ran")
    input_tokens: int = Field(default=0, description="Number of input tokens consumed")
    output_tokens: int = Field(default=0, description="Number of output tokens produced")
    model: str = Field(default="", description="Model ID used for this invocation")
    cost_usd: float = Field(default=0.0, description="Estimated cost in USD")

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

    def models_used(self) -> list[str]:
        """Return the distinct, non-empty model ids recorded across the run.

        Sorted for determinism. Used to stamp the run's audit receipt with the
        models that actually produced the analysis.
        """
        return sorted({e.model for e in self.entries if e.model})

    def cost_by_model(self) -> dict[str, dict[str, Any]]:
        """Return per-model cost rollup (Issue #232).

        Maps model id → ``{cost, input_tokens, output_tokens, estimated}``.
        ``estimated=True`` flags models priced via the Sonnet-shaped default
        fallback (no exact rate in the built-in table or DD_MODEL_PRICING), so a
        non-Claude/gateway model's spend is never presented as exact. The empty
        model id (a path that inherited the CLI default) is keyed as
        ``"(provider default)"``.
        """
        agg: dict[str, dict[str, Any]] = {}
        for e in self.entries:
            key = e.model or "(provider default)"
            bucket = agg.setdefault(key, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "estimated": False})
            bucket["cost"] += e.cost_usd
            bucket["input_tokens"] += e.input_tokens
            bucket["output_tokens"] += e.output_tokens
            # A model is "estimated" when no exact rate exists for it. The empty
            # model id is always estimated (we don't know what the CLI used).
            bucket["estimated"] = bucket["estimated"] or _is_estimated_pricing(e.model)
        return {k: {**v, "cost": round(v["cost"], 4)} for k, v in agg.items()}

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
        """Serialize the tracker state for reporting.

        Includes the active LLM routing receipt (provider + secret-free
        base_url + distinct models used) so cost_summary.json is a
        self-contained audit artifact: what was spent AND on which provider/model.
        """
        from dd_agents.llm import resolve_provider

        return {
            "total_cost": round(self.total_cost(), 4),
            "total_tokens": self.total_tokens(),
            "budget_limit_usd": self.budget_limit_usd,
            "budget_remaining": round(self.remaining_budget(), 4) if self.budget_limit_usd else None,
            "routing": {**resolve_provider().as_receipt(), "models_used": self.models_used()},
            "by_agent": {k: round(v, 4) for k, v in self.cost_by_agent().items()},
            "by_step": {k: round(v, 4) for k, v in self.cost_by_step().items()},
            "by_model": self.cost_by_model(),
            "entries": [e.model_dump() for e in self.entries],
        }
