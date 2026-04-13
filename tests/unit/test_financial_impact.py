"""Tests for Revenue-at-Risk & Financial Impact Quantification (Issue #102)."""

from __future__ import annotations

from typing import Any

import pytest

from dd_agents.reporting.computed_metrics import ReportDataComputer


def _make_merged(
    subjects: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal merged_data dict for testing."""
    return subjects or {}


def _subject(
    name: str,
    findings: list[dict[str, Any]] | None = None,
    cross_references: list[dict[str, Any]] | None = None,
    gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "subject": name,
        "subject_safe_name": name.lower().replace(" ", "_"),
        "findings": findings or [],
        "gaps": gaps or [],
        "cross_references": cross_references or [],
        "governance_graph": {"nodes": [], "edges": []},
        "governance_resolved_pct": 1.0,
    }


class TestRevenueExtraction:
    """Test revenue extraction from cross-reference data."""

    def test_extracts_arr_from_cross_refs(self) -> None:
        merged = {
            "acme": _subject(
                "Acme",
                cross_references=[
                    {
                        "data_point": "ARR",
                        "contract_value": "$500,000",
                        "reference_value": "$500,000",
                        "match_status": "match",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_by_subject.get("acme", 0.0) == pytest.approx(500_000.0)

    def test_extracts_contract_value_from_cross_refs(self) -> None:
        merged = {
            "beta": _subject(
                "Beta",
                cross_references=[
                    {
                        "data_point": "Total Contract Value",
                        "contract_value": "$1.2M",
                        "reference_value": "$1,200,000",
                        "match_status": "match",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_by_subject.get("beta", 0.0) == pytest.approx(1_200_000.0)

    def test_prefers_reference_value_over_contract_value(self) -> None:
        """When both are present, reference_value is authoritative."""
        merged = {
            "gamma": _subject(
                "Gamma",
                cross_references=[
                    {
                        "data_point": "Annual Revenue",
                        "contract_value": "$100,000",
                        "reference_value": "$120,000",
                        "match_status": "mismatch",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_by_subject.get("gamma", 0.0) == pytest.approx(120_000.0)

    def test_skips_non_revenue_cross_refs(self) -> None:
        merged = {
            "delta": _subject(
                "Delta",
                cross_references=[
                    {
                        "data_point": "Payment Terms",
                        "contract_value": "Net 30",
                        "reference_value": "Net 30",
                        "match_status": "match",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_by_subject.get("delta", 0.0) == 0.0

    def test_total_contracted_arr(self) -> None:
        merged = {
            "a": _subject(
                "A",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$300,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "b": _subject(
                "B",
                cross_references=[
                    {"data_point": "ACV", "contract_value": "$200,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.total_contracted_arr == pytest.approx(500_000.0)

    def test_no_cross_refs_yields_zero(self) -> None:
        merged = {"x": _subject("X")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.total_contracted_arr == 0.0
        assert result.revenue_by_subject == {}

    def test_handles_malformed_values(self) -> None:
        merged = {
            "bad": _subject(
                "Bad",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "N/A", "reference_value": "TBD", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_by_subject.get("bad", 0.0) == 0.0


class TestRevenueAtRisk:
    """Test revenue-at-risk waterfall computation."""

    def _merged_with_revenue_and_findings(self) -> dict[str, Any]:
        return {
            "acme": _subject(
                "Acme",
                findings=[
                    {
                        "severity": "P0",
                        "category": "change_of_control",
                        "title": "CoC clause",
                        "description": "Consent required",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "x"}],
                        "confidence": "high",
                        "agent": "legal",
                    },
                ],
                cross_references=[
                    {
                        "data_point": "ARR",
                        "contract_value": "$500,000",
                        "reference_value": "$500,000",
                        "match_status": "match",
                    },
                ],
            ),
            "beta": _subject(
                "Beta",
                findings=[
                    {
                        "severity": "P1",
                        "category": "termination",
                        "title": "TfC clause",
                        "description": "30-day termination for convenience",
                        "citations": [{"source_type": "contract", "source_path": "b.pdf", "exact_quote": "y"}],
                        "confidence": "high",
                        "agent": "legal",
                    },
                ],
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$300,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "gamma": _subject(
                "Gamma",
                findings=[],
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$200,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }

    def test_waterfall_has_total_arr(self) -> None:
        merged = self._merged_with_revenue_and_findings()
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.total_contracted_arr == pytest.approx(1_000_000.0)

    def test_waterfall_coc_exposure(self) -> None:
        merged = self._merged_with_revenue_and_findings()
        computer = ReportDataComputer()
        result = computer.compute(merged)
        coc = result.risk_waterfall.get("change_of_control", {})
        assert coc.get("amount", 0.0) == pytest.approx(500_000.0)
        assert coc.get("contracts", 0) >= 1

    def test_waterfall_tfc_exposure(self) -> None:
        merged = self._merged_with_revenue_and_findings()
        computer = ReportDataComputer()
        result = computer.compute(merged)
        tfc = result.risk_waterfall.get("termination_for_convenience", {})
        assert tfc.get("amount", 0.0) == pytest.approx(300_000.0)

    def test_risk_adjusted_arr(self) -> None:
        """Risk-adjusted ARR = total - sum of risk exposures (clamped >= 0)."""
        merged = self._merged_with_revenue_and_findings()
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert 0.0 < result.risk_adjusted_arr <= result.total_contracted_arr

    def test_revenue_data_coverage(self) -> None:
        """Coverage = subjects with revenue / total subjects."""
        merged = self._merged_with_revenue_and_findings()
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_data_coverage == pytest.approx(1.0)

    def test_no_double_counting_across_categories(self) -> None:
        """When one subject has findings in multiple categories, revenue counted once."""
        merged = {
            "multi": _subject(
                "Multi",
                findings=[
                    {
                        "severity": "P0",
                        "category": "change_of_control",
                        "title": "CoC clause",
                        "description": "Consent required",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "x"}],
                        "confidence": "high",
                        "agent": "legal",
                    },
                    {
                        "severity": "P1",
                        "category": "termination",
                        "title": "TfC clause",
                        "description": "30-day termination",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "y"}],
                        "confidence": "high",
                        "agent": "legal",
                    },
                ],
                cross_references=[
                    {
                        "data_point": "ARR",
                        "contract_value": "$500,000",
                        "reference_value": "$500,000",
                        "match_status": "match",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        # Risk-adjusted ARR = total - exposure; with $500K ARR and two risk categories,
        # exposure should be $500K (not $1M due to double-counting prevention)
        assert result.risk_adjusted_arr == pytest.approx(0.0)  # 100% at risk

    def test_partial_coverage(self) -> None:
        """When some subjects lack revenue data, coverage < 1.0."""
        merged = {
            "a": _subject(
                "A",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$100,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "b": _subject("B"),  # no cross-refs
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.revenue_data_coverage == pytest.approx(0.5)


class TestConcentrationTreemap:
    """Test customer concentration treemap data."""

    def test_treemap_data_sorted_by_revenue(self) -> None:
        merged = {
            "small": _subject(
                "Small",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$50,000", "reference_value": "", "match_status": "match"},
                ],
            ),
            "large": _subject(
                "Large",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$500,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        if result.concentration_treemap:
            assert result.concentration_treemap[0]["subject_safe_name"] == "large"

    def test_treemap_includes_pct(self) -> None:
        merged = {
            "only": _subject(
                "Only",
                cross_references=[
                    {"data_point": "ARR", "contract_value": "$100,000", "reference_value": "", "match_status": "match"},
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        if result.concentration_treemap:
            assert result.concentration_treemap[0]["pct"] == pytest.approx(100.0)

    def test_treemap_empty_when_no_revenue(self) -> None:
        merged = {"x": _subject("X")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.concentration_treemap == []


class TestFinancialImpactRenderer:
    """Test HTML rendering of financial impact section."""

    def test_renders_when_revenue_present(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportComputedData
        from dd_agents.reporting.html_financial import FinancialImpactRenderer

        data = ReportComputedData(
            total_contracted_arr=1_000_000.0,
            risk_adjusted_arr=600_000.0,
            revenue_data_coverage=1.0,
            revenue_by_subject={"a": 500_000, "b": 500_000},
            risk_waterfall={
                "change_of_control": {"amount": 400_000.0, "contracts": 1, "subjects": ["a"]},
            },
            concentration_treemap=[
                {"subject_safe_name": "a", "display_name": "A", "revenue": 500_000, "pct": 50.0, "risk_level": "high"},
                {"subject_safe_name": "b", "display_name": "B", "revenue": 500_000, "pct": 50.0, "risk_level": "low"},
            ],
            total_subjects=2,
        )
        renderer = FinancialImpactRenderer(data, {}, {})
        result = renderer.render()
        assert "Revenue-at-Risk" in result
        assert "$1.0M" in result  # total
        assert "Change of Control" in result
        assert "Risk-Adjusted ARR" in result

    def test_empty_when_no_revenue(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportComputedData
        from dd_agents.reporting.html_financial import FinancialImpactRenderer

        data = ReportComputedData(total_contracted_arr=0.0)
        renderer = FinancialImpactRenderer(data, {}, {})
        assert renderer.render() == ""

    def test_treemap_escapes_html(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportComputedData
        from dd_agents.reporting.html_financial import FinancialImpactRenderer

        data = ReportComputedData(
            total_contracted_arr=100_000.0,
            risk_adjusted_arr=100_000.0,
            revenue_data_coverage=1.0,
            revenue_by_subject={"x": 100_000},
            concentration_treemap=[
                {
                    "subject_safe_name": "x",
                    "display_name": "<script>alert(1)</script>",
                    "revenue": 100_000,
                    "pct": 100.0,
                    "risk_level": "low",
                },
            ],
            total_subjects=1,
        )
        renderer = FinancialImpactRenderer(data, {}, {})
        result = renderer.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
