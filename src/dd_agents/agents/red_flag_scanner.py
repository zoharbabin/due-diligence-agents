"""Red Flag Scanner agent — lightweight deal-killer early warning (Issue #125).

Runs as a single-turn agent on key documents (executive summaries, financial
highlights, legal matter lists, board minutes) to surface potential deal-killers
within 5 minutes.  Produces a Red Flag Assessment with stoplight indicators.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from dd_agents.agents.base import READONLY_TOOLS, BaseAgentRunner
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1, SEVERITY_P2, SEVERITY_P3

# ---------------------------------------------------------------------------
# Red flag categories (8 deal-killer patterns)
# ---------------------------------------------------------------------------

RED_FLAG_CATEGORIES: list[str] = [
    "active_litigation",
    "ip_ownership_gaps",
    "undisclosed_contracts",
    "key_person_dependency",
    "financial_restatements",
    "regulatory_violations",
    "customer_concentration",
    "debt_covenants",
]

CATEGORY_LABELS: dict[str, str] = {
    "active_litigation": "Active Litigation",
    "ip_ownership_gaps": "IP Ownership Gaps",
    "undisclosed_contracts": "Undisclosed Material Contracts",
    "key_person_dependency": "Key-Person Dependency",
    "financial_restatements": "Financial Restatements",
    "regulatory_violations": "Regulatory Violations",
    "customer_concentration": "Customer Concentration",
    "debt_covenants": "Debt Covenant Issues",
}

# ---------------------------------------------------------------------------
# Tools available to the Red Flag Scanner
# ---------------------------------------------------------------------------

# Shared read-only tool set (audit §2.3) — single source of truth in base.py.
RED_FLAG_TOOLS: list[str] = list(READONLY_TOOLS)

# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------

_SEV_WEIGHT: dict[str, int] = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
_CONF_WEIGHT: dict[str, float] = {"high": 1.0, "medium": 0.6, "low": 0.3}


def classify_signal(flags: list[dict[str, Any]]) -> str:
    """Classify overall deal signal from a list of red flags.

    Returns ``"green"`` (no deal-killers), ``"yellow"`` (investigate), or
    ``"red"`` (potential deal-killer detected).

    Logic:
    - Any P0 flag → red
    - Any P1 + high confidence → red
    - Any P1 + medium/low confidence → yellow
    - Any P2 → yellow
    - P3 only or empty → green
    """
    if not flags:
        return "green"

    worst = "green"
    for flag in flags:
        sev = str(flag.get("severity", SEVERITY_P3))
        conf = str(flag.get("confidence", "low"))
        score = _SEV_WEIGHT.get(sev, 1) * _CONF_WEIGHT.get(conf, 0.3)

        if sev == SEVERITY_P0 or (sev == SEVERITY_P1 and conf == "high"):
            return "red"
        if score >= 1.5 or sev in (SEVERITY_P1, SEVERITY_P2):
            worst = "yellow" if worst != "red" else worst

    return worst


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class RedFlagScannerOutput(BaseModel):
    """Structured output from the Red Flag Scanner agent."""

    overall_signal: str = Field(
        description="Stoplight signal: green (no flags), yellow (investigate), red (deal-killer)."
    )
    recommendation: str = Field(description="One-line recommendation for the deal team.")
    flags: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of red flag findings. Each has: category, title, description, "
            "severity (P0-P3), confidence (high/medium/low), source_document, "
            "recommended_action."
        ),
    )


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class RedFlagScannerAgent(BaseAgentRunner):
    """Lightweight Red Flag Scanner for quick-scan mode.

    Scans key documents for deal-killer patterns within 5 minutes.
    Uses a single-turn approach with targeted prompts.
    """

    max_turns: int = 30
    timeout_seconds: int = 300
    max_budget_usd: float = 2.0

    def get_agent_name(self) -> str:
        return "red_flag_scanner"

    def get_system_prompt(self) -> str:
        from dd_agents.agents.prompts.loader import split_on_marker

        # The editable prose lives in prompts/synthesis/red_flag_scanner.md with a
        # ``<!-- CATEGORIES -->`` marker where the (code-derived) category list is
        # injected, so the category taxonomy stays single-source in RED_FLAG_CATEGORIES.
        # split_on_marker is fail-closed if the marker is edited away or duplicated.
        categories_desc = "\n".join(
            f"- **{CATEGORY_LABELS.get(cat, cat)}**: Scan for {cat.replace('_', ' ')}" for cat in RED_FLAG_CATEGORIES
        )
        head, tail = split_on_marker("synthesis", "red_flag_scanner", "<!-- CATEGORIES -->")
        return f"{head.rstrip()}\n{categories_desc}\n\n{tail.lstrip()}"

    def get_tools(self) -> list[str]:
        return list(READONLY_TOOLS)

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Build a targeted prompt for the Red Flag Scanner.

        Unlike specialist agents, the Red Flag Scanner does not receive
        subject batches.  It scans the entire data room for key documents.
        """
        project_dir = str(self.project_dir)
        text_dir = f"{project_dir}/_dd/forensic-dd/index/text"

        parts: list[str] = [
            "QUICK SCAN: Red Flag Detection\n",
            f"Data room text directory: {text_dir}\n",
            "INSTRUCTIONS:\n",
            "1. Use Glob to find key documents (executive summaries, financial "
            "highlights, legal summaries, board minutes, matter lists)\n",
            "2. Read the most important documents (prioritize summaries and overviews)\n",
            "3. Scan for the 8 red flag categories\n",
            "4. Output a JSON object with:\n",
            '   {"overall_signal": "green|yellow|red",\n',
            '    "recommendation": "one-line recommendation",\n',
            '    "flags": [{"category": "...", "title": "...", "description": "...",\n',
            '              "severity": "P0|P1|P2|P3", "confidence": "high|medium|low",\n',
            '              "source_document": "...", "recommended_action": "..."}]}\n',
        ]

        deal_config = state.get("deal_config")
        if deal_config:
            buyer = getattr(deal_config, "buyer", None)
            target = getattr(deal_config, "target", None)
            if buyer:
                parts.append(f"Buyer: {getattr(buyer, 'name', str(buyer))}\n")
            if target:
                parts.append(f"Target: {getattr(target, 'name', str(target))}\n")

        return "\n".join(parts)
