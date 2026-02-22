"""Reporting Lead agent -- final merge, audit, and Excel generation.

The Reporting Lead is the last agent in the pipeline.  It does NOT perform
new analysis.  Instead it merges specialist findings, validates numerical
consistency, and generates the multi-sheet Excel report.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from dd_agents.models.audit import QualityScores

logger = logging.getLogger(__name__)


class ReportingLeadAgent(BaseAgentRunner):
    """Reporting Lead agent runner.

    Receives all specialist findings, judge scores (if available), and the
    report schema path.  Produces the merged findings, numerical manifest,
    and the final Excel workbook.
    """

    max_turns: int = 300
    max_budget_usd: float = 8.0

    def get_agent_name(self) -> str:
        return "reportinglead"

    def get_model_id(self) -> str:
        return "claude-sonnet-4-20250514"

    def get_system_prompt(self) -> str:
        return (
            "You are the Reporting Lead agent for forensic M&A due diligence. "
            "Your job is to merge specialist findings, run numerical audits, "
            "and generate the final Excel report.  Do NOT perform new analysis."
        )

    def get_tools(self) -> list[str]:
        return [
            "Read",
            "Write",
            "Glob",
            "Grep",
            "Bash",
            "validate_manifest",
            "get_customer_files",
        ]

    def build_prompt(self, state: dict[str, Any]) -> str:
        builder = PromptBuilder(self.project_dir, self.run_dir, self.run_id)
        return builder.build_reporting_lead_prompt(
            findings_dir=state.get("findings_dir", str(self.run_dir / "findings")),
            schema_path=state.get("schema_path"),
            deal_config=state.get("deal_config") or self.deal_config,
        )

    # ------------------------------------------------------------------
    # Convenience entry-point used by the orchestrator
    # ------------------------------------------------------------------

    async def run_reporting(
        self,
        state: dict[str, Any],
        judge_scores: QualityScores | None = None,
    ) -> dict[str, Any]:
        """Execute the reporting lead phase.

        Merges all findings, validates numerical consistency, and generates
        the Excel report.

        Parameters
        ----------
        state:
            Pipeline state dict.
        judge_scores:
            Optional judge quality scores for inclusion in the report.

        Returns
        -------
        Result dict from :meth:`run`.
        """
        # Inject judge scores into state for the prompt builder.
        if judge_scores is not None:
            state["judge_scores"] = judge_scores

        return await self.run(state)
