"""Narrative Generation Agent — produces interpretive report content.

Single-pass LLM agent that generates deal-specific narrative content for
the HTML report. Takes merged findings, deal config, executive synthesis,
and computed metrics as input. Produces structured NarrativeOutput JSON
with per-domain summaries, per-finding commentary, and context-aware
recommendations.

This agent runs AFTER executive synthesis and BEFORE HTML report generation.
Non-blocking — failure falls back to deterministic report content.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.models.narrative import NarrativeOutput

logger = logging.getLogger(__name__)

NARRATIVE_TOOLS: list[str] = [
    "Read",
    "Glob",
    "Grep",
]


class NarrativeGenerationAgent(BaseAgentRunner):
    """Generate interpretive narrative content for the HTML report.

    Reads merged findings and produces structured narrative JSON including
    deal context framing, per-domain summaries, per-finding 'so what'
    commentary, prioritized recommendations, and open questions.
    """

    max_turns: int = 10
    max_budget_usd: float = 1.0
    timeout_seconds: int = 180

    def get_agent_name(self) -> str:
        return "narrative_generation"

    def get_system_prompt(self) -> str:
        return (
            "You are a senior M&A advisor writing the interpretive layer of a due diligence report. "
            "Your job is to transform structured findings into decision-ready narrative that answers: "
            "'What does this mean for THIS specific deal, and what should we do about it?' "
            "Write for a deal team audience — clear, specific, no jargon inflation. "
            "Every statement must be tied to evidence from the findings provided. "
            "You produce a single structured JSON output — never modify source files."
        )

    def get_tools(self) -> list[str]:
        return list(NARRATIVE_TOOLS)

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Build narrative generation prompt from all available context."""
        return _build_narrative_prompt(state)


def _build_narrative_prompt(state: dict[str, Any]) -> str:
    """Construct the full prompt for narrative generation."""
    parts: list[str] = []

    # Deal context
    deal_config = state.get("deal_config")
    if deal_config and isinstance(deal_config, dict):
        parts.append("## Deal Context\n")
        buyer = deal_config.get("buyer", {})
        target = deal_config.get("target", {})
        deal_info = deal_config.get("deal_info", {})
        buyer_strategy = deal_config.get("buyer_strategy", {})

        if buyer.get("name") and target.get("name"):
            parts.append(f"**Buyer:** {buyer['name']}")
            parts.append(f"**Target:** {target['name']}")
        if deal_info.get("type"):
            parts.append(f"**Deal Type:** {deal_info['type']}")
        if deal_info.get("focus_areas"):
            parts.append(f"**Focus Areas:** {', '.join(deal_info['focus_areas'])}")

        if buyer_strategy:
            parts.append("\n### Buyer Strategy")
            if buyer_strategy.get("thesis"):
                parts.append(f"**Thesis:** {buyer_strategy['thesis']}")
            if buyer_strategy.get("key_synergies"):
                parts.append(f"**Expected Synergies:** {', '.join(buyer_strategy['key_synergies'])}")
            if buyer_strategy.get("integration_priorities"):
                parts.append(f"**Integration Priorities:** {', '.join(buyer_strategy['integration_priorities'])}")
            if buyer_strategy.get("risk_tolerance"):
                parts.append(f"**Risk Tolerance:** {buyer_strategy['risk_tolerance']}")
            if buyer_strategy.get("focus_areas"):
                parts.append(f"**Buyer Focus Areas:** {', '.join(buyer_strategy['focus_areas'])}")
        parts.append("")

    # Executive synthesis results (if available)
    exec_synthesis = state.get("executive_synthesis")
    if exec_synthesis and isinstance(exec_synthesis, dict):
        parts.append("## Executive Synthesis Results\n")
        if exec_synthesis.get("go_no_go_signal"):
            parts.append(f"**Verdict:** {exec_synthesis['go_no_go_signal']}")
        if exec_synthesis.get("go_no_go_rationale"):
            parts.append(f"**Rationale:** {exec_synthesis['go_no_go_rationale']}")
        if exec_synthesis.get("key_themes"):
            parts.append(f"**Key Themes:** {', '.join(exec_synthesis['key_themes'])}")
        deal_breakers = exec_synthesis.get("deal_breakers_ranked", [])
        if deal_breakers:
            parts.append("\n**Deal Breakers (ranked):**")
            for db in deal_breakers[:5]:
                parts.append(
                    f"  {db.get('rank', '?')}. {db.get('title', '')} "
                    f"[{db.get('entity', '')}] — {db.get('impact_description', '')}"
                )
        parts.append("")

    # Findings summary
    findings_summary = state.get("findings_summary", {})
    if findings_summary:
        parts.append("## Findings Summary\n")
        parts.append(f"**Total Subjects:** {findings_summary.get('total_subjects', 0)}")
        parts.append(f"**Total Findings:** {findings_summary.get('total_findings', 0)}")
        sev_dist = findings_summary.get("severity_distribution", {})
        if sev_dist:
            parts.append(
                f"**Severity Distribution:** P0={sev_dist.get('P0', 0)}, "
                f"P1={sev_dist.get('P1', 0)}, P2={sev_dist.get('P2', 0)}, "
                f"P3={sev_dist.get('P3', 0)}"
            )
        parts.append("")

    # Domain summaries from computed metrics
    domain_summaries = state.get("domain_summaries", {})
    if domain_summaries:
        parts.append("## Domain Risk Overview\n")
        for domain, info in domain_summaries.items():
            if isinstance(info, dict):
                risk = info.get("risk_label", "Unknown")
                count = info.get("finding_count", 0)
                parts.append(f"- **{domain.capitalize()}**: {risk} risk ({count} findings)")
        parts.append("")

    # P0 findings (full detail)
    p0_findings = state.get("p0_findings", [])
    if p0_findings:
        parts.append("## P0 Critical Findings\n")
        for f in p0_findings[:10]:
            parts.append(f"### {f.get('title', 'Untitled')} [{f.get('entity', '')}]")
            parts.append(f"{f.get('description', '')}\n")

    # P1 findings (full detail)
    p1_findings = state.get("p1_findings", [])
    if p1_findings:
        parts.append("## P1 High-Priority Findings\n")
        for f in p1_findings[:15]:
            parts.append(f"### {f.get('title', 'Untitled')} [{f.get('entity', '')}]")
            parts.append(f"{f.get('description', '')}\n")

    # Financial metrics
    financial = state.get("financial_metrics", {})
    if financial:
        parts.append("## Financial Context\n")
        if financial.get("total_contracted_arr"):
            parts.append(f"**Total ARR:** ${financial['total_contracted_arr']:,.0f}")
        if financial.get("risk_adjusted_arr"):
            parts.append(f"**Risk-Adjusted ARR:** ${financial['risk_adjusted_arr']:,.0f}")
        if financial.get("total_exposure_pct"):
            parts.append(f"**Revenue at Risk:** {financial['total_exposure_pct']:.1f}%")
        parts.append("")

    # Active domains
    active_domains = state.get("active_domains", [])
    if active_domains:
        parts.append(f"**Active Domains:** {', '.join(active_domains)}\n")

    # Output schema instructions
    parts.append("## Your Task\n")
    parts.append(
        "Produce a JSON object matching the schema below. Every field must be specific "
        "to THIS deal — no generic boilerplate. Tie every recommendation to a specific "
        "finding. Quantify impact in dollars or timeline where possible.\n"
    )

    has_buyer_strategy = bool(deal_config and isinstance(deal_config, dict) and deal_config.get("buyer_strategy"))
    if not has_buyer_strategy:
        parts.append(
            "NOTE: No buyer_strategy was provided in the deal config. Leave "
            "buyer_thesis_alignment empty. For config_guidance, explain what additional "
            "context (buyer thesis, synergies, risk tolerance) would improve the report.\n"
        )

    schema = NarrativeOutput.model_json_schema()
    parts.append("```json\n" + json.dumps(schema, indent=2) + "\n```\n")
    parts.append("Respond with ONLY the JSON object. No markdown fences, no explanation outside the JSON.")

    return "\n".join(parts)
