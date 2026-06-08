"""Unit tests for 3-Layer Drill-Down architecture (Issue #197).

Covers:
- Domain summary computation (RAG status, top categories, top findings)
- Priority score computation for dashboard findings
- DomainSummaryRenderer HTML output (cards, grid, links)
- Empty state handling
- Data attribute presence for filter bar integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer
from dd_agents.reporting.html_base import fmt_currency
from dd_agents.reporting.html_domain_summary import DomainSummaryRenderer


def _make_finding(
    severity: str = "P2",
    title: str = "Test finding",
    agent: str = "legal",
    category: str = "contract_risk",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "description": "A test description",
        "agent": agent,
        "category": category,
        "citations": [],
    }


class TestDomainSummaryComputation:
    """Tests for domain_summaries computed field."""

    def test_domain_summaries_populated(self) -> None:
        """compute() populates domain_summaries dict."""
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P0", agent="legal")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        assert "legal" in data.domain_summaries
        assert data.domain_summaries["legal"]["finding_count"] == 1

    def test_rag_red_on_p0(self) -> None:
        """Domain with P0 gets RAG=red."""
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P0", agent="finance")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        assert data.domain_summaries["finance"]["rag_status"] == "red"

    def test_rag_red_on_three_p1(self) -> None:
        """Domain with 3+ P1 gets RAG=red."""
        findings = [_make_finding("P1", title=f"Issue {i}", agent="legal") for i in range(3)]
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        assert data.domain_summaries["legal"]["rag_status"] == "red"

    def test_rag_amber_on_p1(self) -> None:
        """Domain with 1 P1 gets RAG=amber."""
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P1", agent="commercial")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        assert data.domain_summaries["commercial"]["rag_status"] == "amber"

    def test_rag_green_no_findings(self) -> None:
        """Domain with no findings gets RAG=green."""
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P2", agent="legal")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        # Finance has no findings
        assert data.domain_summaries.get("finance", {}).get("rag_status") == "green"

    def test_top_categories_populated(self) -> None:
        """Top categories list contains category names and counts."""
        findings = [
            _make_finding("P2", agent="legal", category="contract_risk"),
            _make_finding("P2", agent="legal", category="contract_risk"),
            _make_finding("P1", agent="legal", category="ip_issues"),
        ]
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        cats = data.domain_summaries["legal"]["top_categories"]
        assert len(cats) == 2
        assert cats[0]["count"] == 2

    def test_top_findings_preview(self) -> None:
        """Top findings preview has title and severity."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [_make_finding("P0", title="Critical breach", agent="legal")],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        preview = data.domain_summaries["legal"]["top_findings_preview"]
        assert len(preview) == 1
        assert preview[0]["title"] == "Critical breach"
        assert preview[0]["severity"] == "P0"


class TestDashboardFindings:
    """Tests for dashboard_findings priority scoring."""

    def test_p0_ranked_above_p2(self) -> None:
        """P0 findings appear before P2 in priority ranking."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    _make_finding("P2", title="Minor issue"),
                    _make_finding("P0", title="Critical issue"),
                ],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert len(data.dashboard_findings) == 2
        assert data.dashboard_findings[0]["title"] == "Critical issue"

    def test_max_five_findings(self) -> None:
        """Dashboard findings capped at 5."""
        findings = [_make_finding("P1", title=f"Issue {i}", agent="legal") for i in range(10)]
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        assert len(data.dashboard_findings) <= 5

    def test_empty_on_no_material_findings(self) -> None:
        """No material findings → empty dashboard_findings."""
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": [], "gaps": []}}
        data = ReportDataComputer().compute(merged)
        assert data.dashboard_findings == []


class TestDomainSummaryRenderer:
    """Tests for DomainSummaryRenderer HTML output."""

    def test_renders_domain_cards(self, tmp_path: Path) -> None:
        """Renderer outputs domain card grid."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P1", agent="legal")], "gaps": []},
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "domain-card-grid" in content
        assert "Domain Overview" in content

    def test_empty_state_no_section(self) -> None:
        """No domain summaries → empty string (no section rendered)."""
        data = ReportComputedData()
        renderer = DomainSummaryRenderer(data, {}, {})
        assert renderer.render() == ""

    def test_nav_links_present(self, tmp_path: Path) -> None:
        """Domain cards contain navigation links to detail sections."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P0", agent="finance")], "gaps": []},
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "href='#sec-domain-finance'" in content or "href='#sec-domain-legal'" in content

    def test_xss_in_title_escaped(self, tmp_path: Path) -> None:
        """XSS payloads in finding titles are escaped in domain summary."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [_make_finding("P0", title="<img onerror=alert(1)>", agent="legal")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "<img onerror=" not in content
        assert "&lt;img" in content


class TestDomainSummaryEdgeCases:
    """Edge case tests for domain summary computation."""

    def test_rag_amber_on_p2_only(self) -> None:
        """Domain with only P2 findings gets amber RAG status."""
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P2", agent="legal")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        legal_summary = data.domain_summaries.get("legal", {})
        assert legal_summary.get("rag_status") == "amber"

    def test_rag_red_on_three_p1(self) -> None:
        """Domain with 3+ P1 findings gets red RAG status."""
        findings = [_make_finding("P1", title=f"Issue {i}", agent="finance") for i in range(3)]
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        fin_summary = data.domain_summaries.get("finance", {})
        assert fin_summary.get("rag_status") == "red"

    def test_rag_amber_on_two_p1(self) -> None:
        """Domain with exactly 2 P1 findings (below threshold) gets amber."""
        findings = [_make_finding("P1", title=f"Issue {i}", agent="finance") for i in range(2)]
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        fin_summary = data.domain_summaries.get("finance", {})
        assert fin_summary.get("rag_status") == "amber"

    def test_dashboard_findings_ordering(self) -> None:
        """Dashboard findings are P0-first, P2-after."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    _make_finding("P2", title="Minor issue", agent="legal"),
                    _make_finding("P0", title="Critical issue", agent="legal"),
                ],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert len(data.dashboard_findings) == 2
        assert data.dashboard_findings[0]["title"] == "Critical issue"
        assert data.dashboard_findings[1]["title"] == "Minor issue"


class TestDashboardKpis:
    """Issue #197: Layer-1 KPI strip computed field."""

    _LABELS = {"Findings", "Critical (P0/P1)", "Domains at Risk", "Revenue at Risk", "Entities"}

    def test_dashboard_kpis_populated(self) -> None:
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P0", agent="legal")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        assert len(data.dashboard_kpis) == 5
        assert {k["label"] for k in data.dashboard_kpis} == self._LABELS

    def test_kpi_entities_count(self) -> None:
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P1", agent="legal")], "gaps": []},
            "b": {"subject": "b", "findings": [_make_finding("P2", agent="finance")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        entities = next(k for k in data.dashboard_kpis if k["label"] == "Entities")
        assert entities["value"] == "2"

    def test_kpi_domains_at_risk(self) -> None:
        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    _make_finding("P0", agent="legal"),
                    _make_finding("P0", agent="finance"),
                ],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        dar = next(k for k in data.dashboard_kpis if k["label"] == "Domains at Risk")
        assert dar["value"] == "2"
        assert dar["intent"] == "critical"

    def test_kpi_critical_intent(self) -> None:
        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [_make_finding("P0", agent="legal")], "gaps": []},
        }
        data = ReportDataComputer().compute(merged)
        crit = next(k for k in data.dashboard_kpis if k["label"] == "Critical (P0/P1)")
        assert crit["intent"] == "critical"

    def test_kpi_clean_deal(self) -> None:
        merged: dict[str, Any] = {"a": {"subject": "a", "findings": [], "gaps": []}}
        data = ReportDataComputer().compute(merged)
        assert len(data.dashboard_kpis) == 5
        findings = next(k for k in data.dashboard_kpis if k["label"] == "Findings")
        dar = next(k for k in data.dashboard_kpis if k["label"] == "Domains at Risk")
        crit = next(k for k in data.dashboard_kpis if k["label"] == "Critical (P0/P1)")
        assert findings["value"] == "0"
        assert dar["value"] == "0"
        assert crit["intent"] == "neutral"

    def test_kpi_revenue_at_risk_is_deduped_exposure_not_total_arr(self) -> None:
        """Revenue at Risk KPI shows the at-risk exposure, NOT the full ARR base."""
        merged: dict[str, Any] = {
            "acme": {
                "subject": "Acme",
                "findings": [
                    {
                        "severity": "P1",
                        "title": "Change of control consent required",
                        "description": "Assignment consent needed on transfer of control",
                        "agent": "legal",
                        "category": "change_of_control",
                        "citations": [],
                    }
                ],
                "gaps": [],
                "cross_references": [{"data_point": "ARR", "reference_value": "$1,000,000"}],
            },
            # Beta has revenue but NO findings → contributes to total ARR, not exposure.
            "beta": {
                "subject": "Beta",
                "findings": [],
                "gaps": [],
                "cross_references": [{"data_point": "ARR", "reference_value": "$4,000,000"}],
            },
        }
        data = ReportDataComputer().compute(merged)
        rar = next(k for k in data.dashboard_kpis if k["label"] == "Revenue at Risk")
        # Only Acme ($1M) is at risk; Beta's $4M is not. KPI must NOT show $5M total.
        assert "5" not in rar["value"]
        assert rar["value"] == fmt_currency(1_000_000.0)
        assert rar["intent"] == "critical"
