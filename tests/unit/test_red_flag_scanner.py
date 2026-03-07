"""Tests for Red Flag Scanner agent and renderer (Issue #125)."""

from __future__ import annotations

from typing import Any

import pytest

from dd_agents.agents.prompt_builder import AgentType
from dd_agents.agents.red_flag_scanner import (
    RED_FLAG_CATEGORIES,
    RED_FLAG_TOOLS,
    RedFlagScannerAgent,
    RedFlagScannerOutput,
    classify_signal,
)
from dd_agents.reporting.html_red_flags import RedFlagAssessmentRenderer

# ---------------------------------------------------------------------------
# RedFlagScannerOutput model tests
# ---------------------------------------------------------------------------


class TestRedFlagScannerOutput:
    """Test the output Pydantic model for the Red Flag Scanner."""

    def test_minimal_output(self) -> None:
        out = RedFlagScannerOutput(
            overall_signal="green",
            recommendation="Proceed to full due diligence.",
            flags=[],
        )
        assert out.overall_signal == "green"
        assert out.flags == []

    def test_with_flags(self) -> None:
        out = RedFlagScannerOutput(
            overall_signal="red",
            recommendation="Investigate litigation before proceeding.",
            flags=[
                {
                    "category": "active_litigation",
                    "title": "Pending regulatory action",
                    "description": "Target faces SEC investigation.",
                    "severity": "P0",
                    "confidence": "high",
                    "source_document": "legal_summary.pdf",
                    "recommended_action": "Engage external counsel for review.",
                },
            ],
        )
        assert len(out.flags) == 1
        assert out.flags[0]["category"] == "active_litigation"

    def test_signal_must_be_valid(self) -> None:
        out = RedFlagScannerOutput(
            overall_signal="yellow",
            recommendation="Investigate.",
            flags=[],
        )
        assert out.overall_signal in {"green", "yellow", "red"}


# ---------------------------------------------------------------------------
# Signal classification tests
# ---------------------------------------------------------------------------


class TestClassifySignal:
    """Test the classify_signal helper function."""

    def test_no_flags_is_green(self) -> None:
        assert classify_signal([]) == "green"

    def test_p0_flag_is_red(self) -> None:
        flags = [{"severity": "P0", "confidence": "high"}]
        assert classify_signal(flags) == "red"

    def test_p1_high_confidence_is_red(self) -> None:
        flags = [{"severity": "P1", "confidence": "high"}]
        assert classify_signal(flags) == "red"

    def test_p1_medium_confidence_is_yellow(self) -> None:
        flags = [{"severity": "P1", "confidence": "medium"}]
        assert classify_signal(flags) == "yellow"

    def test_p2_is_yellow(self) -> None:
        flags = [{"severity": "P2", "confidence": "high"}]
        assert classify_signal(flags) == "yellow"

    def test_p3_only_is_green(self) -> None:
        flags = [{"severity": "P3", "confidence": "low"}]
        assert classify_signal(flags) == "green"

    def test_multiple_flags_takes_worst(self) -> None:
        flags = [
            {"severity": "P3", "confidence": "low"},
            {"severity": "P1", "confidence": "high"},
        ]
        assert classify_signal(flags) == "red"


# ---------------------------------------------------------------------------
# Red Flag categories constant
# ---------------------------------------------------------------------------


class TestRedFlagCategories:
    """Test the red flag category definitions."""

    def test_has_eight_categories(self) -> None:
        assert len(RED_FLAG_CATEGORIES) >= 8

    def test_required_categories(self) -> None:
        expected = {
            "active_litigation",
            "ip_ownership_gaps",
            "undisclosed_contracts",
            "key_person_dependency",
            "financial_restatements",
            "regulatory_violations",
            "customer_concentration",
            "debt_covenants",
        }
        assert expected.issubset(set(RED_FLAG_CATEGORIES))


# ---------------------------------------------------------------------------
# RedFlagScannerAgent tests
# ---------------------------------------------------------------------------


class TestRedFlagScannerAgent:
    """Test the Red Flag Scanner agent class."""

    @pytest.fixture()
    def agent(self, tmp_path: Any) -> RedFlagScannerAgent:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True)
        return RedFlagScannerAgent(
            project_dir=tmp_path,
            run_dir=run_dir,
            run_id="test-123",
        )

    def test_agent_name(self, agent: RedFlagScannerAgent) -> None:
        assert agent.get_agent_name() == "red_flag_scanner"

    def test_system_prompt_mentions_deal_killers(self, agent: RedFlagScannerAgent) -> None:
        prompt = agent.get_system_prompt()
        assert "deal-killer" in prompt.lower() or "red flag" in prompt.lower()

    def test_tools_subset(self, agent: RedFlagScannerAgent) -> None:
        tools = agent.get_tools()
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools

    def test_max_turns_is_low(self, agent: RedFlagScannerAgent) -> None:
        assert agent.max_turns <= 50

    def test_timeout_is_five_minutes(self, agent: RedFlagScannerAgent) -> None:
        assert agent.timeout_seconds <= 300

    def test_agent_type_exists(self) -> None:
        assert AgentType.RED_FLAG_SCANNER == "red_flag_scanner"

    def test_tools_list(self) -> None:
        assert "Read" in RED_FLAG_TOOLS
        assert "Glob" in RED_FLAG_TOOLS
        assert "Grep" in RED_FLAG_TOOLS


# ---------------------------------------------------------------------------
# Red Flag Assessment Renderer tests
# ---------------------------------------------------------------------------


def _make_renderer(
    flags: list[dict[str, Any]] | None = None,
    signal: str = "green",
    recommendation: str = "Proceed to full DD.",
) -> RedFlagAssessmentRenderer:
    """Build a renderer with optional red flag data."""
    from dd_agents.reporting.computed_metrics import ReportComputedData

    data = ReportComputedData(
        red_flag_scan={
            "overall_signal": signal,
            "recommendation": recommendation,
            "flags": flags or [],
        },
    )
    return RedFlagAssessmentRenderer(data, {}, {})


class TestRedFlagAssessmentRenderer:
    """Test the Red Flag Assessment HTML renderer."""

    def test_empty_when_no_scan_data(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportComputedData

        data = ReportComputedData()
        renderer = RedFlagAssessmentRenderer(data, {}, {})
        assert renderer.render() == ""

    def test_renders_green_signal(self) -> None:
        renderer = _make_renderer(signal="green")
        result = renderer.render()
        assert "Red Flag Assessment" in result
        assert "green" in result.lower() or "No Deal-Killers" in result

    def test_renders_red_signal(self) -> None:
        renderer = _make_renderer(
            signal="red",
            recommendation="Investigate litigation.",
            flags=[
                {
                    "category": "active_litigation",
                    "title": "SEC investigation",
                    "description": "Target under investigation.",
                    "severity": "P0",
                    "confidence": "high",
                    "source_document": "legal.pdf",
                    "recommended_action": "Engage counsel.",
                },
            ],
        )
        result = renderer.render()
        assert "Red Flag Assessment" in result
        assert "SEC investigation" in result
        assert "active_litigation" in result or "Active Litigation" in result

    def test_renders_yellow_signal(self) -> None:
        renderer = _make_renderer(
            signal="yellow",
            flags=[
                {
                    "category": "customer_concentration",
                    "title": "Revenue concentration",
                    "description": "Top customer is 45% of revenue.",
                    "severity": "P1",
                    "confidence": "medium",
                    "source_document": "financials.xlsx",
                    "recommended_action": "Verify customer diversification plan.",
                },
            ],
        )
        result = renderer.render()
        assert "Revenue concentration" in result

    def test_xss_escaping(self) -> None:
        renderer = _make_renderer(
            signal="red",
            flags=[
                {
                    "category": "active_litigation",
                    "title": "<script>alert(1)</script>",
                    "description": "XSS test",
                    "severity": "P0",
                    "confidence": "high",
                    "source_document": "test.pdf",
                    "recommended_action": "Fix XSS.",
                },
            ],
        )
        result = renderer.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_confidence_badge_rendered(self) -> None:
        renderer = _make_renderer(
            signal="yellow",
            flags=[
                {
                    "category": "debt_covenants",
                    "title": "Covenant near-violation",
                    "description": "Leverage ratio at 3.8x vs 4.0x limit.",
                    "severity": "P2",
                    "confidence": "low",
                    "source_document": "loan_agreement.pdf",
                    "recommended_action": "Review covenant calculations.",
                },
            ],
        )
        result = renderer.render()
        assert "low" in result.lower()

    def test_recommendation_rendered(self) -> None:
        renderer = _make_renderer(recommendation="Proceed with caution.")
        result = renderer.render()
        assert "Proceed with caution" in result
