"""Executive Synthesis Agent — senior M&A partner review of DD findings.

Single-pass LLM agent that re-evaluates P0/P1 findings with professional
M&A judgment, produces a calibrated Go/No-Go recommendation, and ranks
genuine deal breakers.  Always runs (unlike acquirer intelligence which
requires buyer_strategy).

This agent is fundamentally different from the 4 specialist agents:
- Specialists analyse raw documents (multi-turn, file-reading, 100+ turns).
- Executive Synthesis analyses pre-merged findings (single-pass, read-only, ~5 turns).
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from dd_agents.agents.base import BaseAgentRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------


class SeverityOverride(BaseModel):
    """A recommendation to reclassify a finding's severity."""

    finding_title: str = Field(default="", description="Title of the finding being reclassified")
    entity: str = Field(default="", description="Entity/customer the finding relates to")
    original_severity: str = Field(default="", description="Original severity (P0, P1)")
    recommended_severity: str = Field(default="", description="Recommended severity (P0, P1, P2, P3)")
    rationale: str = Field(default="", description="Rationale for the severity reclassification")


class RankedDealBreaker(BaseModel):
    """A genuine deal-breaking issue ranked by impact."""

    rank: int = Field(default=0, description="Rank order of this deal breaker (1 = most impactful)")
    title: str = Field(default="", description="Title of the deal-breaking issue")
    entity: str = Field(default="", description="Entity/customer the issue relates to")
    impact_description: str = Field(default="", description="Business impact of this deal breaker")
    remediation: str = Field(default="", description="Recommended remediation or mitigation")


class ExecutiveSynthesisOutput(BaseModel):
    """Validated output from the executive synthesis agent.

    Fields with defaults allow partial LLM output to be captured
    gracefully — missing fields get safe zero-values.
    """

    go_no_go_signal: str = Field(
        default="Conditional Go",
        description="Go | Conditional Go | Proceed with Caution | No-Go",
    )
    go_no_go_rationale: str = Field(
        default="",
        description="Board-ready paragraph explaining the recommendation",
    )
    executive_narrative: str = Field(
        default="",
        description="2-3 paragraph DD summary for board presentation",
    )
    risk_score_override: int = Field(
        default=-1,
        description="0-100 calibrated risk score, or -1 to keep mechanical",
    )
    severity_overrides: list[SeverityOverride] = Field(
        default_factory=list,
        description="Recommended severity reclassifications for P0/P1 findings",
    )
    deal_breakers_ranked: list[RankedDealBreaker] = Field(
        default_factory=list,
        description="Genuine deal breakers ranked by impact",
    )
    key_themes: list[str] = Field(
        default_factory=list,
        description="Key themes from the DD review",
    )


# ---------------------------------------------------------------------------
# Read-only tools — this agent should never modify pipeline outputs
# ---------------------------------------------------------------------------

EXECUTIVE_SYNTHESIS_TOOLS: list[str] = [
    "Read",
    "Glob",
    "Grep",
]


class ExecutiveSynthesisAgent(BaseAgentRunner):
    """Re-evaluate P0/P1 findings with senior M&A partner judgment.

    This is a synthesis agent — it reads pre-existing merged findings and
    produces a calibrated Go/No-Go recommendation with executive narrative.
    It does NOT read raw documents or produce per-customer findings.
    """

    # Synthesis agent — needs enough turns to read merged findings via
    # Read/Glob/Grep tools and then produce the JSON output.  The prior
    # value of 5 was too low: the agent spent all turns on tool calls
    # and hit the hard limit (15 messages) with 0 text output.
    max_turns: int = 15
    max_budget_usd: float = 3.0
    timeout_seconds: int = 180

    def get_agent_name(self) -> str:
        return "executive_synthesis"

    def get_system_prompt(self) -> str:
        return (
            "You are a senior M&A partner conducting a final review of due diligence "
            "findings. Your role is to apply professional judgment to re-evaluate "
            "severity classifications and produce a calibrated Go/No-Go recommendation. "
            "No-Go requires truly exceptional circumstances. Most deals are Conditional Go. "
            "You produce a structured JSON analysis — never modify source files."
        )

    def get_tools(self) -> list[str]:
        return list(EXECUTIVE_SYNTHESIS_TOOLS)

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Build executive synthesis prompt from deal config + P0/P1 findings."""
        from dd_agents.agents.prompt_builder import PromptBuilder

        builder = PromptBuilder(
            project_dir=self.project_dir,
            run_dir=self.run_dir,
            run_id=self.run_id,
        )
        return builder.build_executive_synthesis_prompt(
            deal_config=state.get("deal_config"),
            p0_findings=state.get("p0_findings", []),
            p1_findings=state.get("p1_findings", []),
            findings_summary=state.get("findings_summary", {}),
            merged_findings_dir=state.get("merged_findings_dir"),
        )
