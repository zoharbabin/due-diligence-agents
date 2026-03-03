"""Unit tests for the report data computation engine.

Covers:
- ReportComputedData model construction and serialization
- ReportDataComputer.compute() with various inputs
- Risk score calculation (deterministic weighted formula)
- HHI concentration index computation
- Revenue-at-risk aggregation
- Severity/domain/category breakdowns
- Graceful handling of empty/missing data
- Gap aggregation by priority and type
- Cross-reference match rate calculation
- Governance metrics aggregation
"""

from __future__ import annotations

import pytest

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer

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


def _make_gap(
    priority: str = "P1",
    gap_type: str = "Missing_Doc",
) -> dict[str, str]:
    return {"priority": priority, "gap_type": gap_type, "missing_item": "MSA", "risk_if_missing": "Risk"}


def _make_merged_data(
    customers: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    if customers is not None:
        return customers  # type: ignore[return-value]
    return {
        "customer_a": {
            "customer": "Customer A",
            "findings": [
                _make_finding(severity="P0", agent="legal", category="change_of_control"),
                _make_finding(severity="P1", agent="finance", category="revenue_recognition"),
                _make_finding(severity="P2", agent="commercial", category="customer_concentration"),
                _make_finding(severity="P3", agent="producttech", category="technical_debt"),
            ],
            "gaps": [_make_gap(priority="P0"), _make_gap(priority="P2", gap_type="Stale_Doc")],
            "governance_resolution_pct": 85.0,
            "cross_references": [
                {"data_point": "ARR", "match_status": "match"},
                {"data_point": "Headcount", "match_status": "mismatch"},
            ],
        },
        "customer_b": {
            "customer": "Customer B",
            "findings": [
                _make_finding(severity="P1", agent="legal", category="ip_ownership"),
            ],
            "gaps": [],
            "governance_resolution_pct": 95.0,
            "cross_references": [
                {"data_point": "ARR", "match_status": "match"},
            ],
        },
    }


# ===========================================================================
# Tests
# ===========================================================================


class TestReportComputedData:
    """Tests for the ReportComputedData Pydantic model."""

    def test_model_construction_defaults(self) -> None:
        data = ReportComputedData()
        assert data.total_findings == 0
        assert data.total_gaps == 0
        assert data.total_customers == 0
        assert data.deal_risk_score == 0.0
        assert data.concentration_hhi == 0.0

    def test_model_serialization_roundtrip(self) -> None:
        data = ReportComputedData(total_findings=10, total_customers=5)
        json_str = data.model_dump_json()
        restored = ReportComputedData.model_validate_json(json_str)
        assert restored.total_findings == 10
        assert restored.total_customers == 5


class TestReportDataComputer:
    """Tests for ReportDataComputer.compute()."""

    def test_empty_data(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute({})
        assert result.total_findings == 0
        assert result.total_gaps == 0
        assert result.total_customers == 0
        assert result.deal_risk_label == "Clean"

    def test_total_counts(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.total_findings == 5
        assert result.total_gaps == 2
        assert result.total_customers == 2

    def test_severity_breakdown(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.findings_by_severity["P0"] == 1
        assert result.findings_by_severity["P1"] == 2
        assert result.findings_by_severity["P2"] == 1
        assert result.findings_by_severity["P3"] == 1

    def test_domain_breakdown(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.findings_by_domain["legal"] == 2
        assert result.findings_by_domain["finance"] == 1
        assert result.findings_by_domain["commercial"] == 1
        assert result.findings_by_domain["producttech"] == 1

    def test_deal_risk_critical_when_p0(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.deal_risk_label == "Critical"

    def test_deal_risk_clean_when_no_findings(self) -> None:
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": []}}
        result = computer.compute(data)
        assert result.deal_risk_label == "Clean"

    def test_deal_risk_high_when_multiple_p1(self) -> None:
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [
                    _make_finding(severity="P1"),
                    _make_finding(severity="P1"),
                    _make_finding(severity="P1"),
                ],
                "gaps": [],
            }
        }
        result = computer.compute(data)
        assert result.deal_risk_label == "High"

    def test_domain_risk_scores(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        # Legal has P0 + P1 -> high score
        assert result.domain_risk_scores["legal"] > result.domain_risk_scores["producttech"]

    def test_customer_risk_scores(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        # Customer A has P0 -> higher risk than Customer B with only P1
        assert result.customer_risk_scores["customer_a"] > result.customer_risk_scores["customer_b"]

    def test_gap_breakdown_by_priority(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.gaps_by_priority["P0"] == 1
        assert result.gaps_by_priority["P2"] == 1

    def test_gap_breakdown_by_type(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.gaps_by_type["Missing_Doc"] == 1
        assert result.gaps_by_type["Stale_Doc"] == 1

    def test_cross_reference_stats(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.total_cross_refs == 3
        assert result.cross_ref_matches == 2
        assert result.cross_ref_mismatches == 1
        assert result.match_rate == pytest.approx(2.0 / 3.0, rel=1e-3)

    def test_governance_metrics(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.avg_governance_pct == pytest.approx(90.0, rel=1e-3)
        assert result.governance_scores["customer_a"] == 85.0
        assert result.governance_scores["customer_b"] == 95.0

    def test_wolf_pack_only_p0_p1(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert len(result.wolf_pack) == 3  # 1 P0 + 2 P1
        for f in result.wolf_pack:
            assert f["severity"] in ("P0", "P1")

    def test_category_domain_matrix(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert "change_of_control" in result.category_domain_matrix
        assert result.category_domain_matrix["change_of_control"]["legal"] == 1

    def test_severity_domain_matrix(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.severity_domain_matrix["P0"]["legal"] == 1
        assert result.severity_domain_matrix["P1"]["legal"] == 1
        assert result.severity_domain_matrix["P1"]["finance"] == 1

    def test_non_dict_data_skipped(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute({"bad": "not a dict"})
        assert result.total_customers == 1
        assert result.total_findings == 0

    def test_missing_fields_handled(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute({"c": {}})
        assert result.total_findings == 0
        assert result.total_gaps == 0

    def test_concentration_hhi_single_customer(self) -> None:
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [_make_finding(severity="P1")],
                "gaps": [],
            }
        }
        result = computer.compute(data)
        # Single customer -> HHI = 10000 (100%^2 * 100)
        assert result.concentration_hhi == pytest.approx(10000.0)

    def test_concentration_hhi_even_distribution(self) -> None:
        computer = ReportDataComputer()
        data = {
            f"c{i}": {
                "customer": f"Customer {i}",
                "findings": [_make_finding()],
                "gaps": [],
            }
            for i in range(4)
        }
        result = computer.compute(data)
        # 4 equal customers: HHI = 4 * (25^2) = 2500
        assert result.concentration_hhi == pytest.approx(2500.0)

    def test_top_customers_by_risk_sorted(self) -> None:
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert len(result.top_customers_by_risk) >= 1
        # First customer should have highest risk
        first = result.top_customers_by_risk[0]
        assert first == "customer_a"  # Has P0 finding
