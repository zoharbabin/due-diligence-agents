"""Tests for the uniform cross-domain trigger instruction template (audit §3.3)."""

from __future__ import annotations

import re
from typing import Any

from dd_agents.orchestrator.triggers import (
    BUILTIN_RULES,
    _trigger_instruction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    *,
    agent: str,
    category: str,
    severity: str = "P1",
    title: str = "Trigger me",
    description: str = "convenience tfc cross-border service credit",
    finding_id: str = "f-1",
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "agent": agent,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "citations": [{"source_path": "data/contract.pdf", "exact_quote": "x"}],
    }


# One finding per built-in rule so every rule fires at least once.
_RULE_FINDINGS: list[dict[str, Any]] = [
    _finding(agent="finance", category="revenue_recognition"),
    _finding(agent="legal", category="change_of_control"),
    _finding(agent="legal", category="termination", description="termination for convenience tfc"),
    _finding(agent="legal", category="ip_ownership"),
    _finding(agent="producttech", category="data_privacy gdpr", description="cross-border transfer"),
    _finding(agent="commercial", category="sla_risk service_credit", description="service credit 10%"),
    _finding(agent="finance", category="pricing_risk"),
]


# ---------------------------------------------------------------------------
# Template helper
# ---------------------------------------------------------------------------


def test_trigger_instruction_shape() -> None:
    out = _trigger_instruction(
        action="Do the thing:",
        steps=["step one", "step two", "step three"],
        severity_hint="P0 if material",
    )
    assert out.startswith("Do the thing:")
    assert "1. step one" in out
    assert "2. step two" in out
    assert "3. step three" in out
    assert "SEVERITY: P0 if material" in out
    assert "Cite all thresholds/findings with source file paths." in out


# ---------------------------------------------------------------------------
# Every built-in trigger instruction conforms (§3.3)
# ---------------------------------------------------------------------------


def test_all_triggers_have_severity_and_three_steps() -> None:
    instructions: list[str] = []
    for rule in BUILTIN_RULES:
        triggers = rule("Subject A", _RULE_FINDINGS)
        assert triggers, f"rule {rule.name} produced no trigger"
        for t in triggers:
            instructions.append(t.instructions)

    # Sanity: all 7 rules represented.
    assert len(instructions) == 7

    numbered = re.compile(r"^\d+\. ", re.MULTILINE)
    for instr in instructions:
        assert "SEVERITY:" in instr
        assert "Cite all thresholds/findings with source file paths." in instr
        step_count = len(numbered.findall(instr))
        assert step_count >= 3, f"expected >=3 numbered steps, got {step_count}: {instr!r}"
