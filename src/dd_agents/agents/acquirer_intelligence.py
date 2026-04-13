"""Acquirer Intelligence Agent -- optional buyer-strategy analysis (Issue #110).

Single-pass LLM agent that synthesises merged DD findings through the buyer's
strategic lens.  Produces structured intelligence consumed by StrategyRenderer.

This agent is fundamentally different from the 4 specialist agents:
- Specialists analyse raw documents (multi-turn, file-reading, 100+ turns).
- Acquirer Intelligence analyses pre-merged findings (single-pass, read-only, ~15 turns).

Only runs when ``buyer_strategy`` is present in deal config.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field  # noqa: TC001 — runtime use for output schema

from dd_agents.agents.base import BaseAgentRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------


class _RiskAlignment(BaseModel):  # noqa: TC001 — runtime use
    """Risk alignment for a single focus area."""

    focus_area: str = Field(default="", description="Buyer focus area being assessed")
    finding_count: int = Field(default=0, description="Number of findings relevant to this focus area")
    assessment: str = Field(default="", description="Risk alignment assessment narrative")


class AcquirerIntelligenceOutput(BaseModel):  # noqa: TC001 — runtime use
    """Validated output from the acquirer intelligence agent.

    Fields with defaults allow partial LLM output to be captured
    gracefully — missing fields get safe zero-values.
    """

    summary: str = Field(default="", description="Strategic assessment of findings impact on acquisition thesis")
    recommendations: list[str] = Field(default_factory=list, description="Actionable recommendations")
    risk_alignment: list[_RiskAlignment] = Field(default_factory=list, description="Focus area risk assessments")
    deal_impact: str = Field(default="", description="Overall deal impact: low, moderate, high, critical")
    key_concerns: list[str] = Field(default_factory=list, description="Key concern strings")


# ---------------------------------------------------------------------------
# Read-only tools -- this agent should never modify pipeline outputs
# ---------------------------------------------------------------------------

ACQUIRER_INTELLIGENCE_TOOLS: list[str] = [
    "Read",
    "Glob",
    "Grep",
]


class AcquirerIntelligenceAgent(BaseAgentRunner):
    """Analyse merged findings through the buyer's strategic lens.

    This is a synthesis agent — it reads pre-existing merged findings and
    produces strategic intelligence.  It does NOT read raw documents or
    produce per-subject findings.

    Output schema::

        {
            "summary": "Strategic fit assessment...",
            "recommendations": ["Proceed with...", "Renegotiate..."],
            "risk_alignment": [
                {
                    "focus_area": "change_of_control",
                    "finding_count": 3,
                    "assessment": "Material risk to thesis"
                }
            ],
            "deal_impact": "moderate",
            "key_concerns": ["CoC clauses in 5 contracts", ...]
        }
    """

    # Synthesis agent — reads all merged findings (16+ subject files) via
    # Read/Glob/Grep tools then produces buyer-lens JSON output.  With 14+
    # subjects the agent needs ~40-60 tool turns for reading alone.
    max_turns: int = 75
    max_budget_usd: float = 3.0
    timeout_seconds: int = 300

    def get_agent_name(self) -> str:
        return "acquirer_intelligence"

    def get_system_prompt(self) -> str:
        return (
            "You are the Acquirer Intelligence analyst for forensic M&A due diligence. "
            "Your role is to synthesise pre-merged findings through the buyer's strategic "
            "lens, assessing how due diligence findings impact the acquisition thesis. "
            "You produce a structured JSON analysis — never modify source files."
        )

    def get_tools(self) -> list[str]:
        return list(ACQUIRER_INTELLIGENCE_TOOLS)

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Build acquirer intelligence prompt from buyer strategy + findings summary."""
        buyer_strategy = state.get("buyer_strategy", {}) or {}
        findings_summary = state.get("merged_findings_summary", {}) or {}
        merged_dir = state.get("merged_findings_dir", "")

        sections: list[str] = []

        sections.append(
            "# ACQUIRER INTELLIGENCE ANALYSIS\n\n"
            "Analyse the merged due diligence findings through the buyer's strategic "
            "lens. Produce a structured assessment of how findings impact the "
            "acquisition thesis.\n"
        )

        # Buyer strategy context
        sections.append("## BUYER STRATEGY\n")
        if buyer_strategy.get("thesis"):
            sections.append(f"Acquisition Thesis: {buyer_strategy['thesis']}")
        if buyer_strategy.get("key_synergies"):
            sections.append(f"Expected Synergies: {', '.join(buyer_strategy['key_synergies'])}")
        if buyer_strategy.get("integration_priorities"):
            sections.append(f"Integration Priorities: {', '.join(buyer_strategy['integration_priorities'])}")
        if buyer_strategy.get("risk_tolerance"):
            sections.append(f"Risk Tolerance: {buyer_strategy['risk_tolerance']}")
        if buyer_strategy.get("focus_areas"):
            sections.append(f"Focus Areas: {', '.join(buyer_strategy['focus_areas'])}")
        if buyer_strategy.get("budget_range"):
            sections.append(f"Budget Range: {buyer_strategy['budget_range']}")

        # Findings summary
        sections.append("\n## FINDINGS SUMMARY\n")
        if findings_summary:
            for key, value in findings_summary.items():
                sections.append(f"- {key}: {value}")
        else:
            sections.append("No findings summary available.")

        # Merged findings location
        if merged_dir:
            sections.append(f"\n## MERGED FINDINGS\n\nRead merged findings from: {merged_dir}")

        # Output format
        sections.append(
            "\n## OUTPUT FORMAT\n\n"
            "Return a single JSON object with the following structure:\n"
            "```json\n"
            "{\n"
            '  "summary": "Strategic assessment of findings impact on acquisition thesis",\n'
            '  "recommendations": ["Actionable recommendation 1", ...],\n'
            '  "risk_alignment": [\n'
            "    {\n"
            '      "focus_area": "category name",\n'
            '      "finding_count": 0,\n'
            '      "assessment": "Impact assessment"\n'
            "    }\n"
            "  ],\n"
            '  "deal_impact": "low | moderate | high | critical",\n'
            '  "key_concerns": ["Concern 1", ...]\n'
            "}\n"
            "```\n"
            "Output ONLY the JSON object. No explanatory text."
        )

        return "\n".join(sections)
