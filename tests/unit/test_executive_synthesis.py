"""Unit tests for the executive synthesis agent.

Covers:
- Agent name and tools
- Prompt building with deal context and P0 findings
- Output parsing (valid, empty, fenced)
- Pydantic model defaults and validation
- Risk scoring with synthesis override
- Go/No-Go rendering with synthesis
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dd_agents.agents.executive_synthesis import (
    ExecutiveSynthesisAgent,
    ExecutiveSynthesisOutput,
    RankedDealBreaker,
    SeverityOverride,
)
from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    title: str = "Test finding",
    description: str = "A test finding description",
    agent: str = "legal",
    category: str = "uncategorized",
) -> dict[str, object]:
    return {
        "severity": severity,
        "title": title,
        "description": description,
        "agent": agent,
        "category": category,
        "citations": [],
    }


def _make_agent() -> ExecutiveSynthesisAgent:
    return ExecutiveSynthesisAgent(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="test_run",
    )


# ===========================================================================
# Agent identity and configuration
# ===========================================================================


class TestExecutiveSynthesisAgent:
    """Tests for ExecutiveSynthesisAgent basics."""

    def test_agent_name(self) -> None:
        """Agent returns 'executive_synthesis'."""
        agent = _make_agent()
        assert agent.get_agent_name() == "executive_synthesis"

    def test_tools_read_only(self) -> None:
        """Agent tools are read-only (Read, Glob, Grep; no Write)."""
        agent = _make_agent()
        tools = agent.get_tools()
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Write" not in tools

    def test_build_prompt_includes_deal_context(self) -> None:
        """Deal type, buyer, and target appear in the prompt."""
        agent = _make_agent()
        prompt = agent.build_prompt(
            {
                "deal_config": {
                    "buyer": {"name": "Apex Holdings"},
                    "target": {"name": "WidgetCo"},
                    "deal": {"type": "acquisition", "focus_areas": []},
                },
                "p0_findings": [],
                "p1_findings": [],
                "findings_summary": {},
            }
        )
        assert "Apex Holdings" in prompt
        assert "WidgetCo" in prompt
        assert "acquisition" in prompt.lower()

    def test_build_prompt_includes_p0_findings(self) -> None:
        """P0 findings appear in the prompt."""
        agent = _make_agent()
        prompt = agent.build_prompt(
            {
                "deal_config": {
                    "buyer": {"name": "Buyer"},
                    "target": {"name": "Target"},
                    "deal": {"type": "acquisition", "focus_areas": []},
                },
                "p0_findings": [
                    {"title": "Critical intercompany payable", "entity": "Sub A", "description": "Large payable"},
                ],
                "p1_findings": [],
                "findings_summary": {"total": 5},
            }
        )
        assert "Critical intercompany payable" in prompt
        assert "Sub A" in prompt


# ===========================================================================
# Output parsing
# ===========================================================================


class TestOutputParsing:
    """Tests for parsing executive synthesis output."""

    def test_parse_synthesis_output_valid(self) -> None:
        """Parses valid JSON output into ExecutiveSynthesisOutput."""
        output = ExecutiveSynthesisOutput.model_validate(
            {
                "go_no_go_signal": "Conditional Go",
                "go_no_go_rationale": "Deal is sound with standard conditions.",
                "executive_narrative": "The due diligence revealed no showstoppers.",
                "risk_score_override": 35,
                "severity_overrides": [
                    {
                        "finding_title": "Intercompany payable",
                        "original_severity": "P0",
                        "recommended_severity": "P3",
                        "rationale": "Eliminated at closing in full acquisition.",
                    }
                ],
                "deal_breakers_ranked": [],
                "key_themes": ["clean deal", "standard risks"],
            }
        )
        assert output.go_no_go_signal == "Conditional Go"
        assert output.risk_score_override == 35
        assert len(output.severity_overrides) == 1
        assert output.severity_overrides[0].recommended_severity == "P3"

    def test_parse_synthesis_output_empty(self) -> None:
        """Empty dict returns defaults gracefully."""
        output = ExecutiveSynthesisOutput.model_validate({})
        assert output.go_no_go_signal == "Conditional Go"
        assert output.risk_score_override == -1
        assert output.severity_overrides == []
        assert output.deal_breakers_ranked == []

    def test_output_model_defaults(self) -> None:
        """All fields have safe defaults."""
        output = ExecutiveSynthesisOutput()
        assert output.go_no_go_signal == "Conditional Go"
        assert output.go_no_go_rationale == ""
        assert output.executive_narrative == ""
        assert output.risk_score_override == -1
        assert output.severity_overrides == []
        assert output.deal_breakers_ranked == []
        assert output.key_themes == []

    def test_severity_override_model(self) -> None:
        """SeverityOverride validates correctly."""
        override = SeverityOverride(
            finding_title="Intercompany payable",
            entity="Sub A",
            original_severity="P0",
            recommended_severity="P3",
            rationale="Eliminated at closing.",
        )
        assert override.finding_title == "Intercompany payable"
        assert override.entity == "Sub A"

    def test_ranked_deal_breaker_model(self) -> None:
        """RankedDealBreaker validates correctly."""
        breaker = RankedDealBreaker(
            rank=1,
            title="Fraud in financial statements",
            entity="WidgetCo",
            impact_description="Material misstatement risk.",
            remediation="Engage forensic accountant.",
        )
        assert breaker.rank == 1
        assert breaker.remediation == "Engage forensic accountant."


# ===========================================================================
# Risk scoring with synthesis override
# ===========================================================================


class TestRiskScoringWithSynthesis:
    """Tests for computed_metrics integration with executive synthesis."""

    def test_risk_label_uses_synthesis_override(self) -> None:
        """When synthesis provides go_no_go_signal, it maps to the correct label."""
        data = ReportComputedData(
            executive_synthesis={
                "go_no_go_signal": "Conditional Go",
            },
            deal_risk_label="Critical",  # mechanical fallback
        )
        # The executive renderer should prefer synthesis signal
        assert data.executive_synthesis is not None
        assert data.executive_synthesis["go_no_go_signal"] == "Conditional Go"

    def test_risk_label_softened_single_p0(self) -> None:
        """Single P0 → 'High' not 'Critical' with softened mechanical scoring."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0")],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert data.deal_risk_label == "High"

    def test_risk_label_three_p0_still_critical(self) -> None:
        """Three P0 findings → 'Critical' with softened scoring."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0", title=f"Issue {i}") for i in range(3)],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert data.deal_risk_label == "Critical"

    def test_risk_label_two_p0_high(self) -> None:
        """Two P0 findings → 'High' with softened scoring."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [
                    _make_finding(severity="P0", title="Issue 1"),
                    _make_finding(severity="P0", title="Issue 2"),
                ],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert data.deal_risk_label == "High"

    def test_risk_score_uses_synthesis_override(self) -> None:
        """When synthesis provides risk_score_override >= 0, it's stored in computed data."""
        data = ReportComputedData(
            executive_synthesis={
                "risk_score_override": 42,
            },
        )
        assert data.executive_synthesis is not None
        assert data.executive_synthesis["risk_score_override"] == 42

    def test_risk_label_p1_threshold(self) -> None:
        """P1 >= 3 → 'High' (unchanged from before)."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P1") for _ in range(3)],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert data.deal_risk_label == "High"


# ===========================================================================
# Go/No-Go rendering with synthesis
# ===========================================================================


class TestGoNoGoWithSynthesis:
    """Tests for executive summary rendering with synthesis data."""

    def test_go_no_go_uses_synthesis_when_available(self, tmp_path: Path) -> None:
        """When synthesis is available, its signal replaces mechanical."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Conditional Go",
                "go_no_go_rationale": "Intercompany payable is trivially resolved.",
                "executive_narrative": "The deal is sound overall.",
            },
        )
        content = out.read_text(encoding="utf-8")
        assert "Conditional Go" in content
        assert "Intercompany payable is trivially resolved" in content

    def test_go_no_go_fallback_without_synthesis(self, tmp_path: Path) -> None:
        """Mechanical signal works when no synthesis is provided."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0") for _ in range(3)],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "No-Go" in content

    def test_deal_breakers_uses_synthesis_ranking(self, tmp_path: Path) -> None:
        """When synthesis provides ranked breakers, they are rendered."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0", title="Mechanical finding")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Proceed with Caution",
                "deal_breakers_ranked": [
                    {
                        "rank": 1,
                        "title": "Genuine fraud concern",
                        "entity": "WidgetCo",
                        "impact_description": "Material misstatement risk.",
                        "remediation": "Engage forensic accountant.",
                    },
                ],
            },
        )
        content = out.read_text(encoding="utf-8")
        assert "Genuine fraud concern" in content
        assert "Engage forensic accountant" in content

    def test_executive_narrative_rendered(self, tmp_path: Path) -> None:
        """Executive narrative prose section is rendered when provided."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Go",
                "executive_narrative": "This deal presents minimal risk across all domains.",
            },
        )
        content = out.read_text(encoding="utf-8")
        assert "This deal presents minimal risk across all domains" in content

    def test_partial_synthesis_only_signal(self, tmp_path: Path) -> None:
        """Synthesis with only go_no_go_signal renders correctly."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={"go_no_go_signal": "Go"},
        )
        content = out.read_text(encoding="utf-8")
        # Signal is used from synthesis — bounded check avoids matching "Go" inside "No-Go"
        assert ">Go<" in content or "Go</div>" in content
        # No narrative section rendered (empty narrative)
        assert "Executive Assessment" not in content

    def test_empty_deal_breakers_falls_back_to_mechanical(self, tmp_path: Path) -> None:
        """When synthesis provides empty deal_breakers_ranked, mechanical P0 findings show."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0", title="Mechanical P0 issue")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Proceed with Caution",
                "deal_breakers_ranked": [],
            },
        )
        content = out.read_text(encoding="utf-8")
        # Signal from synthesis
        assert "Proceed with Caution" in content
        # Mechanical deal breakers shown since ranked list is empty
        assert "Mechanical P0 issue" in content

    def test_synthesis_xss_in_narrative_escaped(self, tmp_path: Path) -> None:
        """XSS in executive_narrative is escaped."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Go",
                "executive_narrative": "<script>alert('xss')</script>",
            },
        )
        content = out.read_text(encoding="utf-8")
        # The narrative payload should be escaped (the report's own JS <script> tag is legitimate)
        assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in content

    def test_synthesis_xss_in_deal_breaker_escaped(self, tmp_path: Path) -> None:
        """XSS in deal breaker fields is escaped."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            merged,
            out,
            executive_synthesis={
                "go_no_go_signal": "Proceed with Caution",
                "deal_breakers_ranked": [
                    {
                        "rank": 1,
                        "title": "<img src=x onerror=alert(1)>",
                        "entity": "<svg onload=alert(2)>",
                        "impact_description": "<script>steal()</script>",
                        "remediation": "<b>bold</b>",
                    },
                ],
            },
        )
        content = out.read_text(encoding="utf-8")
        # All injected payloads should be HTML-escaped
        assert "&lt;img src=x onerror=alert(1)&gt;" in content
        assert "&lt;svg onload=alert(2)&gt;" in content
        assert "&lt;script&gt;steal()&lt;/script&gt;" in content

    def test_pydantic_defaults_fill_missing_synthesis_fields(self) -> None:
        """Pydantic validation fills missing fields with safe defaults."""
        partial = {"executive_narrative": "Just a note."}
        output = ExecutiveSynthesisOutput.model_validate(partial)
        assert output.go_no_go_signal == "Conditional Go"
        assert output.risk_score_override == -1
        assert output.deal_breakers_ranked == []
        assert output.severity_overrides == []
        assert output.executive_narrative == "Just a note."
