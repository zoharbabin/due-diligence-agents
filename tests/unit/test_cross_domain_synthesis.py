"""Unit tests for Cross-Domain Synthesis enhancement (Issue #198).

Covers:
- Compound severity escalation rules
- Connection narrative generation
- Domain interaction matrix
- Renderer HTML output (cards, matrix, empty state)
- XSS prevention in entity names
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData
from dd_agents.reporting.html_cross_domain import (
    CrossDomainRenderer,
    _compute_compound_severity,
    _get_pair_narrative,
)
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1, SEVERITY_P2, SEVERITY_P3


class TestCompoundSeverityEscalation:
    """Tests for compound severity escalation rules."""

    def test_p0_stays_p0(self) -> None:
        """Any P0 present → compound severity is P0."""
        assert _compute_compound_severity([SEVERITY_P0, SEVERITY_P2], 2) == SEVERITY_P0

    def test_p1_plus_p2_escalates_to_p0(self) -> None:
        """P1 + P2 in same entity → P0."""
        assert _compute_compound_severity([SEVERITY_P1, SEVERITY_P2], 2) == SEVERITY_P0

    def test_two_p2_escalates_to_p1(self) -> None:
        """2×P2 across domains → P1."""
        assert _compute_compound_severity([SEVERITY_P2, SEVERITY_P2], 2) == SEVERITY_P1

    def test_three_domains_minimum_p1(self) -> None:
        """3+ domains → P1 minimum regardless of individual severities."""
        assert _compute_compound_severity([SEVERITY_P3, SEVERITY_P3, SEVERITY_P3], 3) == SEVERITY_P1

    def test_single_p1_stays_p1(self) -> None:
        """Single P1 without escalation triggers stays P1."""
        assert _compute_compound_severity([SEVERITY_P1], 2) == SEVERITY_P1

    def test_single_p2_stays_p2(self) -> None:
        """Single P2 across 2 domains stays P2."""
        assert _compute_compound_severity([SEVERITY_P2], 2) == SEVERITY_P2

    def test_p0_takes_precedence(self) -> None:
        """P0 with many other severities still P0."""
        assert _compute_compound_severity([SEVERITY_P0, SEVERITY_P1, SEVERITY_P2, SEVERITY_P2], 4) == SEVERITY_P0


class TestConnectionNarratives:
    """Tests for deterministic pair narrative generation."""

    def test_finance_legal_narrative(self) -> None:
        """Finance + Legal pair has a narrative."""
        narrative = _get_pair_narrative(["finance", "legal"])
        assert "indemnity" in narrative or "contractual" in narrative

    def test_legal_producttech_narrative(self) -> None:
        """Legal + ProductTech pair has a narrative."""
        narrative = _get_pair_narrative(["legal", "producttech"])
        assert "license" in narrative.lower() or "IP" in narrative

    def test_unknown_pair_generic_narrative(self) -> None:
        """Unknown pair returns generic systemic risk narrative."""
        narrative = _get_pair_narrative(["esg", "hr"])
        assert "systemic risk" in narrative

    def test_single_domain_no_narrative(self) -> None:
        """Single domain returns empty narrative."""
        assert _get_pair_narrative(["legal"]) == ""

    def test_three_domains_picks_best_pair(self) -> None:
        """Three domains finds the best matching pair."""
        narrative = _get_pair_narrative(["finance", "legal", "commercial"])
        assert narrative != ""


class TestCrossDomainRenderer:
    """Tests for CrossDomainRenderer output."""

    def _make_data_with_risks(self, risks: list[dict[str, Any]]) -> ReportComputedData:
        return ReportComputedData(
            cross_domain_risks=risks,
            display_names={"acme": "Acme Corp", "widget": "WidgetCo"},
        )

    def test_empty_state(self) -> None:
        """No risks and no triggers → empty string."""
        data = ReportComputedData()
        renderer = CrossDomainRenderer(data, {}, {})
        assert renderer.render() == ""

    def test_renders_connection_cards(self) -> None:
        """Risks render as connection cards with domain pills."""
        data = self._make_data_with_risks(
            [
                {
                    "entity": "acme",
                    "domains": ["legal", "finance"],
                    "domain_count": 2,
                    "finding_count": 4,
                    "risk_score": 8.5,
                    "has_p0": False,
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "Acme Corp" in html
        assert "cross-domain-card" in html
        assert "domain-pill" in html

    def test_renders_interaction_matrix(self) -> None:
        """Matrix table rendered with domain pair counts."""
        data = self._make_data_with_risks(
            [
                {
                    "entity": "acme",
                    "domains": ["legal", "finance", "commercial"],
                    "domain_count": 3,
                    "finding_count": 5,
                    "risk_score": 10.0,
                    "has_p0": True,
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "Domain Interaction Matrix" in html
        assert "Legal" in html
        assert "Finance" in html

    def test_narrative_rendered(self) -> None:
        """Connection narrative appears in output."""
        data = self._make_data_with_risks(
            [
                {
                    "entity": "acme",
                    "domains": ["finance", "legal"],
                    "domain_count": 2,
                    "finding_count": 3,
                    "risk_score": 6.0,
                    "has_p0": False,
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "cross-domain-narrative" in html

    def test_compound_severity_badge(self) -> None:
        """Compound severity badge appears on cards."""
        data = self._make_data_with_risks(
            [
                {
                    "entity": "acme",
                    "domains": ["legal", "finance", "commercial"],
                    "domain_count": 3,
                    "finding_count": 3,
                    "risk_score": 9.0,
                    "has_p0": False,
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "severity-badge" in html

    def test_xss_in_entity_name_escaped(self) -> None:
        """XSS in entity name is escaped."""
        data = ReportComputedData(
            cross_domain_risks=[
                {
                    "entity": "<script>alert(1)</script>",
                    "domains": ["legal", "finance"],
                    "domain_count": 2,
                    "finding_count": 2,
                    "risk_score": 5.0,
                    "has_p0": False,
                }
            ],
            display_names={"<script>alert(1)</script>": "<script>alert(1)</script>"},
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_triggers_section_rendered(self) -> None:
        """Trigger analysis renders when triggers present."""
        data = ReportComputedData(
            cross_domain_triggers=[
                {
                    "subject": "acme",
                    "source_agent": "finance",
                    "target_agent": "legal",
                    "trigger_type": "revenue_contract_mismatch",
                    "priority": "P1",
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "Cross-Domain Verification" in html
        assert "revenue_contract_mismatch" in html

    def test_css_included(self) -> None:
        """Cross-domain CSS is included in render_css."""
        from dd_agents.reporting.html_base import render_css

        css = render_css()
        assert ".cross-domain-card" in css
        assert ".domain-pill" in css

    def test_xss_in_trigger_fields_escaped(self) -> None:
        """XSS in trigger source_agent/trigger_type is escaped."""
        data = ReportComputedData(
            cross_domain_triggers=[
                {
                    "subject": "acme",
                    "source_agent": "<img src=x onerror=alert(1)>",
                    "target_agent": "legal",
                    "trigger_type": "<script>xss</script>",
                    "priority": "P1",
                }
            ]
        )
        renderer = CrossDomainRenderer(data, {}, {})
        html = renderer.render()
        assert "<img src=x" not in html
        assert "&lt;img" in html
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestPairNarrative:
    """Tests for domain pair narrative lookup."""

    def test_reversed_pair_still_matches(self) -> None:
        """Pair ['legal', 'finance'] matches same as ['finance', 'legal']."""
        from dd_agents.reporting.html_cross_domain import _get_pair_narrative

        n1 = _get_pair_narrative(["finance", "legal"])
        n2 = _get_pair_narrative(["legal", "finance"])
        assert n1 == n2
        assert n1 != ""

    def test_unknown_pair_gets_generic(self) -> None:
        """Unknown domain pair gets generic systemic risk narrative."""
        from dd_agents.reporting.html_cross_domain import _get_pair_narrative

        n = _get_pair_narrative(["esg", "hr"])
        assert "systemic risk" in n.lower() or "cross-functional" in n.lower()

    def test_single_domain_returns_empty(self) -> None:
        """Single domain returns empty narrative."""
        from dd_agents.reporting.html_cross_domain import _get_pair_narrative

        assert _get_pair_narrative(["legal"]) == ""
