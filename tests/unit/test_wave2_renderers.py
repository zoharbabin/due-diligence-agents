"""Unit tests for Wave 2 HTML section renderers.

Tests each new and enhanced renderer with empty and non-empty data.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData
from dd_agents.reporting.html_compliance import ComplianceRenderer
from dd_agents.reporting.html_cross_domain import CrossDomainRenderer
from dd_agents.reporting.html_discount import DiscountAnalysisRenderer
from dd_agents.reporting.html_entity import EntityDistributionRenderer
from dd_agents.reporting.html_ip_risk import IPRiskRenderer
from dd_agents.reporting.html_liability import LiabilityRenderer
from dd_agents.reporting.html_renewal import RenewalAnalysisRenderer
from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer
from dd_agents.reporting.html_timeline import TimelineRenderer
from dd_agents.reporting.html_valuation import ValuationBridgeRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data(**kwargs: Any) -> ReportComputedData:
    """Create a ReportComputedData with field overrides."""
    return ReportComputedData(**kwargs)


def _make_finding(
    severity: str = "P2",
    title: str = "Test finding",
    customer: str = "Customer A",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "_customer": customer,
        "_customer_safe_name": "customer_a",
    }


# ---------------------------------------------------------------------------
# SaaS Metrics Renderer — NRR/GRR enhancement
# ---------------------------------------------------------------------------


class TestSaaSMetricsRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = SaaSMetricsRenderer(data, {})
        assert r.render() == ""

    def test_nrr_grr_cards_rendered(self) -> None:
        data = _make_data(
            total_contracted_arr=1_000_000.0,
            saas_metrics={
                "total_customers": 10,
                "customers_with_revenue": 8,
                "avg_contract_value": 100_000.0,
                "top_customer_pct": 20.0,
                "tier_distribution": {},
                "nrr_estimate": 120.0,
                "grr_estimate": 92.0,
                "expansion_signals": 5,
                "contraction_signals": 2,
            },
        )
        r = SaaSMetricsRenderer(data, {})
        html = r.render()
        assert "sec-saas" in html
        assert "120%" in html
        assert "92%" in html
        assert "Expansion Signals" in html
        assert "Contraction Signals" in html
        assert "Benchmark Comparison" in html

    def test_nrr_green_threshold(self) -> None:
        data = _make_data(
            total_contracted_arr=500_000.0,
            saas_metrics={
                "total_customers": 5,
                "customers_with_revenue": 5,
                "avg_contract_value": 100_000.0,
                "top_customer_pct": 10.0,
                "tier_distribution": {},
                "nrr_estimate": 115.0,
                "grr_estimate": 90.0,
            },
        )
        r = SaaSMetricsRenderer(data, {})
        html = r.render()
        assert "var(--green)" in html

    def test_nrr_red_threshold(self) -> None:
        data = _make_data(
            total_contracted_arr=500_000.0,
            saas_metrics={
                "total_customers": 5,
                "customers_with_revenue": 5,
                "avg_contract_value": 100_000.0,
                "top_customer_pct": 10.0,
                "tier_distribution": {},
                "nrr_estimate": 80.0,
                "grr_estimate": 70.0,
            },
        )
        r = SaaSMetricsRenderer(data, {})
        html = r.render()
        assert "var(--red)" in html

    def test_no_nrr_section_when_none(self) -> None:
        data = _make_data(
            total_contracted_arr=500_000.0,
            saas_metrics={
                "total_customers": 5,
                "customers_with_revenue": 5,
                "avg_contract_value": 100_000.0,
                "top_customer_pct": 10.0,
                "tier_distribution": {},
            },
        )
        r = SaaSMetricsRenderer(data, {})
        html = r.render()
        assert "NRR Estimate" not in html


# ---------------------------------------------------------------------------
# Discount Renderer — avg/max + top discounted
# ---------------------------------------------------------------------------


class TestDiscountRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = DiscountAnalysisRenderer(data, {})
        assert r.render() == ""

    def test_avg_max_and_top_discounted(self) -> None:
        data = _make_data(
            discount_analysis={
                "total_pricing_findings": 3,
                "customers_with_discounts": 2,
                "avg_discount_pct": 15.5,
                "max_discount_pct": 40.0,
                "distribution": {"0-10%": 1, "10-20%": 1, "20%+": 1},
                "top_discounted": [
                    {"entity": "Customer A", "discount_pct": 40.0},
                    {"entity": "Customer B", "discount_pct": 15.0},
                ],
                "findings": [_make_finding()],
            }
        )
        r = DiscountAnalysisRenderer(data, {})
        html = r.render()
        assert "sec-discount" in html
        assert "15.5%" in html
        assert "40.0%" in html
        assert "Top Discounted Entities" in html
        assert "Customer A" in html

    def test_top_discounted_uses_display_name(self) -> None:
        data = _make_data(
            display_names={"acme_corp": "Acme Corporation"},
            discount_analysis={
                "total_pricing_findings": 1,
                "customers_with_discounts": 1,
                "distribution": {},
                "top_discounted": [
                    {"entity": "acme_corp", "discount_pct": 25.0},
                ],
                "findings": [],
            },
        )
        r = DiscountAnalysisRenderer(data, {})
        html = r.render()
        assert "Acme Corporation" in html
        assert "acme_corp" not in html

    def test_xss_escaping_top_discounted(self) -> None:
        data = _make_data(
            discount_analysis={
                "total_pricing_findings": 1,
                "customers_with_discounts": 1,
                "distribution": {},
                "top_discounted": [
                    {"entity": "<script>alert(1)</script>", "discount_pct": 10.0},
                ],
                "findings": [],
            }
        )
        r = DiscountAnalysisRenderer(data, {})
        html = r.render()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Renewal Renderer — evergreen + expiry distribution
# ---------------------------------------------------------------------------


class TestRenewalRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = RenewalAnalysisRenderer(data, {})
        assert r.render() == ""

    def test_evergreen_and_expiry_distribution(self) -> None:
        data = _make_data(
            renewal_analysis={
                "total_renewal_findings": 5,
                "auto_renew_count": 2,
                "manual_renew_count": 1,
                "escalation_cap_count": 1,
                "evergreen_count": 3,
                "expiry_distribution": {"Q1 2026": 2, "Q2 2026": 3},
                "findings": [_make_finding()],
            }
        )
        r = RenewalAnalysisRenderer(data, {})
        html = r.render()
        assert "sec-renewal" in html
        assert "Evergreen" in html
        assert "Expiry Distribution" in html
        assert "Q1 2026" in html


# ---------------------------------------------------------------------------
# Compliance Renderer — DPA coverage + jurisdictions
# ---------------------------------------------------------------------------


class TestComplianceRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = ComplianceRenderer(data, {})
        assert r.render() == ""

    def test_dpa_coverage_and_jurisdictions(self) -> None:
        data = _make_data(
            compliance_analysis={
                "total_compliance_findings": 4,
                "dpa_findings_count": 2,
                "jurisdiction_findings_count": 1,
                "regulatory_findings_count": 1,
                "dpa_coverage_pct": 75.0,
                "top_jurisdictions": [
                    {"jurisdiction": "GDPR (EU)", "count": 3},
                    {"jurisdiction": "CCPA (CA)", "count": 1},
                ],
                "findings": [_make_finding()],
            }
        )
        r = ComplianceRenderer(data, {})
        html = r.render()
        assert "sec-compliance" in html
        assert "75%" in html
        assert "Top Jurisdictions" in html
        assert "GDPR (EU)" in html


# ---------------------------------------------------------------------------
# Entity Distribution Renderer — migration risk + entity names
# ---------------------------------------------------------------------------


class TestEntityRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = EntityDistributionRenderer(data, {})
        assert r.render() == ""

    def test_migration_risk_and_names(self) -> None:
        data = _make_data(
            entity_distribution={
                "entity_findings_count": 3,
                "total_entities_mentioned": 5,
                "migration_risk_score": "critical",
                "entity_names": ["Entity Alpha", "Entity Beta"],
                "findings": [_make_finding()],
            }
        )
        r = EntityDistributionRenderer(data, {})
        html = r.render()
        assert "sec-entity" in html
        assert "Critical" in html
        assert "Migration Risk" in html
        assert "Entity Alpha" in html
        assert "var(--red)" in html  # critical = red

    def test_migration_risk_low_hides_badge(self) -> None:
        data = _make_data(
            entity_distribution={
                "entity_findings_count": 1,
                "total_entities_mentioned": 1,
                "migration_risk_score": "low",
                "findings": [],
            }
        )
        r = EntityDistributionRenderer(data, {})
        html = r.render()
        assert "Migration Risk</div>" not in html  # low risk hides the metric card badge


# ---------------------------------------------------------------------------
# Timeline Renderer — cliff risk + expiry dates
# ---------------------------------------------------------------------------


class TestTimelineRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = TimelineRenderer(data, {})
        assert r.render() == ""

    def test_cliff_risk_and_dates(self) -> None:
        data = _make_data(
            contract_timeline={
                "expiry_findings_count": 8,
                "date_mentions_count": 20,
                "earliest_expiry": "2026-06-01",
                "latest_expiry": "2029-12-31",
                "cliff_risk": True,
                "findings": [_make_finding()],
            }
        )
        r = TimelineRenderer(data, {})
        html = r.render()
        assert "sec-timeline" in html
        assert "Cliff risk detected" in html
        assert "2026-06-01" in html
        assert "2029-12-31" in html

    def test_no_cliff_alert_when_zero(self) -> None:
        data = _make_data(
            contract_timeline={
                "expiry_findings_count": 3,
                "date_mentions_count": 5,
                "cliff_risk": False,
                "findings": [],
            }
        )
        r = TimelineRenderer(data, {})
        html = r.render()
        assert "Cliff risk" not in html


# ---------------------------------------------------------------------------
# Liability Renderer (NEW)
# ---------------------------------------------------------------------------


class TestLiabilityRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = LiabilityRenderer(data, {})
        assert r.render() == ""

    def test_non_empty_renders_section(self) -> None:
        data = _make_data()
        # Set via object attribute since field may not exist on model yet
        object.__setattr__(
            data,
            "liability_analysis",
            {
                "total_liability_findings": 5,
                "insurance_count": 2,
                "liability_cap_count": 3,
                "uncapped_count": 1,
                "indemnification_count": 2,
                "findings": [_make_finding(severity="P0", title="Uncapped liability")],
            },
        )
        r = LiabilityRenderer(data, {})
        html = r.render()
        assert "sec-liability" in html
        assert "Insurance &amp; Liability Analysis" in html
        assert "Uncapped liability detected" in html
        assert "alert-critical" in html

    def test_no_uncapped_alert_when_zero(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "liability_analysis",
            {
                "total_liability_findings": 2,
                "insurance_count": 0,
                "liability_cap_count": 2,
                "uncapped_count": 0,
                "indemnification_count": 1,
                "findings": [_make_finding()],
            },
        )
        r = LiabilityRenderer(data, {})
        html = r.render()
        assert "Uncapped liability" not in html

    def test_xss_escaping(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "liability_analysis",
            {
                "total_liability_findings": 1,
                "insurance_count": 0,
                "liability_cap_count": 0,
                "uncapped_count": 0,
                "indemnification_count": 0,
                "findings": [_make_finding(title="<img onerror=alert(1)>")],
            },
        )
        r = LiabilityRenderer(data, {})
        html = r.render()
        assert "<img" not in html
        assert "&lt;img" in html


# ---------------------------------------------------------------------------
# IP Risk Renderer (NEW)
# ---------------------------------------------------------------------------


class TestIPRiskRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = IPRiskRenderer(data, {})
        assert r.render() == ""

    def test_non_empty_renders_section(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "ip_risk_analysis",
            {
                "total_ip_findings": 4,
                "ip_ownership_gaps": 2,
                "open_source_count": 3,
                "license_risk_count": 1,
                "findings": [_make_finding(severity="P1", title="IP ownership unclear")],
            },
        )
        r = IPRiskRenderer(data, {})
        html = r.render()
        assert "sec-ip-risk" in html
        assert "IP &amp; Technology License Risk" in html
        assert "2 IP ownership gaps" in html
        assert "Open source usage" in html

    def test_no_ownership_alert_when_zero(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "ip_risk_analysis",
            {
                "total_ip_findings": 1,
                "ip_ownership_gaps": 0,
                "open_source_count": 0,
                "license_risk_count": 1,
                "findings": [],
            },
        )
        r = IPRiskRenderer(data, {})
        html = r.render()
        assert "ownership gaps" not in html


# ---------------------------------------------------------------------------
# Cross-Domain Renderer (NEW)
# ---------------------------------------------------------------------------


class TestCrossDomainRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = CrossDomainRenderer(data, {})
        assert r.render() == ""

    def test_non_empty_renders_section(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "cross_domain_risks",
            [
                {
                    "entity": "Customer A",
                    "domain_count": 3,
                    "finding_count": 7,
                    "risk_score": 8.5,
                    "has_p0": True,
                },
                {
                    "entity": "Customer B",
                    "domain_count": 2,
                    "finding_count": 3,
                    "risk_score": 4.0,
                    "has_p0": False,
                },
            ],
        )
        r = CrossDomainRenderer(data, {})
        html = r.render()
        assert "sec-cross-domain" in html
        assert "Cross-Domain Risk Correlation" in html
        assert "Customer A" in html
        assert "8.5" in html
        assert "alert-critical" in html  # P0 alert for Customer A

    def test_xss_escaping_entity(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "cross_domain_risks",
            [
                {
                    "entity": "<b>Evil</b>",
                    "domain_count": 1,
                    "finding_count": 1,
                    "risk_score": 1.0,
                    "has_p0": False,
                },
            ],
        )
        r = CrossDomainRenderer(data, {})
        html = r.render()
        assert "<b>" not in html
        assert "&lt;b&gt;" in html


# ---------------------------------------------------------------------------
# Valuation Bridge Renderer (NEW)
# ---------------------------------------------------------------------------


class TestValuationBridgeRenderer:
    def test_empty_returns_empty(self) -> None:
        data = _make_data()
        r = ValuationBridgeRenderer(data, {})
        assert r.render() == ""

    def test_non_empty_renders_section(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "valuation_bridge",
            {
                "total_arr": 10_000_000.0,
                "risk_adjusted_arr": 8_500_000.0,
                "total_exposure": 1_500_000.0,
                "risk_categories": [
                    {"category": "Change of Control", "exposure": 800_000.0},
                    {"category": "Termination Risk", "exposure": 700_000.0},
                ],
            },
        )
        r = ValuationBridgeRenderer(data, {})
        html = r.render()
        assert "sec-valuation" in html
        assert "Valuation Impact Bridge" in html
        assert "5x" in html
        assert "8x" in html
        assert "12x" in html
        assert "Risk Category Breakdown" in html
        assert "Change of Control" in html

    def test_critical_alert_high_exposure(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "valuation_bridge",
            {
                "total_arr": 1_000_000.0,
                "risk_adjusted_arr": 700_000.0,
                "total_exposure": 300_000.0,  # 30% > 20%
            },
        )
        r = ValuationBridgeRenderer(data, {})
        html = r.render()
        assert "alert-critical" in html

    def test_high_alert_moderate_exposure(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "valuation_bridge",
            {
                "total_arr": 1_000_000.0,
                "risk_adjusted_arr": 900_000.0,
                "total_exposure": 100_000.0,  # 10% > 5% but <= 20%
            },
        )
        r = ValuationBridgeRenderer(data, {})
        html = r.render()
        assert "alert-high" in html
        assert "alert-critical" not in html

    def test_no_alert_low_exposure(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "valuation_bridge",
            {
                "total_arr": 1_000_000.0,
                "risk_adjusted_arr": 980_000.0,
                "total_exposure": 20_000.0,  # 2% <= 5%
            },
        )
        r = ValuationBridgeRenderer(data, {})
        html = r.render()
        assert "alert-critical" not in html
        assert "alert-high" not in html

    def test_zero_arr_returns_empty(self) -> None:
        data = _make_data()
        object.__setattr__(
            data,
            "valuation_bridge",
            {
                "total_arr": 0.0,
                "risk_adjusted_arr": 0.0,
                "total_exposure": 0.0,
            },
        )
        r = ValuationBridgeRenderer(data, {})
        assert r.render() == ""
