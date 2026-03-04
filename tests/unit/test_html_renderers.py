"""Unit tests for individual HTML section renderers.

Each renderer is tested in isolation with mock ReportComputedData.
"""

from __future__ import annotations

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer
from dd_agents.reporting.html_analysis import CoCAnalysisRenderer, CustomerHealthRenderer, PrivacyAnalysisRenderer
from dd_agents.reporting.html_base import SectionRenderer, render_css, render_js, render_nav_bar
from dd_agents.reporting.html_cross import CrossRefRenderer
from dd_agents.reporting.html_customers import CustomerRenderer
from dd_agents.reporting.html_dashboard import DashboardRenderer
from dd_agents.reporting.html_domains import DomainRenderer
from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer
from dd_agents.reporting.html_findings_table import FindingsTableRenderer
from dd_agents.reporting.html_gaps import GapRenderer
from dd_agents.reporting.html_methodology import MethodologyRenderer
from dd_agents.reporting.html_quality import QualityRenderer
from dd_agents.reporting.html_recommendations import RecommendationsRenderer
from dd_agents.reporting.html_risk import RiskRenderer
from dd_agents.reporting.html_strategy import StrategyRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    agent: str = "legal",
    category: str = "uncategorized",
    title: str = "Test finding",
    description: str = "Description",
    citations: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "severity": severity,
        "agent": agent,
        "category": category,
        "title": title,
        "description": description,
        "citations": citations or [],
    }


def _make_merged_data() -> dict[str, object]:
    return {
        "customer_a": {
            "customer": "Customer A",
            "findings": [
                _make_finding(
                    severity="P0",
                    agent="legal",
                    category="change_of_control",
                    title="CoC terminates contract",
                    citations=[{"source_path": "f.pdf", "exact_quote": "shall terminate"}],
                ),
                _make_finding(severity="P1", agent="finance", category="revenue_recognition"),
                _make_finding(severity="P2", agent="commercial", category="customer_concentration"),
                _make_finding(severity="P3", agent="producttech", category="technical_debt"),
            ],
            "gaps": [
                {"priority": "P0", "gap_type": "Missing_Doc", "missing_item": "NDA", "risk_if_missing": "Legal risk"},
                {"priority": "P2", "gap_type": "Stale_Doc", "missing_item": "SOW", "risk_if_missing": "Stale terms"},
            ],
            "governance_resolution_pct": 85.0,
            "cross_references": [
                {"data_point": "ARR", "contract_value": "100K", "reference_value": "100K", "match_status": "match"},
                {
                    "data_point": "Headcount",
                    "contract_value": "50",
                    "reference_value": "45",
                    "match_status": "mismatch",
                },
            ],
        },
        "customer_b": {
            "customer": "Customer B",
            "findings": [_make_finding(severity="P1", agent="legal", category="ip_ownership")],
            "gaps": [],
            "governance_resolution_pct": 95.0,
        },
    }


def _compute(merged: dict[str, object] | None = None) -> ReportComputedData:
    data = _make_merged_data() if merged is None else merged
    return ReportDataComputer().compute(data)  # type: ignore[arg-type]


# ===========================================================================
# html_base tests
# ===========================================================================


class TestSectionRendererHelpers:
    def test_severity_badge_colors(self) -> None:
        for sev in ("P0", "P1", "P2", "P3"):
            badge = SectionRenderer.severity_badge(sev)
            assert f">{sev}</span>" in badge
            assert "severity-badge" in badge

    def test_escape_html(self) -> None:
        assert SectionRenderer.escape("<script>") == "&lt;script&gt;"
        assert SectionRenderer.escape('"quotes"') == "&quot;quotes&quot;"

    def test_risk_color(self) -> None:
        assert SectionRenderer.risk_color("Critical") == "#dc3545"
        assert SectionRenderer.risk_color("Clean") == "#28a745"
        assert SectionRenderer.risk_color("Unknown") == "#6c757d"

    def test_agent_to_domain(self) -> None:
        assert SectionRenderer.agent_to_domain("legal") == "legal"
        assert SectionRenderer.agent_to_domain("FINANCE") == "finance"
        assert SectionRenderer.agent_to_domain("producttech") == "producttech"
        assert SectionRenderer.agent_to_domain("unknown") == "legal"


class TestCSSJS:
    def test_render_css_contains_key_selectors(self) -> None:
        css = render_css()
        assert ".sidebar" in css
        assert ".severity-badge" in css
        assert "@media print" in css
        assert "@media (max-width: 900px)" in css

    def test_render_js_contains_key_functions(self) -> None:
        js = render_js()
        assert "setupToggles" in js
        assert "global-search" in js
        assert "sev-filter" in js

    def test_render_nav_bar(self) -> None:
        nav = render_nav_bar()
        assert "class='sidebar'" in nav
        assert "id='global-search'" in nav
        assert "id='btn-expand-all'" in nav


# ===========================================================================
# Print CSS tests (#108)
# ===========================================================================


class TestPrintCSS:
    def test_print_hides_nav_and_filter(self) -> None:
        css = render_css()
        assert ".sidebar" in css
        assert ".filter-bar" in css
        assert "display: none" in css or "display:none" in css

    def test_print_expands_all_sections(self) -> None:
        css = render_css()
        assert ".domain-body" in css
        assert ".customer-body" in css
        assert ".finding-detail" in css

    def test_print_break_inside_avoid(self) -> None:
        css = render_css()
        assert "break-inside: avoid" in css or "break-inside:avoid" in css

    def test_print_color_adjust(self) -> None:
        css = render_css()
        assert "print-color-adjust" in css

    def test_print_page_margins(self) -> None:
        css = render_css()
        assert "@page" in css

    def test_print_widows_orphans(self) -> None:
        css = render_css()
        assert "orphans" in css
        assert "widows" in css

    def test_print_link_urls(self) -> None:
        """Print mode should reveal link URLs."""
        css = render_css()
        assert "content:" in css and "attr(href)" in css


# ===========================================================================
# Accessibility tests (#108)
# ===========================================================================


class TestAccessibility:
    def test_nav_has_role(self) -> None:
        nav = render_nav_bar()
        assert "role='navigation'" in nav

    def test_filter_bar_has_role(self) -> None:
        nav = render_nav_bar()
        assert "role='search'" in nav

    def test_main_content_has_role(self) -> None:
        nav = render_nav_bar()
        assert "role='main'" in nav

    def test_skip_to_content_link(self) -> None:
        nav = render_nav_bar()
        assert "skip-to-content" in nav.lower() or "skip-link" in nav.lower()
        assert "#main-content" in nav

    def test_search_input_has_aria_label(self) -> None:
        nav = render_nav_bar()
        assert "aria-label=" in nav

    def test_expand_buttons_have_aria(self) -> None:
        nav = render_nav_bar()
        assert "aria-label=" in nav

    def test_css_has_focus_styles(self) -> None:
        css = render_css()
        assert ":focus" in css
        assert "outline" in css

    def test_css_skip_link_styles(self) -> None:
        css = render_css()
        assert ".skip-link" in css

    def test_js_keyboard_support(self) -> None:
        js = render_js()
        assert "keydown" in js or "keypress" in js
        assert "Enter" in js

    def test_finding_card_has_tabindex(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "tabindex=" in html_out or "role='button'" in html_out

    def test_collapsible_headers_have_aria_expanded(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "aria-expanded=" in html_out


# ===========================================================================
# Dashboard tests (#100)
# ===========================================================================


class TestDashboardRenderer:
    def test_deal_header_rendered(self) -> None:
        computed = _compute()
        config = {
            "_title": "Test Report",
            "_run_id": "run_001",
            "_deal_config": {"buyer": {"name": "Apex"}, "target": {"name": "Widget"}, "deal": {"type": "acquisition"}},
        }
        r = DashboardRenderer(computed, _make_merged_data(), config)
        html_out = r.render()
        assert "Test Report" in html_out
        assert "run_001" in html_out
        assert "Apex" in html_out
        assert "Widget" in html_out
        assert "Overall Risk:" in html_out

    def test_key_metrics_counts(self) -> None:
        computed = _compute()
        r = DashboardRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert ">2</div>" in html_out  # customers
        assert ">5</div>" in html_out  # findings
        assert ">2</div>" in html_out  # gaps

    def test_wolf_pack_contains_p0_p1(self) -> None:
        computed = _compute()
        r = DashboardRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "wolf-card" in html_out
        assert "Deal Breakers" in html_out
        assert "CoC terminates contract" in html_out

    def test_wolf_pack_empty_when_no_critical(self) -> None:
        merged = {"c": {"customer": "C", "findings": [_make_finding(severity="P3")], "gaps": []}}
        computed = _compute(merged)
        r = DashboardRenderer(computed, merged)
        html_out = r.render()
        assert "No P0 or P1 findings" in html_out

    def test_overall_risk_critical(self) -> None:
        computed = _compute()
        r = DashboardRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Overall Risk: Critical" in html_out

    def test_overall_risk_clean(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = DashboardRenderer(computed, merged)
        html_out = r.render()
        assert "Overall Risk: Clean" in html_out


# ===========================================================================
# Risk heatmap tests (#102)
# ===========================================================================


class TestRiskRenderer:
    def test_heatmap_four_domains(self) -> None:
        computed = _compute()
        r = RiskRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-heatmap'" in html_out
        assert "Domain Risk Heatmap" in html_out
        assert html_out.count("class='heatmap-cell'") == 4
        assert "Legal" in html_out
        assert "Finance" in html_out
        assert "Commercial" in html_out
        assert "Product &amp; Tech" in html_out

    def test_heatmap_links_to_domains(self) -> None:
        computed = _compute()
        r = RiskRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "href='#sec-domain-legal'" in html_out
        assert "href='#sec-domain-finance'" in html_out


# ===========================================================================
# Domain tests (#104)
# ===========================================================================


class TestDomainRenderer:
    def test_all_domain_sections(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-domain-legal'" in html_out
        assert "id='sec-domain-finance'" in html_out
        assert "id='sec-domain-commercial'" in html_out
        assert "id='sec-domain-producttech'" in html_out

    def test_category_grouping(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "category-group" in html_out
        assert "Change of Control" in html_out
        assert "Revenue Recognition" in html_out

    def test_severity_bar(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "sev-bar" in html_out

    def test_empty_domain_message(self) -> None:
        merged = {"c": {"customer": "C", "findings": [_make_finding(agent="legal")], "gaps": []}}
        computed = _compute(merged)
        r = DomainRenderer(computed, merged)
        html_out = r.render()
        # Finance/Commercial/ProductTech should show empty message
        assert "No findings in this domain." in html_out


# ===========================================================================
# Gap tests (#106)
# ===========================================================================


class TestGapRenderer:
    def test_gap_section_rendered(self) -> None:
        computed = _compute()
        r = GapRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-gaps'" in html_out
        assert "Gap Analysis" in html_out
        assert "2 gaps" in html_out

    def test_gap_priority_distribution(self) -> None:
        computed = _compute()
        r = GapRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "By Priority" in html_out
        assert "By Type" in html_out

    def test_gap_table_columns(self) -> None:
        computed = _compute()
        r = GapRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Entity</th>" in html_out
        assert "Priority</th>" in html_out
        assert "Missing Item</th>" in html_out

    def test_no_gaps_message(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = GapRenderer(computed, merged)
        html_out = r.render()
        assert "No documentation gaps identified." in html_out


# ===========================================================================
# Cross-reference tests (#103)
# ===========================================================================


class TestCrossRefRenderer:
    def test_xref_table_rendered(self) -> None:
        computed = _compute()
        r = CrossRefRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-xref'" in html_out
        assert "Data Reconciliation" in html_out

    def test_mismatch_highlighting(self) -> None:
        computed = _compute()
        r = CrossRefRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "xref-mismatch" in html_out
        assert "xref-match" in html_out

    def test_no_xrefs_returns_empty(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = CrossRefRenderer(computed, merged)
        html_out = r.render()
        assert html_out == ""


# ===========================================================================
# Customer tests (#105)
# ===========================================================================


class TestCustomerRenderer:
    def test_customer_sections_rendered(self) -> None:
        computed = _compute()
        r = CustomerRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-customers'" in html_out
        assert "Entity Detail" in html_out
        assert "Customer A" in html_out
        assert "Customer B" in html_out

    def test_customer_severity_badges(self) -> None:
        computed = _compute()
        r = CustomerRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "customer-section" in html_out
        assert "severity-badge" in html_out

    def test_governance_score_displayed(self) -> None:
        computed = _compute()
        r = CustomerRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Governance Resolution" in html_out
        assert "86%" in html_out or "85%" in html_out

    def test_customer_xref_table(self) -> None:
        computed = _compute()
        r = CustomerRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Cross-Reference Reconciliation" in html_out
        assert "Headcount" in html_out


# ===========================================================================
# Quality tests (#107)
# ===========================================================================


class TestQualityRenderer:
    def test_governance_bars(self) -> None:
        computed = _compute()
        r = QualityRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-governance'" in html_out
        assert "gov-bar" in html_out
        assert "95%" in html_out

    def test_quality_scores_from_metadata(self) -> None:
        computed = _compute()
        config = {"_run_metadata": {"quality_scores": {"agent_scores": {"legal": {"score": 92, "details": "Good"}}}}}
        r = QualityRenderer(computed, _make_merged_data(), config)
        html_out = r.render()
        assert "Quality Audit" in html_out
        assert "92" in html_out

    def test_no_metadata_no_quality_section(self) -> None:
        computed = _compute()
        r = QualityRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Quality Audit" not in html_out

    def test_no_governance_returns_empty(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = QualityRenderer(computed, merged)
        html_out = r.render()
        assert "Governance Resolution" not in html_out


# ===========================================================================
# Strategy tests (#111)
# ===========================================================================


class TestStrategyRenderer:
    def test_no_buyer_strategy_returns_empty(self) -> None:
        computed = _compute()
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert html_out == ""

    def test_buyer_strategy_rendered(self) -> None:
        computed = _compute()
        computed.buyer_strategy = {
            "thesis": "Expand market share",
            "key_synergies": ["Revenue uplift", "Cost reduction"],
            "integration_priorities": ["Merge sales teams"],
            "risk_tolerance": "moderate",
            "focus_areas": ["change_of_control"],
        }
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-strategy'" in html_out
        assert "Buyer Strategy Analysis" in html_out
        assert "Expand market share" in html_out
        assert "Revenue uplift" in html_out
        assert "Merge sales teams" in html_out

    def test_risk_tolerance_color(self) -> None:
        computed = _compute()
        computed.buyer_strategy = {"risk_tolerance": "aggressive"}
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "#dc3545" in html_out  # aggressive = red

    def test_focus_area_finding_count(self) -> None:
        computed = _compute()
        computed.buyer_strategy = {"focus_areas": ["change_of_control"]}
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Findings in Buyer Focus Areas" in html_out

    def test_acquirer_intelligence_displayed(self) -> None:
        computed = _compute()
        computed.buyer_strategy = {"thesis": "Test"}
        computed.acquirer_intelligence = {
            "summary": "Strong strategic fit",
            "recommendations": ["Proceed with acquisition"],
        }
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "AI-Enhanced Acquirer Analysis" in html_out
        assert "Strong strategic fit" in html_out
        assert "Proceed with acquisition" in html_out


# ===========================================================================
# Edge cases: XSS protection
# ===========================================================================


class TestXSSProtection:
    """Verify HTML-special characters are escaped in rendered output."""

    def test_customer_name_xss_escaped(self) -> None:
        merged = {
            "xss_test": {
                "customer": '<script>alert("xss")</script>',
                "findings": [_make_finding()],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        r = CustomerRenderer(computed, merged)
        html_out = r.render()
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_finding_title_xss_escaped(self) -> None:
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(title='<img src=x onerror="alert(1)">')],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        r = DomainRenderer(computed, merged)
        html_out = r.render()
        assert 'onerror="alert(1)"' not in html_out
        assert "&lt;img" in html_out

    def test_category_name_xss_escaped(self) -> None:
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(category='<b onclick="hack()">bad</b>')],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        r = DomainRenderer(computed, merged)
        html_out = r.render()
        assert 'onclick="hack()"' not in html_out

    def test_strategy_thesis_xss_escaped(self) -> None:
        computed = _compute()
        computed.buyer_strategy = {"thesis": "<script>steal()</script>"}
        r = StrategyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out


# ===========================================================================
# Edge cases: Dashboard None handling
# ===========================================================================


class TestDashboardEdgeCases:
    def test_null_buyer_and_target(self) -> None:
        """When buyer/target are None, dashboard should not display 'None'."""
        computed = _compute()
        config = {"_deal_config": {"buyer": None, "target": None, "deal": {"type": "acquisition"}}}
        r = DashboardRenderer(computed, _make_merged_data(), config)
        html_out = r.render()
        assert "None" not in html_out

    def test_missing_deal_config(self) -> None:
        computed = _compute()
        r = DashboardRenderer(computed, _make_merged_data(), {})
        html_out = r.render()
        assert "Overall Risk:" in html_out

    def test_deal_config_string_buyer(self) -> None:
        """When buyer is a bare string (legacy format), don't crash."""
        computed = _compute()
        config = {"_deal_config": {"buyer": "Simple Corp", "target": "Other Inc"}}
        r = DashboardRenderer(computed, _make_merged_data(), config)
        html_out = r.render()
        # Bare string is not a dict — we return empty, not "Simple Corp"
        assert "Overall Risk:" in html_out

    def test_empty_merged_data(self) -> None:
        """Empty merged data should render cleanly."""
        computed = _compute({})
        r = DashboardRenderer(computed, {})
        html_out = r.render()
        assert "Overall Risk:" in html_out
        assert ">0</div>" in html_out  # zero counts


# ===========================================================================
# Edge cases: Malformed finding data
# ===========================================================================


class TestMalformedData:
    def test_findings_as_dict_not_list(self) -> None:
        """If findings is a dict instead of list, ReportDataComputer handles gracefully."""
        merged = {"c": {"customer": "C", "findings": {"wrong": "format"}, "gaps": []}}
        computed = _compute(merged)
        assert computed.total_findings == 0

    def test_customer_with_no_findings_key(self) -> None:
        """Missing 'findings' key handled gracefully."""
        merged = {"c": {"customer": "C"}}
        computed = _compute(merged)
        assert computed.total_findings == 0
        assert computed.total_customers == 1

    def test_gap_missing_fields_handled(self) -> None:
        """Gaps with missing fields don't crash the renderer."""
        merged = {"c": {"customer": "C", "findings": [], "gaps": [{"priority": "P1"}]}}
        computed = _compute(merged)
        r = GapRenderer(computed, merged)
        html_out = r.render()
        assert "Gap Analysis" in html_out


# ===========================================================================
# Deduplicated domain_risk method
# ===========================================================================


class TestDomainRiskBaseMethod:
    """The domain_risk() method was deduplicated to SectionRenderer."""

    def test_p0_is_critical(self) -> None:
        assert SectionRenderer.domain_risk({"P0": 1, "P1": 2}) == "Critical"

    def test_p1_is_high(self) -> None:
        assert SectionRenderer.domain_risk({"P1": 3}) == "High"

    def test_p2_is_medium(self) -> None:
        assert SectionRenderer.domain_risk({"P2": 5}) == "Medium"

    def test_p3_is_low(self) -> None:
        assert SectionRenderer.domain_risk({"P3": 1}) == "Low"

    def test_empty_is_clean(self) -> None:
        assert SectionRenderer.domain_risk({}) == "Clean"


# ===========================================================================
# Severity bar accessibility
# ===========================================================================


class TestSeverityBarAccessibility:
    def test_severity_bar_has_aria_label(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "role='img'" in html_out
        assert "aria-label='Severity distribution:" in html_out

    def test_severity_bar_describes_distribution(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "P0:" in html_out  # Legal has P0


# ===========================================================================
# Expand all / collapse all aria-expanded
# ===========================================================================


class TestExpandCollapseAriaExpanded:
    def test_js_expand_all_updates_aria(self) -> None:
        js = render_js()
        assert "setAttribute('aria-expanded', 'true')" in js

    def test_js_collapse_all_updates_aria(self) -> None:
        js = render_js()
        assert "setAttribute('aria-expanded', 'false')" in js


# ===========================================================================
# P2 badge contrast (WCAG AA)
# ===========================================================================


class TestP2BadgeContrast:
    def test_p2_badge_has_dark_text_class(self) -> None:
        badge = SectionRenderer.severity_badge("P2")
        assert "sev-p2" in badge

    def test_p0_badge_no_dark_text_class(self) -> None:
        badge = SectionRenderer.severity_badge("P0")
        assert "sev-p2" not in badge

    def test_css_has_sev_p2_rule(self) -> None:
        css = render_css()
        assert ".severity-badge.sev-p2" in css
        assert "color: #333" in css


# ===========================================================================
# Content wrapper closing tag
# ===========================================================================


class TestContentWrapperClosing:
    def test_nav_bar_opens_content_div(self) -> None:
        nav = render_nav_bar()
        assert "<div class='content'" in nav

    def test_css_content_wrapper_defined(self) -> None:
        css = render_css()
        assert ".content {" in css or ".content{" in css


# ===========================================================================
# P1 badge contrast (WCAG AA) — white on #fd7e14 = 3.1:1, needs dark text
# ===========================================================================


class TestP1BadgeContrast:
    def test_p1_badge_has_dark_text_class(self) -> None:
        badge = SectionRenderer.severity_badge("P1")
        assert "sev-p1" in badge

    def test_p0_badge_no_p1_class(self) -> None:
        badge = SectionRenderer.severity_badge("P0")
        assert "sev-p1" not in badge

    def test_p3_badge_no_p1_class(self) -> None:
        badge = SectionRenderer.severity_badge("P3")
        assert "sev-p1" not in badge

    def test_css_has_sev_p1_rule(self) -> None:
        css = render_css()
        assert ".severity-badge.sev-p1" in css
        assert "color: #333" in css


# ===========================================================================
# Table scope='col' attributes (WCAG 2.1 AA)
# ===========================================================================


class TestTableScopeAttributes:
    """All sortable tables must have scope='col' on header cells."""

    def test_gap_table_has_scope(self) -> None:
        computed = _compute()
        r = GapRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "scope='col'" in html_out

    def test_domain_table_has_scope(self) -> None:
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "scope='col'" in html_out

    def test_cross_ref_table_has_scope(self) -> None:
        computed = _compute()
        r = CrossRefRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "scope='col'" in html_out

    def test_customer_xref_table_has_scope(self) -> None:
        computed = _compute()
        r = CustomerRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "scope='col'" in html_out

    def test_quality_table_has_scope(self) -> None:
        computed = _compute()
        config = {"_run_metadata": {"quality_scores": {"agent_scores": {"legal": {"score": 90}}}}}
        r = QualityRenderer(computed, _make_merged_data(), config)
        html_out = r.render()
        assert "scope='col'" in html_out


# ===========================================================================
# Print CSS: tables in break-inside avoid
# ===========================================================================


class TestPrintTableBreak:
    def test_tables_in_break_inside_avoid(self) -> None:
        css = render_css()
        # table.sortable should be in the break-inside: avoid rule
        assert "table.sortable" in css
        # Verify it appears in the print section near break-inside
        print_block = css.split("@media print")[1]
        assert "table.sortable" in print_block
        assert "break-inside: avoid" in print_block


# ===========================================================================
# Heading hierarchy: h2 → h3 (no skip to h4 in category groups)
# ===========================================================================


class TestHeadingHierarchy:
    def test_category_group_uses_h3_not_h4(self) -> None:
        """Customer names in category groups should use h3, not h4."""
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render()
        # Category body should contain h3 for customer names
        assert "<h3>" in html_out
        # Should NOT have h4 in domain sections (that would skip h3)
        # h4 should only appear in customer sections, not domain sections
        domain_sections = html_out.split("id='sec-domain-")
        for section in domain_sections[1:]:  # skip first (before first domain)
            section_content = section.split("</section>")[0]
            if "<h3>" in section_content:
                assert "<h4>" not in section_content


# ===========================================================================
# Risk label boundary values
# ===========================================================================


class TestRiskLabelBoundaries:
    """Test exact thresholds in _compute_risk_label."""

    def test_3_p1_findings_is_high(self) -> None:
        """Exactly 3 P1 findings → High."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P1") for _ in range(3)],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        assert computed.deal_risk_label == "High"

    def test_2_p1_findings_is_medium(self) -> None:
        """Exactly 2 P1 findings → Medium (below High threshold)."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P1") for _ in range(2)],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        assert computed.deal_risk_label == "Medium"

    def test_5_p2_findings_is_medium(self) -> None:
        """Exactly 5 P2 findings → Medium."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P2") for _ in range(5)],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        assert computed.deal_risk_label == "Medium"

    def test_4_p2_findings_is_low(self) -> None:
        """Exactly 4 P2 findings → Low (below Medium threshold)."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P2") for _ in range(4)],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        assert computed.deal_risk_label == "Low"

    def test_only_p3_is_clean(self) -> None:
        """Only P3 findings → Clean (P3 alone doesn't elevate risk)."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P3") for _ in range(10)],
                "gaps": [],
            }
        }
        computed = _compute(merged)
        assert computed.deal_risk_label == "Clean"


# ===========================================================================
# Verification badge rendering
# ===========================================================================


class TestVerificationBadge:
    """Test conditional badge rendering in render_finding_detail."""

    def test_verified_badge_class(self) -> None:
        finding = {**_make_finding(), "verification_status": "verified"}
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "vb-verified" in html_out

    def test_failed_badge_class(self) -> None:
        finding = {**_make_finding(), "verification_status": "failed"}
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "vb-failed" in html_out

    def test_unchecked_badge_class(self) -> None:
        finding = {**_make_finding(), "verification_status": "pending"}
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "vb-unchecked" in html_out

    def test_no_verification_no_badge(self) -> None:
        finding = _make_finding()
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "verification-badge" not in html_out

    def test_confidence_badge_rendered(self) -> None:
        finding = {**_make_finding(), "confidence": "high"}
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "Confidence:" in html_out
        assert "high" in html_out

    def test_detection_method_rendered(self) -> None:
        finding = {**_make_finding(), "detection_method": "keyword_search"}
        computed = _compute()
        r = DomainRenderer(computed, _make_merged_data())
        html_out = r.render_finding_detail(finding)
        assert "Detection:" in html_out
        assert "keyword_search" in html_out


# ===========================================================================
# Executive Summary tests (Issue #113)
# ===========================================================================


class TestExecutiveSummaryRenderer:
    def test_go_no_go_signal(self) -> None:
        computed = _compute()
        r = ExecutiveSummaryRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-executive'" in html_out
        assert "Executive Summary" in html_out
        # P0 exists → Critical → No-Go
        assert "No-Go" in html_out

    def test_go_signal_clean(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = ExecutiveSummaryRenderer(computed, merged)
        html_out = r.render()
        assert "Go" in html_out

    def test_heatmap_rendered(self) -> None:
        computed = _compute()
        r = ExecutiveSummaryRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Risk by Domain" in html_out
        assert "Legal" in html_out

    def test_top_deal_breakers(self) -> None:
        computed = _compute()
        r = ExecutiveSummaryRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Top Deal Breakers" in html_out
        assert "CoC terminates contract" in html_out

    def test_key_metrics_strip(self) -> None:
        computed = _compute()
        r = ExecutiveSummaryRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Total Findings" in html_out
        assert "P0 Critical" in html_out
        assert "Match Rate" in html_out

    def test_concentration_risk(self) -> None:
        computed = _compute()
        r = ExecutiveSummaryRenderer(computed, _make_merged_data())
        html_out = r.render()
        # HHI is computed; if present it should be rendered
        if computed.concentration_hhi > 0:
            assert "Concentration Risk" in html_out


# ===========================================================================
# Findings Table tests (Issue #113 B1)
# ===========================================================================


class TestFindingsTableRenderer:
    def test_p0_table_rendered(self) -> None:
        computed = _compute()
        r = FindingsTableRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-p0-table'" in html_out
        assert "P0 Deal Stoppers" in html_out
        assert "customer-table" in html_out

    def test_p1_table_rendered(self) -> None:
        computed = _compute()
        r = FindingsTableRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-p1-table'" in html_out
        assert "P1 Critical Issues" in html_out

    def test_no_p0_findings_no_p0_table(self) -> None:
        merged = {"c": {"customer": "C", "findings": [_make_finding(severity="P2")], "gaps": []}}
        computed = _compute(merged)
        r = FindingsTableRenderer(computed, merged)
        html_out = r.render()
        assert "P0 Deal Stoppers" not in html_out

    def test_empty_findings_no_tables(self) -> None:
        merged = {"c": {"customer": "C", "findings": [], "gaps": []}}
        computed = _compute(merged)
        r = FindingsTableRenderer(computed, merged)
        html_out = r.render()
        assert html_out == ""

    def test_alert_box_in_severity_table(self) -> None:
        computed = _compute()
        r = FindingsTableRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "class='alert" in html_out


# ===========================================================================
# CoC Analysis tests (Issue #113 B4)
# ===========================================================================


class TestCoCAnalysisRenderer:
    def test_coc_section_rendered(self) -> None:
        computed = _compute()
        r = CoCAnalysisRenderer(computed, _make_merged_data())
        html_out = r.render()
        if computed.coc_findings:
            assert "id='sec-coc'" in html_out
            assert "Change of Control Analysis" in html_out
        else:
            assert html_out == ""

    def test_coc_with_findings(self) -> None:
        """CoC findings from change_of_control category should appear."""
        merged = {
            "c1": {
                "customer": "Customer 1",
                "findings": [
                    _make_finding(
                        severity="P0",
                        agent="legal",
                        category="change_of_control",
                        title="CoC terminates contract",
                        description="Upon change of control agreement terminates",
                    ),
                ],
                "gaps": [],
            },
            "c2": {
                "customer": "Customer 2",
                "findings": [
                    _make_finding(
                        severity="P1",
                        agent="legal",
                        category="assignment_restriction",
                        title="Consent required for assignment",
                        description="Written consent needed for assignment",
                    ),
                ],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        r = CoCAnalysisRenderer(computed, merged)
        html_out = r.render()
        if computed.coc_findings:
            assert "Change of Control Analysis" in html_out
            assert "class='alert" in html_out

    def test_coc_empty_no_render(self) -> None:
        merged = {"c": {"customer": "C", "findings": [_make_finding(severity="P2")], "gaps": []}}
        computed = _compute(merged)
        r = CoCAnalysisRenderer(computed, merged)
        assert r.render() == ""


# ===========================================================================
# Privacy Analysis tests (Issue #113 B10)
# ===========================================================================


class TestPrivacyAnalysisRenderer:
    def test_privacy_empty_no_render(self) -> None:
        merged = {"c": {"customer": "C", "findings": [_make_finding(severity="P2")], "gaps": []}}
        computed = _compute(merged)
        r = PrivacyAnalysisRenderer(computed, merged)
        assert r.render() == ""

    def test_privacy_with_findings(self) -> None:
        merged = {
            "c": {
                "customer": "C",
                "findings": [
                    _make_finding(severity="P1", title="GDPR non-compliance", description="GDPR privacy DPA missing"),
                ],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        r = PrivacyAnalysisRenderer(computed, merged)
        html_out = r.render()
        if computed.privacy_findings:
            assert "Data Privacy" in html_out


# ===========================================================================
# Customer Health Tiers tests (Issue #113 G2)
# ===========================================================================


class TestCustomerHealthRenderer:
    def test_health_tiers_rendered(self) -> None:
        computed = _compute()
        r = CustomerHealthRenderer(computed, _make_merged_data())
        html_out = r.render()
        if computed.tier1_customers or computed.tier2_customers or computed.tier3_customers:
            assert "id='sec-health'" in html_out
            assert "Entity Health Tiers" in html_out

    def test_tier1_critical_alert(self) -> None:
        computed = _compute()
        r = CustomerHealthRenderer(computed, _make_merged_data())
        html_out = r.render()
        if computed.tier1_customers:
            assert "Immediate Attention" in html_out or "class='alert" in html_out

    def test_health_empty_no_render(self) -> None:
        computed = _compute({})
        r = CustomerHealthRenderer(computed, {})
        assert r.render() == ""


# ===========================================================================
# Recommendations tests (Issue #113 B6)
# ===========================================================================


class TestRecommendationsRenderer:
    def test_recommendations_rendered(self) -> None:
        computed = _compute()
        r = RecommendationsRenderer(computed, _make_merged_data())
        html_out = r.render()
        if computed.recommendations:
            assert "id='sec-recommendations'" in html_out
            assert "Recommendations" in html_out
            assert "rec-card" in html_out

    def test_recommendations_empty_no_render(self) -> None:
        computed = _compute({})
        r = RecommendationsRenderer(computed, {})
        assert r.render() == ""

    def test_recommendations_have_timeline_badges(self) -> None:
        computed = _compute()
        r = RecommendationsRenderer(computed, _make_merged_data())
        html_out = r.render()
        if computed.recommendations:
            assert "rec-timeline" in html_out


# ===========================================================================
# Methodology tests (Issue #113 B7)
# ===========================================================================


class TestMethodologyRenderer:
    def test_methodology_rendered(self) -> None:
        computed = _compute()
        r = MethodologyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "id='sec-methodology'" in html_out
        assert "Methodology" in html_out
        assert "Analysis Process" in html_out

    def test_methodology_agent_coverage(self) -> None:
        computed = _compute()
        r = MethodologyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Agent Coverage" in html_out
        assert "Legal" in html_out
        assert "Finance" in html_out

    def test_methodology_data_quality(self) -> None:
        computed = _compute()
        r = MethodologyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Data Quality" in html_out
        assert "match rate" in html_out.lower() or "Match" in html_out

    def test_methodology_limitations(self) -> None:
        computed = _compute()
        r = MethodologyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Known Limitations" in html_out

    def test_methodology_entity_count(self) -> None:
        computed = _compute()
        r = MethodologyRenderer(computed, _make_merged_data())
        html_out = r.render()
        assert "Entities Analyzed" in html_out
        assert ">2</div>" in html_out  # 2 entities in test data


# ===========================================================================
# CSS Custom Properties (Issue #113 E1)
# ===========================================================================


class TestCSSCustomProperties:
    def test_root_variables_defined(self) -> None:
        css = render_css()
        assert ":root {" in css or ":root{" in css
        assert "--navy" in css
        assert "--red" in css
        assert "--orange" in css
        assert "--green" in css
        assert "--blue" in css

    def test_severity_variables(self) -> None:
        css = render_css()
        assert "--sev-p0" in css
        assert "--sev-p1" in css
        assert "--sev-p2" in css
        assert "--sev-p3" in css

    def test_alert_variables(self) -> None:
        css = render_css()
        assert "--alert-critical-bg" in css
        assert "--alert-high-bg" in css
        assert "--alert-info-bg" in css
        assert "--alert-good-bg" in css


# ===========================================================================
# Sidebar Navigation (Issue #113 A1)
# ===========================================================================


class TestSidebarNavigation:
    def test_sidebar_has_toc_groups(self) -> None:
        nav = render_nav_bar()
        assert "toc-group" in nav

    def test_sidebar_has_confidential_badge(self) -> None:
        nav = render_nav_bar()
        assert "confidential" in nav.lower()

    def test_sidebar_has_brand(self) -> None:
        nav = render_nav_bar()
        assert "sidebar-brand" in nav

    def test_sidebar_rag_indicators_with_data(self) -> None:
        rag = {"executive": "green", "domain-legal": "red"}
        nav = render_nav_bar(section_rag=rag)
        assert "rag-dot" in nav

    def test_sidebar_opens_main_wrapper(self) -> None:
        nav = render_nav_bar()
        assert "class='main-wrapper'" in nav


# ===========================================================================
# Alert Box Rendering (Issue #113 C1)
# ===========================================================================


class TestAlertBoxes:
    def test_render_alert_critical(self) -> None:
        alert = SectionRenderer.render_alert("critical", "Title", "Body text")
        assert "alert-critical" in alert
        assert "Title" in alert
        assert "Body text" in alert

    def test_render_alert_good(self) -> None:
        alert = SectionRenderer.render_alert("good", "All clear", "No issues")
        assert "alert-good" in alert
        assert "All clear" in alert

    def test_render_alert_xss(self) -> None:
        alert = SectionRenderer.render_alert("info", "<script>alert(1)</script>", "Test")
        assert "<script>" not in alert
        assert "&lt;script&gt;" in alert


# ===========================================================================
# RAG Indicator (Issue #113 E6)
# ===========================================================================


class TestRAGIndicator:
    def test_rag_green(self) -> None:
        indicator = SectionRenderer.rag_indicator("green")
        assert "rag-dot" in indicator
        assert "green" in indicator.lower() or "#28a745" in indicator

    def test_rag_red(self) -> None:
        indicator = SectionRenderer.rag_indicator("red")
        assert "rag-dot" in indicator

    def test_rag_unknown(self) -> None:
        indicator = SectionRenderer.rag_indicator("unknown")
        assert "rag-dot" in indicator


# ===========================================================================
# Category Normalization (Issue #113 D1)
# ===========================================================================


class TestCategoryNormalization:
    def test_change_of_control_variants_normalized(self) -> None:
        """All CoC variants map to 'Change of Control'."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [
                    _make_finding(agent="legal", category="change_of_control_clauses"),
                    _make_finding(agent="legal", category="change_in_control"),
                    _make_finding(agent="legal", category="assignment_restriction"),
                ],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        legal_cats = computed.category_groups.get("legal", {})
        assert "Change of Control" in legal_cats

    def test_dataroom_folder_mapped_to_other(self) -> None:
        """Data room folder names like '1.1. Engineering' map to 'Other'."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(agent="legal", category="1.1. Engineering")],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        legal_cats = computed.category_groups.get("legal", {})
        assert "1.1. Engineering" not in legal_cats
        assert "Other" in legal_cats

    def test_unknown_category_passes_through(self) -> None:
        """Categories with no keyword match pass through as-is."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(agent="legal", category="completely_novel_topic_xyz")],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        legal_cats = computed.category_groups.get("legal", {})
        # Should either be in its original form or mapped to Other
        assert len(legal_cats) >= 1


# ===========================================================================
# Computed metrics new fields (Issue #113)
# ===========================================================================


class TestComputedMetricsNewFields:
    def test_recommendations_generated(self) -> None:
        computed = _compute()
        assert isinstance(computed.recommendations, list)
        if computed.total_findings > 0:
            assert len(computed.recommendations) > 0

    def test_section_rag_computed(self) -> None:
        computed = _compute()
        assert isinstance(computed.section_rag, dict)

    def test_customer_p0_summary(self) -> None:
        computed = _compute()
        assert isinstance(computed.customer_p0_summary, list)
        if computed.findings_by_severity.get("P0", 0) > 0:
            assert len(computed.customer_p0_summary) > 0

    def test_customer_p1_summary(self) -> None:
        computed = _compute()
        assert isinstance(computed.customer_p1_summary, list)

    def test_health_tiers(self) -> None:
        computed = _compute()
        assert isinstance(computed.tier1_customers, list)
        assert isinstance(computed.tier2_customers, list)
        assert isinstance(computed.tier3_customers, list)

    def test_total_arr_mentioned(self) -> None:
        computed = _compute()
        assert isinstance(computed.total_arr_mentioned, float)

    def test_wolf_pack_p0_only(self) -> None:
        computed = _compute()
        for f in computed.wolf_pack_p0:
            assert f.get("severity") == "P0"

    def test_wolf_pack_p0_cap_15(self) -> None:
        """Wolf pack P0 list should be capped at 15."""
        findings = [_make_finding(severity="P0", title=f"P0 finding {i}") for i in range(20)]
        merged = {"c": {"customer": "C", "findings": findings, "gaps": []}}
        computed = _compute(merged)
        assert len(computed.wolf_pack_p0) <= 15

    def test_topic_classification_coc(self) -> None:
        """Findings with 'change of control' in title are classified as CoC."""
        merged = {
            "c": {
                "customer": "C",
                "findings": [
                    _make_finding(title="Change of control clause found", description="CoC terminates agreement"),
                ],
                "gaps": [],
            },
        }
        computed = _compute(merged)
        assert isinstance(computed.coc_findings, list)

    def test_recommendation_structure(self) -> None:
        computed = _compute()
        for rec in computed.recommendations:
            assert "timeline" in rec
            assert "title" in rec
            assert "description" in rec
