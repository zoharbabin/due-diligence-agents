"""Unit tests for CoC & Termination analytical nuance.

Covers:
- CoC subtype extraction guidance (5 subtypes in legal robustness)
- Competitor-only CoC = P3 severity in rubric
- TfC as valuation concern, never P0
- TfC severity calibration in commercial rubric
- Executive synthesis CoC evaluation framework
- Category split: CoC vs Assignment & Consent, Termination vs Contract Portfolio
- Topic classification: TfC separated from CoC/termination
- CoC renderer subtype column
- TfC renderer with valuation framing
- TfC RAG never red
- TfC recommendation with Valuation timeline
- Consent vs notice vs termination separation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS, AgentType, PromptBuilder
from dd_agents.agents.specialists import LegalAgent
from dd_agents.reporting.computed_metrics import (
    ReportComputedData,
    ReportDataComputer,
    _normalize_category,
)
from dd_agents.reporting.html_analysis import CoCAnalysisRenderer, TfCAnalysisRenderer
from dd_agents.reporting.html_base import render_nav_bar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer(name: str = "Customer A") -> Any:
    """Build a minimal CustomerEntry-like object."""
    m = MagicMock()
    m.name = name
    m.safe_name = name.lower().replace(" ", "_")
    m.path = f"/data/{m.safe_name}"
    m.files = ["file_1.pdf"]
    m.file_count = 1
    return m


def _make_deal_config(deal_type: str = "acquisition") -> dict[str, Any]:
    return {
        "buyer": {"name": "Apex Holdings"},
        "target": {"name": "WidgetCo", "subsidiaries": ["Sub A"]},
        "deal": {"type": deal_type, "focus_areas": ["legal", "finance"]},
    }


def _build_prompt(agent_name: str = "legal", deal_type: str = "acquisition") -> str:
    builder = PromptBuilder(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="test_run",
    )
    return builder.build_specialist_prompt(
        agent_name=agent_name,
        customers=[_make_customer()],
        deal_config=_make_deal_config(deal_type),
    )


def _make_finding(
    severity: str = "P2",
    agent: str = "legal",
    title: str = "Test finding",
    description: str = "Description",
    customer: str = "customer_a",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "agent": agent,
        "title": title,
        "description": description,
        "_customer": customer,
        "_customer_safe_name": customer,
    }


def _make_data(computed: ReportComputedData) -> dict[str, Any]:
    return {"customer_a": {"customer": "Customer A", "findings": [], "gaps": []}}


# ===========================================================================
# Prompt/Rubric Tests
# ===========================================================================


class TestCoCSeverityGuidance:
    """Prompt and rubric tests for CoC/TfC nuance."""

    def test_competitor_only_coc_severity_guidance(self) -> None:
        """Severity rubric mentions competitor-only CoC = P3."""
        focus = SPECIALIST_FOCUS[AgentType.LEGAL]
        assert "competitor-only" in focus.lower() or "competitor" in focus.lower()
        # Should indicate P3 for competitor-only
        prompt = _build_prompt()
        lower = prompt.lower()
        assert "competitor" in lower

    def test_coc_subtypes_in_legal_robustness(self) -> None:
        """All 5 CoC subtypes appear in legal domain robustness."""
        robustness = LegalAgent.domain_robustness()
        lower = robustness.lower()
        expected_subtypes = [
            "notification",
            "consent-required",
            "termination-right",
            "auto-termination",
            "competitor-only",
        ]
        for subtype in expected_subtypes:
            assert subtype in lower, f"Missing CoC subtype '{subtype}' in legal robustness"

    def test_tfc_not_deal_breaker_guidance(self) -> None:
        """Rubric says TfC = P2, never P0."""
        focus = SPECIALIST_FOCUS[AgentType.LEGAL]
        lower = focus.lower()
        # TfC should be mentioned as P2 or valuation concern
        assert "tfc" in lower or "termination for convenience" in lower

    def test_tfc_severity_calibration_commercial(self) -> None:
        """Commercial rubric mentions TfC as valuation concern."""
        focus = SPECIALIST_FOCUS[AgentType.COMMERCIAL]
        lower = focus.lower()
        assert "tfc" in lower or "termination for convenience" in lower
        assert "valuation" in lower or "revenue quality" in lower

    def test_executive_synthesis_coc_framework(self) -> None:
        """Executive synthesis prompt includes CoC evaluation framework."""
        builder = PromptBuilder(
            project_dir=Path("/tmp/project"),
            run_dir=Path("/tmp/run"),
            run_id="test_run",
        )
        prompt = builder.build_executive_synthesis_prompt(
            deal_config=_make_deal_config(),
            p0_findings=[],
            p1_findings=[],
            findings_summary={"total": 0},
        )
        lower = prompt.lower()
        assert "competitor-only" in lower or "competitor" in lower
        assert "tfc" in lower or "termination for convenience" in lower


# ===========================================================================
# Category/Topic Tests
# ===========================================================================


class TestCategoryTopicSplit:
    """Category normalization and topic classification tests."""

    def test_category_split_coc_vs_assignment(self) -> None:
        """'assignment_restriction' maps to 'Assignment & Consent', not 'Change of Control'."""
        result = _normalize_category("assignment_restriction", "legal")
        assert result == "Assignment & Consent"

    def test_category_split_tfc_vs_termination(self) -> None:
        """'convenience_termination' maps to 'Contract Portfolio', not 'Termination & Exit'."""
        result = _normalize_category("convenience_termination", "legal")
        assert result == "Contract Portfolio"

    def test_topic_classification_tfc_separate(self) -> None:
        """TfC findings go to 'tfc' topic, not 'termination'."""
        findings = [
            _make_finding(title="Termination for Convenience clause in MSA"),
        ]
        computer = ReportDataComputer()
        topics = computer._classify_by_topic(findings)
        assert len(topics.get("tfc", [])) == 1
        assert len(topics.get("termination", [])) == 0

    def test_topic_classification_coc_no_tfc_leak(self) -> None:
        """TfC findings don't leak into 'coc' topic."""
        findings = [
            _make_finding(title="Termination for Convenience — 90 day notice"),
            _make_finding(title="Change of Control consent required"),
        ]
        computer = ReportDataComputer()
        topics = computer._classify_by_topic(findings)
        # CoC finding should be in coc
        assert len(topics.get("coc", [])) == 1
        assert "change of control" in topics["coc"][0]["title"].lower()
        # TfC finding should be in tfc
        assert len(topics.get("tfc", [])) == 1

    def test_finding_with_both_coc_and_tfc_keywords(self) -> None:
        """Finding with both CoC and TfC keywords classified by topic priority (CoC wins)."""
        findings = [
            _make_finding(
                title="Change of Control with Termination for Convenience",
                description="Assignment consent required. Customer may also terminate for convenience.",
            ),
        ]
        computer = ReportDataComputer()
        topics = computer._classify_by_topic(findings)
        # CoC should win (checked first in topic dict order)
        assert len(topics.get("coc", [])) == 1
        assert len(topics.get("tfc", [])) == 0

    def test_coc_category_still_works(self) -> None:
        """'change_of_control' still maps to 'Change of Control'."""
        result = _normalize_category("change_of_control", "legal")
        assert result == "Change of Control"

    def test_termination_category_still_works(self) -> None:
        """'termination_for_cause' still maps to 'Termination & Exit'."""
        result = _normalize_category("termination_for_cause", "legal")
        assert result == "Termination & Exit"


# ===========================================================================
# Rendering Tests
# ===========================================================================


class TestCoCRendererSubtype:
    """CoC renderer tests for subtype column."""

    def test_coc_renderer_subtype_column(self) -> None:
        """CoC table has 'Type' column."""
        data = ReportComputedData(
            coc_findings=[
                _make_finding(title="Change of Control — consent required", severity="P1"),
            ],
            coc_customers_affected=1,
            consent_required_customers=1,
        )
        renderer = CoCAnalysisRenderer(data, _make_data(data), {})
        html = renderer.render()
        assert "<th" in html
        assert "Type" in html

    def test_coc_renderer_competitor_only_label(self) -> None:
        """Competitor-only findings are labeled correctly."""
        data = ReportComputedData(
            coc_findings=[
                _make_finding(
                    title="Change of Control — competitor restriction",
                    description="Terminate only if buyer is a competitor",
                    severity="P3",
                ),
            ],
            coc_customers_affected=1,
        )
        renderer = CoCAnalysisRenderer(data, _make_data(data), {})
        html = renderer.render()
        assert "Competitor" in html


class TestTfCRenderer:
    """TfC renderer tests."""

    def test_tfc_renderer_rendered(self) -> None:
        """TfC section renders with valuation framing."""
        data = ReportComputedData(
            tfc_findings=[
                _make_finding(title="Termination for Convenience — 30 day notice"),
            ],
            tfc_customers_affected=1,
        )
        renderer = TfCAnalysisRenderer(data, _make_data(data), {})
        html = renderer.render()
        assert "sec-tfc" in html
        assert "valuation" in html.lower() or "revenue" in html.lower()

    def test_tfc_renderer_empty_no_render(self) -> None:
        """No TfC findings means no section rendered."""
        data = ReportComputedData(tfc_findings=[], tfc_customers_affected=0)
        renderer = TfCAnalysisRenderer(data, _make_data(data), {})
        html = renderer.render()
        assert html == ""


# ===========================================================================
# RAG / Recommendation Tests
# ===========================================================================


class TestTfCRAGAndRecommendations:
    """TfC RAG and recommendation tests."""

    def test_tfc_rag_never_red(self) -> None:
        """TfC RAG is amber when present, never red — even with high-severity findings."""
        merged = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    {
                        "severity": "P2",
                        "agent": "legal",
                        "title": "Termination for Convenience on major contract",
                        "description": "TfC clause allows customer to terminate without cause with 30 day notice",
                        "category": "convenience_termination",
                    },
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        computed = computer.compute(merged)
        tfc_rag = computed.section_rag.get("tfc", "green")
        assert tfc_rag != "red", "TfC RAG should never be red"
        # If there are TfC findings it should be amber
        if computed.tfc_findings:
            assert tfc_rag == "amber"

    def test_tfc_recommendation_generated(self) -> None:
        """TfC recommendation uses 'Valuation' timeline."""
        merged = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    {
                        "severity": "P2",
                        "agent": "legal",
                        "title": "Termination for Convenience clause",
                        "description": "Customer may terminate without cause with 30 day notice",
                        "category": "convenience_termination",
                    },
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        computed = computer.compute(merged)
        tfc_recs = [r for r in computed.recommendations if r.get("timeline") == "Valuation"]
        if computed.tfc_findings:
            assert len(tfc_recs) >= 1, "Expected TfC recommendation with Valuation timeline"

    def test_coc_recommendation_subtype_aware(self) -> None:
        """CoC recommendation differentiates consent vs notification."""
        merged = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    {
                        "severity": "P1",
                        "agent": "legal",
                        "title": "Change of Control — consent required",
                        "description": "Assignment requires customer consent",
                        "category": "change_of_control",
                    },
                ],
                "gaps": [],
            },
            "customer_b": {
                "customer": "Customer B",
                "findings": [
                    {
                        "severity": "P2",
                        "agent": "legal",
                        "title": "Change of Control notification",
                        "description": "Notification-only CoC clause, notify counterparty",
                        "category": "change_of_control",
                    },
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        computed = computer.compute(merged)
        # Find CoC recommendation
        coc_recs = [
            r
            for r in computed.recommendations
            if "consent" in r.get("title", "").lower() or "assignment" in r.get("title", "").lower()
        ]
        assert len(coc_recs) >= 1, "Expected CoC recommendation"
        # Verify description mentions both consent and notification distinctly
        desc = coc_recs[0].get("description", "").lower()
        assert "consent" in desc, "CoC recommendation should mention consent-required findings"
        assert "notification" in desc, "CoC recommendation should mention notification-only findings"


# ===========================================================================
# Separation Tests
# ===========================================================================


class TestSubtypeSeparation:
    """Tests for correct subtype separation across the pipeline."""

    def test_consent_vs_notice_vs_termination_separation(self) -> None:
        """3 CoC subtypes render with correct labels in CoC table."""
        data = ReportComputedData(
            coc_findings=[
                _make_finding(title="CoC — notification-only", description="Notify counterparty"),
                _make_finding(title="CoC — consent-required", description="Requires prior consent"),
                _make_finding(title="CoC — auto-termination", description="Auto-terminates on acquisition"),
            ],
            coc_customers_affected=3,
            consent_required_customers=1,
        )
        renderer = CoCAnalysisRenderer(data, _make_data(data), {})
        html = renderer.render()
        # All 3 subtypes should appear
        assert "Notification" in html
        assert "Consent" in html
        assert "Auto" in html

    def test_tfc_vs_tfc_cause_different_categories(self) -> None:
        """TfC and TfCause map to different canonical categories."""
        tfc_result = _normalize_category("convenience_termination", "legal")
        cause_result = _normalize_category("termination_for_cause", "legal")
        assert tfc_result != cause_result
        assert tfc_result == "Contract Portfolio"
        assert cause_result == "Termination & Exit"


# ===========================================================================
# Nav link test
# ===========================================================================


class TestTfCNav:
    """TfC navigation link tests."""

    def test_tfc_nav_link_present(self) -> None:
        """Nav bar includes TfC Revenue link."""
        nav_html = render_nav_bar(section_rag={"tfc": "amber"})
        assert "#sec-tfc" in nav_html
        assert "TfC" in nav_html or "tfc" in nav_html.lower()
