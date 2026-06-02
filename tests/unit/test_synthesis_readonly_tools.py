"""Tests for the shared READONLY_TOOLS set and synthesis-agent get_tools (audit §2.3).

The four synthesis agents (executive_synthesis, acquirer_intelligence,
red_flag_scanner, narrative_generation) must all expose exactly the read-only
tool set ["Read", "Glob", "Grep"] and must never grant write/exec tools.
"""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceAgent
from dd_agents.agents.base import READONLY_TOOLS, SynthesisAgentBase
from dd_agents.agents.executive_synthesis import ExecutiveSynthesisAgent
from dd_agents.agents.narrative_generation import NarrativeGenerationAgent
from dd_agents.agents.red_flag_scanner import RedFlagScannerAgent

_FORBIDDEN = {"Write", "Edit", "MultiEdit", "Bash", "NotebookEdit", "WebFetch", "WebSearch"}


def _make(cls: type) -> object:
    return cls(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="test_run",
    )


def test_readonly_tools_constant_exact() -> None:
    assert READONLY_TOOLS == ("Read", "Glob", "Grep")


def test_all_synthesis_agents_get_tools_exact() -> None:
    for cls in (
        ExecutiveSynthesisAgent,
        AcquirerIntelligenceAgent,
        RedFlagScannerAgent,
        NarrativeGenerationAgent,
    ):
        agent = _make(cls)
        assert agent.get_tools() == ["Read", "Glob", "Grep"]  # type: ignore[attr-defined]


def test_synthesis_agents_have_no_write_or_bash_tool() -> None:
    for cls in (
        ExecutiveSynthesisAgent,
        AcquirerIntelligenceAgent,
        RedFlagScannerAgent,
        NarrativeGenerationAgent,
    ):
        agent = _make(cls)
        tools = set(agent.get_tools())  # type: ignore[attr-defined]
        assert tools & _FORBIDDEN == set()


def test_synthesis_base_defaults_to_readonly() -> None:
    class _Dummy(SynthesisAgentBase):
        def get_agent_name(self) -> str:
            return "dummy"

        def get_system_prompt(self) -> str:
            return "x"

    agent = _Dummy(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="test_run",
    )
    assert agent.get_tools() == ["Read", "Glob", "Grep"]
