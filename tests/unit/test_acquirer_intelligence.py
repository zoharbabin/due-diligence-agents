"""Unit tests for AcquirerIntelligenceAgent (Issue #110).

Tests the agent class, prompt builder, and pipeline integration.
The agent is optional — only runs when buyer_strategy is present in deal config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dd_agents.agents.acquirer_intelligence import (
    ACQUIRER_INTELLIGENCE_TOOLS,
    AcquirerIntelligenceAgent,  # noqa: TC001 — runtime use in tests
)
from dd_agents.agents.prompt_builder import AgentType, PromptBuilder

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Agent class tests
# ---------------------------------------------------------------------------


class TestAcquirerIntelligenceAgent:
    def _make_agent(self, tmp_path: Path) -> AcquirerIntelligenceAgent:
        return AcquirerIntelligenceAgent(
            project_dir=tmp_path,
            run_dir=tmp_path / "run",
            run_id="test_run",
        )

    def test_agent_name(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        assert agent.get_agent_name() == "acquirer_intelligence"

    def test_system_prompt_contains_role(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        prompt = agent.get_system_prompt()
        assert "acquirer" in prompt.lower() or "buyer" in prompt.lower()
        assert "due diligence" in prompt.lower()

    def test_tools_read_only(self, tmp_path: Path) -> None:
        """Acquirer intelligence agent should have read-only tools — no Write."""
        agent = self._make_agent(tmp_path)
        tools = agent.get_tools()
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Write" not in tools

    def test_max_turns_reasonable(self, tmp_path: Path) -> None:
        """Synthesis agent needs enough turns to read findings + produce output."""
        agent = self._make_agent(tmp_path)
        assert agent.max_turns == 75

    def test_budget_low(self, tmp_path: Path) -> None:
        """Should use minimal budget since it's a synthesis pass."""
        agent = self._make_agent(tmp_path)
        assert agent.max_budget_usd <= 5.0

    def test_tools_list_constant(self) -> None:
        assert isinstance(ACQUIRER_INTELLIGENCE_TOOLS, list)
        assert "Read" in ACQUIRER_INTELLIGENCE_TOOLS

    def test_build_prompt_includes_buyer_strategy(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        state: dict[str, Any] = {
            "buyer_strategy": {
                "thesis": "Expand into enterprise market",
                "key_synergies": ["Revenue uplift"],
                "risk_tolerance": "moderate",
                "focus_areas": ["change_of_control"],
            },
            "merged_findings_summary": {
                "total_findings": 10,
                "p0_count": 2,
                "domains": {"legal": 5, "finance": 3},
            },
        }
        prompt = agent.build_prompt(state)
        assert "Expand into enterprise market" in prompt
        assert "Revenue uplift" in prompt
        assert "moderate" in prompt
        assert "change_of_control" in prompt

    def test_build_prompt_includes_findings_summary(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        state: dict[str, Any] = {
            "buyer_strategy": {"thesis": "Test"},
            "merged_findings_summary": {
                "total_findings": 42,
                "p0_count": 3,
                "p1_count": 7,
            },
        }
        prompt = agent.build_prompt(state)
        assert "42" in prompt
        assert "findings" in prompt.lower()

    def test_build_prompt_requires_output_format(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        state: dict[str, Any] = {
            "buyer_strategy": {"thesis": "Test"},
            "merged_findings_summary": {},
        }
        prompt = agent.build_prompt(state)
        assert "summary" in prompt.lower()
        assert "recommendations" in prompt.lower()

    def test_build_prompt_empty_strategy_still_works(self, tmp_path: Path) -> None:
        agent = self._make_agent(tmp_path)
        state: dict[str, Any] = {
            "buyer_strategy": {},
            "merged_findings_summary": {},
        }
        prompt = agent.build_prompt(state)
        assert len(prompt) > 0

    def test_base_parse_agent_output_valid(self) -> None:
        """Base class parser extracts structured JSON from agent output."""
        from dd_agents.agents.base import BaseAgentRunner

        raw = '{"summary": "Strong fit", "recommendations": ["Proceed"]}'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["summary"] == "Strong fit"
        assert result[0]["recommendations"] == ["Proceed"]

    def test_base_parse_agent_output_empty(self) -> None:
        from dd_agents.agents.base import BaseAgentRunner

        result = BaseAgentRunner._parse_agent_output("")
        assert result == []

    def test_base_parse_agent_output_with_fences(self) -> None:
        from dd_agents.agents.base import BaseAgentRunner

        raw = '```json\n{"summary": "Analysis complete"}\n```'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["summary"] == "Analysis complete"

    def test_output_model_defaults(self) -> None:
        """AcquirerIntelligenceOutput has safe defaults for all fields."""
        from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceOutput

        model = AcquirerIntelligenceOutput()
        assert model.summary == ""
        assert model.recommendations == []
        assert model.risk_alignment == []
        assert model.deal_impact == ""
        assert model.key_concerns == []

    def test_output_model_roundtrip(self) -> None:
        """Model can be serialized and deserialized."""
        from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceOutput

        model = AcquirerIntelligenceOutput(
            summary="Test",
            recommendations=["Do X"],
            deal_impact="moderate",
        )
        data = model.model_dump()
        restored = AcquirerIntelligenceOutput.model_validate(data)
        assert restored.summary == "Test"
        assert restored.deal_impact == "moderate"


# ---------------------------------------------------------------------------
# AgentType enum tests
# ---------------------------------------------------------------------------


class TestAgentTypeEnum:
    def test_acquirer_intelligence_in_enum(self) -> None:
        assert hasattr(AgentType, "ACQUIRER_INTELLIGENCE")
        assert AgentType.ACQUIRER_INTELLIGENCE == "acquirer_intelligence"

    def test_acquirer_intelligence_not_specialist(self) -> None:
        """Acquirer intelligence is NOT a specialist — shouldn't appear in specialist lists."""
        from dd_agents.agents.specialists import SPECIALIST_TYPES

        assert AgentType.ACQUIRER_INTELLIGENCE not in SPECIALIST_TYPES


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------


class TestAcquirerIntelligencePromptBuilder:
    def test_build_acquirer_prompt(self, tmp_path: Path) -> None:
        builder = PromptBuilder(
            project_dir=tmp_path,
            run_dir=tmp_path / "run",
            run_id="test_001",
        )
        prompt = builder.build_acquirer_intelligence_prompt(
            buyer_strategy={
                "thesis": "Market consolidation",
                "risk_tolerance": "conservative",
                "focus_areas": ["ip_ownership", "change_of_control"],
            },
            findings_summary={
                "total_findings": 25,
                "p0_count": 1,
                "p1_count": 4,
                "domains": {"legal": 10, "finance": 8, "commercial": 4, "producttech": 3},
            },
            merged_findings_dir=str(tmp_path / "findings" / "merged"),
        )
        assert "Market consolidation" in prompt
        assert "conservative" in prompt
        assert "ip_ownership" in prompt
        assert "25" in prompt
        assert "merged" in prompt.lower() or str(tmp_path) in prompt

    def test_build_acquirer_prompt_minimal(self, tmp_path: Path) -> None:
        builder = PromptBuilder(
            project_dir=tmp_path,
            run_dir=tmp_path / "run",
            run_id="test_001",
        )
        prompt = builder.build_acquirer_intelligence_prompt(
            buyer_strategy={},
            findings_summary={},
        )
        assert len(prompt) > 0
        assert "acquirer" in prompt.lower() or "buyer" in prompt.lower()


# ---------------------------------------------------------------------------
# BuyerStrategy model tests
# ---------------------------------------------------------------------------


class TestBuyerStrategyModel:
    """Test the BuyerStrategy Pydantic model and its risk_tolerance validator."""

    def test_valid_risk_tolerance_conservative(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy(risk_tolerance="conservative")
        assert bs.risk_tolerance == "conservative"

    def test_valid_risk_tolerance_moderate(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy(risk_tolerance="moderate")
        assert bs.risk_tolerance == "moderate"

    def test_valid_risk_tolerance_aggressive(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy(risk_tolerance="aggressive")
        assert bs.risk_tolerance == "aggressive"

    def test_empty_risk_tolerance_allowed(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy(risk_tolerance="")
        assert bs.risk_tolerance == ""

    def test_invalid_risk_tolerance_rejected(self) -> None:
        import pytest

        from dd_agents.models.config import BuyerStrategy

        with pytest.raises(Exception):  # noqa: B017, PT011
            BuyerStrategy(risk_tolerance="reckless")

    def test_default_fields(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy()
        assert bs.thesis == ""
        assert bs.key_synergies == []
        assert bs.focus_areas == []
        assert bs.risk_tolerance == "moderate"

    def test_full_construction(self) -> None:
        from dd_agents.models.config import BuyerStrategy

        bs = BuyerStrategy(
            thesis="Market consolidation",
            key_synergies=["Revenue uplift"],
            integration_priorities=["Merge teams"],
            risk_tolerance="moderate",
            focus_areas=["change_of_control"],
            budget_range="$50M-$80M",
        )
        assert bs.thesis == "Market consolidation"
        assert len(bs.key_synergies) == 1
        assert bs.budget_range == "$50M-$80M"
