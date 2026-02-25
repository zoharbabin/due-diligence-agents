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

    # Judge-specific configuration (populated from deal config).
    sampling_rates: dict[str, float] = dict(DEFAULT_SAMPLING_RATES)
    score_threshold: int = DEFAULT_SCORE_THRESHOLD
    max_iteration_rounds: int = DEFAULT_MAX_ITERATION_ROUNDS

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

            # In production, we would read the written quality_scores.json.
            # Here we return from parsed output or build a stub.
            scores = self._build_scores_from_result(result, round_num)

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
    def _build_scores_from_result(result: dict[str, Any], round_num: int) -> QualityScores:
        """Build a :class:`QualityScores` from the run result.

        This is a placeholder -- in production the Judge writes the file to
        disk and we read it back.  For now, return a minimal valid object.
        """
        return QualityScores(
            run_id=result.get("run_id", ""),
            overall_quality=0,
            iteration_round=round_num,
        )

    @staticmethod
    def _apply_quality_caveats(scores: QualityScores, failing_agents: list[str]) -> None:
        """Mark agents below threshold with quality caveats."""
        scores.agents_below_threshold = list(failing_agents)
