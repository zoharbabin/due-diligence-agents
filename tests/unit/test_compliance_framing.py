"""Compliance framing threaded into interpretive/verdict prompts (audit §1.3)."""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.executive_synthesis import ExecutiveSynthesisAgent
from dd_agents.agents.narrative_generation import NarrativeGenerationAgent
from dd_agents.agents.prompt_constants import COMPLIANCE_FRAMING


def test_compliance_framing_constant_text() -> None:
    assert "verified by qualified advisors" in COMPLIANCE_FRAMING
    assert "settled fact" in COMPLIANCE_FRAMING


def test_executive_synthesis_prompt_includes_compliance_framing() -> None:
    agent = ExecutiveSynthesisAgent(project_dir=Path("/x"), run_dir=Path("/x"), run_id="t")
    assert COMPLIANCE_FRAMING in agent.get_system_prompt()


def test_narrative_generation_prompt_includes_compliance_framing() -> None:
    agent = NarrativeGenerationAgent(project_dir=Path("/x"), run_dir=Path("/x"), run_id="t")
    assert COMPLIANCE_FRAMING in agent.get_system_prompt()
