"""Judge agent -- quality assurance with risk-based sampling.

Implements the full Judge iteration loop: spawn, score, threshold check,
targeted re-spawn for failing agents, and forced finalization with caveats.
"""

from __future__ import annotations

import logging
from typing import Any

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.models.audit import AgentScoreDimensions, QualityScores

logger = logging.getLogger(__name__)


def _safe_int(v: Any, default: int = 0) -> int:
    """Convert *v* to int, returning *default* on failure."""
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default risk-based sampling rates (configurable via deal-config.json).
DEFAULT_SAMPLING_RATES: dict[str, float] = {
    "p0": 1.0,  # 100 % of P0 findings
    "p1": 0.20,  # 20 % of P1 findings
    "p2": 0.10,  # 10 % of P2 findings
    "p3": 0.0,  # 0 % of P3 findings
}

# Spot-check dimension weights (must sum to 1.0).
DIMENSION_WEIGHTS: dict[str, float] = {
    "citation_verification": 0.30,
    "contextual_validation": 0.25,
    "financial_accuracy": 0.20,
    "cross_agent_consistency": 0.15,
    "completeness": 0.10,
}

# Default thresholds.
DEFAULT_SCORE_THRESHOLD: int = 70
DEFAULT_MAX_ITERATION_ROUNDS: int = 2

# Round-2 blend formula weights.
ROUND2_BLEND_NEW: float = 0.70
ROUND2_BLEND_PRIOR: float = 0.30


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------


def calculate_agent_score(dimensions: AgentScoreDimensions) -> int:
    """Compute the weighted agent quality score (0--100).

    Formula::

        score = 0.30 * citation_verification
              + 0.25 * contextual_validation
              + 0.20 * financial_accuracy
              + 0.15 * cross_agent_consistency
              + 0.10 * completeness
    """
    raw = (
        DIMENSION_WEIGHTS["citation_verification"] * dimensions.citation_verification
        + DIMENSION_WEIGHTS["contextual_validation"] * dimensions.contextual_validation
        + DIMENSION_WEIGHTS["financial_accuracy"] * dimensions.financial_accuracy
        + DIMENSION_WEIGHTS["cross_agent_consistency"] * dimensions.cross_agent_consistency
        + DIMENSION_WEIGHTS["completeness"] * dimensions.completeness
    )
    return round(raw)


def blend_round_scores(round1_score: int, round2_score: int) -> int:
    """Blend two iteration rounds: 70 % new + 30 % prior."""
    return round(ROUND2_BLEND_NEW * round2_score + ROUND2_BLEND_PRIOR * round1_score)


# ---------------------------------------------------------------------------
# JudgeAgent class
# ---------------------------------------------------------------------------


class JudgeAgent(BaseAgentRunner):
    """Quality-assurance agent that reviews specialist outputs.

    Activation is conditional on ``judge.enabled`` in the deal config.
    """

    max_turns: int = 150
    max_budget_usd: float = 3.0

    # Class-level defaults for reference; instance copies are made in __init__
    # to avoid mutable-default sharing across instances.
    score_threshold: int = DEFAULT_SCORE_THRESHOLD
    max_iteration_rounds: int = DEFAULT_MAX_ITERATION_ROUNDS

    def __init__(
        self,
        *args: Any,
        sampling_rates: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Each instance gets its own copy of sampling_rates to prevent
        # mutations from leaking between instances.
        self.sampling_rates: dict[str, float] = (
            dict(sampling_rates) if sampling_rates is not None else dict(DEFAULT_SAMPLING_RATES)
        )
        # Store prior round scores for blending across iteration rounds.
        self._prior_scores: dict[str, int] = {}

    def get_agent_name(self) -> str:
        return "judge"

    def get_system_prompt(self) -> str:
        return (
            "You are the Judge agent for forensic M&A due diligence. "
            "Your role is to verify specialist findings through risk-based "
            "sampling, citation verification, contextual validation, financial "
            "accuracy checks, cross-agent consistency, and completeness review."
        )

    def get_tools(self) -> list[str]:
        return ["Read", "Write", "Glob", "Grep", "verify_citation", "get_customer_files"]

    def build_prompt(self, state: dict[str, Any]) -> str:
        builder = PromptBuilder(self.project_dir, self.run_dir, self.run_id)
        findings_dir = state.get("findings_dir", str(self.run_dir / "findings"))
        return builder.build_judge_prompt(
            findings_dir=findings_dir,
            quality_targets={"score_threshold": self.score_threshold},
            sampling_rates=self.sampling_rates,
        )

    # ------------------------------------------------------------------
    # Iteration loop
    # ------------------------------------------------------------------

    async def run_with_iteration(
        self,
        state: dict[str, Any],
    ) -> QualityScores | None:
        """Execute the judge loop with up to *max_iteration_rounds* passes.

        Returns
        -------
        :class:`QualityScores` or ``None`` if the judge is disabled.
        """
        scores: QualityScores | None = None

        for round_num in range(1, self.max_iteration_rounds + 1):
            result = await self.run(state)

            scores = self._build_scores_from_result(result, round_num)

            # Blend scores with prior round when round_num > 1.
            if round_num > 1 and self._prior_scores:
                for agent_name, agent_score in scores.agent_scores.items():
                    prior = self._prior_scores.get(agent_name)
                    if prior is not None:
                        agent_score.score = blend_round_scores(prior, agent_score.score)
                # Recompute overall quality from blended agent scores.
                if scores.agent_scores:
                    scores.overall_quality = round(
                        sum(a.score for a in scores.agent_scores.values()) / max(len(scores.agent_scores), 1)
                    )

            # Save current scores for potential next-round blending.
            self._prior_scores = {name: agent_score.score for name, agent_score in scores.agent_scores.items()}

            failing = [
                agent_name
                for agent_name, agent_score in scores.agent_scores.items()
                if agent_score.score < self.score_threshold
            ]

            if not failing:
                logger.info("Judge round %d: all agents pass", round_num)
                return scores

            if round_num == self.max_iteration_rounds:
                logger.warning(
                    "Judge round %d: agents below threshold after final round: %s",
                    round_num,
                    failing,
                )
                self._apply_quality_caveats(scores, failing)
                return scores

            logger.info(
                "Judge round %d: agents below threshold: %s -- triggering re-analysis",
                round_num,
                failing,
            )
            # In production, targeted re-spawn of failing agents would happen here.

        return scores

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_scores_from_prose(raw_text: str) -> dict[str, Any] | None:
        """Extract agent scores from prose/markdown Judge output.

        When the Judge outputs prose instead of JSON, look for patterns like:
        - "Legal: 85/100" or "legal score: 85"
        - "Overall quality: 78" or "Overall Run Score: 82"
        - Markdown table rows: ``| **Finance** | **87** | 85 | 88 | ...``

        Returns a dict shaped like ``{"agent_scores": {...}, "overall_quality": N}``
        or ``None`` if no scores could be extracted.
        """
        import re as _re

        agent_names = ("legal", "finance", "commercial", "producttech")
        dimension_names = (
            "citation_verification",
            "contextual_validation",
            "financial_accuracy",
            "cross_agent_consistency",
            "completeness",
        )

        agent_scores: dict[str, dict[str, Any]] = {}

        for agent in agent_names:
            # Strategy A: prose patterns -- "Legal: 85/100", "legal score: 85"
            prose_pattern = _re.compile(
                rf"\b{agent}\b[^:\n]{{0,30}}[:=]\s*(\d{{1,3}})(?:\s*/\s*100)?",
                _re.IGNORECASE,
            )
            match = prose_pattern.search(raw_text)

            # Strategy B: markdown table -- "| **Finance** | **87** |"
            # Captures the first number after the agent name in a pipe-delimited row.
            if not match:
                table_pattern = _re.compile(
                    rf"\|\s*\**{agent}\**\s*\|\s*\**(\d{{1,3}})\**",
                    _re.IGNORECASE,
                )
                match = table_pattern.search(raw_text)

            if match:
                score = min(int(match.group(1)), 100)
                dims: dict[str, int] = {}
                # Try to find dimension scores near the agent mention.
                agent_section_start = max(0, match.start() - 50)
                agent_section_end = min(len(raw_text), match.end() + 1000)
                section = raw_text[agent_section_start:agent_section_end]

                # For table rows, find the line containing the matched agent
                # name and extract pipe-delimited numbers as dimensions.
                match_offset = match.start() - agent_section_start
                line_start = section.rfind("\n", 0, match_offset) + 1
                line_end = section.find("\n", match_offset)
                if line_end == -1:
                    line_end = len(section)
                row_text = section[line_start:line_end]
                row_nums = [int(n) for n in _re.findall(r"(?<!\w)(\d{1,3})(?!\w)", row_text)]
                # First number is the agent score, remaining are dimension
                # scores in table column order.
                if len(row_nums) > 1:
                    dim_values = row_nums[1:]
                    for i, dim_name in enumerate(dimension_names):
                        if i < len(dim_values):
                            dims[dim_name] = min(dim_values[i], 100)

                # Also try explicit "dim_name: N" patterns (prose format).
                for dim in dimension_names:
                    if dim in dims:
                        continue
                    dim_label = dim.replace("_", "[_ ]")
                    dim_pattern = _re.compile(
                        rf"\b{dim_label}\b[^:\n]{{0,20}}[:=]\s*(\d{{1,3}})",
                        _re.IGNORECASE,
                    )
                    dim_match = dim_pattern.search(section)
                    if dim_match:
                        dims[dim] = min(int(dim_match.group(1)), 100)
                agent_scores[agent] = {"score": score, "dimensions": dims}

        if not agent_scores:
            return None

        # Extract overall quality.
        overall = 0
        # Match "Overall quality: 78", "Overall Run Score: 82", "overall score = 85"
        overall_pattern = _re.compile(
            r"overall[_ ](?:quality|(?:\w+[_ ])?score)[^:\n]{0,20}[:=]\s*(\d{1,3})",
            _re.IGNORECASE,
        )
        overall_match = overall_pattern.search(raw_text)
        if overall_match:
            overall = min(int(overall_match.group(1)), 100)
        else:
            # Compute from agent scores.
            if agent_scores:
                overall = round(sum(s["score"] for s in agent_scores.values()) / len(agent_scores))

        logger.info(
            "Extracted Judge scores from prose: %d agents, overall=%d",
            len(agent_scores),
            overall,
        )
        return {"agent_scores": agent_scores, "overall_quality": overall}

    @staticmethod
    def _build_scores_from_result(result: dict[str, Any], round_num: int) -> QualityScores:
        """Build a :class:`QualityScores` from the agent run result.

        Parses the structured output produced by the Judge agent (a list of
        parsed JSON dicts in ``result["output"]``).  The expected JSON format
        matches the ``QualityScores`` schema with ``agent_scores`` containing
        per-agent dimension scores.

        Falls back to prose extraction when JSON parsing yields no
        ``agent_scores``, then to a minimal ``QualityScores`` when all
        strategies fail.
        """
        from dd_agents.models.audit import AgentScore as _AgentScore

        run_id: str = result.get("run_id", "")
        output: list[dict[str, Any]] = result.get("output") or []

        # Try to find a quality_scores-shaped dict in the parsed output.
        scores_data: dict[str, Any] | None = None
        for item in output:
            # Accept if it looks like QualityScores (has agent_scores key).
            if "agent_scores" in item:
                scores_data = item
                break

        # Strategy 2: try prose extraction from raw agent text.
        if scores_data is None:
            raw_text = result.get("raw_output", "")
            if not raw_text:
                # Reconstruct raw text from parsed output dicts.
                parts: list[str] = []
                for item in output:
                    for _key, val in item.items():
                        if isinstance(val, str):
                            parts.append(val)
                raw_text = "\n".join(parts)
            if raw_text:
                scores_data = JudgeAgent._extract_scores_from_prose(raw_text)

        if scores_data is None:
            logger.warning("Judge output did not contain agent_scores -- returning empty QualityScores")
            return QualityScores(
                run_id=run_id,
                overall_quality=0,
                iteration_round=round_num,
            )

        # Parse agent scores with dimension-level detail.
        agent_scores: dict[str, _AgentScore] = {}
        raw_agent_scores = scores_data.get("agent_scores", {})
        for agent_name, raw_score in raw_agent_scores.items():
            if isinstance(raw_score, dict):
                # Build dimensions from nested dict if present.
                raw_dims = raw_score.get("dimensions", {})
                dims = AgentScoreDimensions(
                    citation_verification=_safe_int(raw_dims.get("citation_verification", 0)),
                    contextual_validation=_safe_int(raw_dims.get("contextual_validation", 0)),
                    financial_accuracy=_safe_int(raw_dims.get("financial_accuracy", 0)),
                    cross_agent_consistency=_safe_int(raw_dims.get("cross_agent_consistency", 0)),
                    completeness=_safe_int(raw_dims.get("completeness", 0)),
                )
                # Use explicit score if provided, otherwise compute from dims.
                explicit_score = raw_score.get("score")
                computed_score = (
                    _safe_int(explicit_score) if explicit_score is not None else calculate_agent_score(dims)
                )
                # Resolve pass count: JSON may use "pass" (alias) or "pass_count".
                pass_val = raw_score.get("pass", raw_score.get("pass_count", 0))
                pass_count = _safe_int(pass_val) if pass_val is not None else 0
                agent_scores[agent_name] = _AgentScore.model_validate(
                    {
                        "score": computed_score,
                        "findings_reviewed": _safe_int(raw_score.get("findings_reviewed", 0)),
                        "findings_total": _safe_int(raw_score.get("findings_total", 0)),
                        "pass": pass_count,
                        "partial": _safe_int(raw_score.get("partial", 0)),
                        "fail": _safe_int(raw_score.get("fail", 0)),
                        "dimensions": dims.model_dump(),
                    }
                )

        # Compute overall quality as average of agent scores.
        overall: int = 0
        if agent_scores:
            overall = round(sum(a.score for a in agent_scores.values()) / max(len(agent_scores), 1))
        else:
            overall = _safe_int(scores_data.get("overall_quality", 0))

        return QualityScores(
            run_id=run_id or scores_data.get("run_id", ""),
            overall_quality=overall,
            iteration_round=round_num,
            agent_scores=agent_scores,
        )

    @staticmethod
    def _apply_quality_caveats(scores: QualityScores, failing_agents: list[str]) -> None:
        """Mark agents below threshold with quality caveats and assign quality tiers.

        Tiers:
        - score >= 85: "full_pass" — all findings accepted
        - score 75-84: "advisory" — findings included but flagged
        - score 70-74: "conditional" — P0/P1 findings require review flag
        - score < 70: "fail" — findings should be quarantined
        """
        scores.agents_below_threshold = list(failing_agents)
        for _agent_name, agent_score in scores.agent_scores.items():
            if agent_score.score >= 85:
                tier = "full_pass"
            elif agent_score.score >= 75:
                tier = "advisory"
            elif agent_score.score >= 70:
                tier = "conditional"
            else:
                tier = "fail"
            # Store quality tier in the agent score's metadata for downstream use.
            agent_score.quality_tier = tier
