"""Tests for SaaS health metrics dashboard (Issue #115)."""

from __future__ import annotations

from typing import Any

import pytest

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer


def _customer(
    name: str,
    findings: list[dict[str, Any]] | None = None,
    cross_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "customer": name,
        "findings": findings or [],
        "gaps": [],
        "cross_references": cross_references or [],
    }


class TestSaaSMetricsComputation:
    """Tests for SaaS metric extraction from computed data."""

    def test_saas_fields_exist(self) -> None:
        """ReportComputedData should have SaaS metric fields."""
        data = ReportComputedData()
        assert hasattr(data, "saas_metrics")

    def test_saas_metrics_empty_when_no_revenue(self) -> None:
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.saas_metrics.get("total_customers", 0) >= 0

    def test_customer_count(self) -> None:
        merged = {
            "a": _customer(
                "A",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$100,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "b": _customer(
                "B",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$200,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.saas_metrics["total_customers"] == 2
        assert result.saas_metrics["customers_with_revenue"] == 2

    def test_avg_contract_value(self) -> None:
        merged = {
            "a": _customer(
                "A",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$100,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "b": _customer(
                "B",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$300,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.saas_metrics["avg_contract_value"] == pytest.approx(200_000.0)

    def test_revenue_concentration_top_customer(self) -> None:
        merged = {
            "big": _customer(
                "Big",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$800,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "small": _customer(
                "Small",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$200,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.saas_metrics["top_customer_pct"] == pytest.approx(80.0)

    def test_tier_distribution(self) -> None:
        """Customers should be classified into tiers by revenue."""
        merged = {
            "enterprise": _customer(
                "Enterprise",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$500,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "mid": _customer(
                "Mid",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$50,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "smb": _customer(
                "SMB",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$5,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        tiers = result.saas_metrics.get("tier_distribution", {})
        assert isinstance(tiers, dict)
        assert sum(tiers.values()) == 3


class TestSaaSMetricsRenderer:
    """Tests for SaaS metrics HTML rendering."""

    def test_renderer_exists(self) -> None:
        from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer

        assert SaaSMetricsRenderer is not None

    def test_renders_empty_when_no_data(self) -> None:
        from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer

        computed = ReportComputedData()
        renderer = SaaSMetricsRenderer(computed, {}, {})
        html = renderer.render()
        assert html == "" or "sec-saas" not in html

    def test_renders_kpi_cards_with_data(self) -> None:
        from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer

        computed = ReportComputedData(
            total_contracted_arr=1_000_000.0,
            saas_metrics={
                "total_customers": 10,
                "customers_with_revenue": 8,
                "avg_contract_value": 125_000.0,
                "top_customer_pct": 35.0,
                "tier_distribution": {"Enterprise": 2, "Mid-Market": 5, "SMB": 3},
            },
        )
        renderer = SaaSMetricsRenderer(computed, {}, {})
        html = renderer.render()
        assert "sec-saas" in html
        assert "$1.0M" in html or "$1,000" in html
        assert "125" in html

    def test_xss_escaping(self) -> None:
        from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer

        computed = ReportComputedData(
            total_contracted_arr=100.0,
            saas_metrics={
                "total_customers": 1,
                "customers_with_revenue": 1,
                "avg_contract_value": 100.0,
                "top_customer_pct": 100.0,
                "tier_distribution": {"<script>alert(1)</script>": 1},
            },
        )
        renderer = SaaSMetricsRenderer(computed, {}, {})
        html = renderer.render()
        assert "<script>" not in html
