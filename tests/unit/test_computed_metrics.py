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

from dd_agents.reporting.computed_metrics import (
    ReportComputedData,
    ReportDataComputer,
)

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

    def test_deal_risk_high_when_single_p0(self) -> None:
        """Single P0 → High (softened from Critical, Issue #113)."""
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data())
        assert result.deal_risk_label == "High"

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
        assert "Change of Control" in result.category_domain_matrix
        assert result.category_domain_matrix["Change of Control"]["legal"] == 1

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

    def test_hhi_zero_findings_no_division_by_zero(self) -> None:
        """HHI with zero total findings should return 0.0, not raise."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": []}}
        result = computer.compute(data)
        assert result.concentration_hhi == pytest.approx(0.0)

    def test_governance_negative_value_stored(self) -> None:
        """Negative governance scores are stored (validation is upstream)."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": [], "governance_resolution_pct": -5.0}}
        result = computer.compute(data)
        assert result.governance_scores.get("c") == -5.0

    def test_governance_over_100_stored(self) -> None:
        """Governance >100 is stored (clamping happens in renderer, not computer)."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": [], "governance_resolution_pct": 150.0}}
        result = computer.compute(data)
        assert result.governance_scores.get("c") == 150.0

    def test_governance_string_value_handled(self) -> None:
        """String governance values are coerced to float or skipped."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": [], "governance_resolution_pct": "85.5"}}
        result = computer.compute(data)
        assert result.governance_scores.get("c") == pytest.approx(85.5)

    def test_governance_invalid_string_skipped(self) -> None:
        """Non-numeric governance values are skipped."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": [], "governance_resolution_pct": "N/A"}}
        result = computer.compute(data)
        assert "c" not in result.governance_scores

    def test_deal_risk_medium_for_single_p1(self) -> None:
        """Single P1 finding should be Medium (below High threshold of 3 P1s)."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [_make_finding(severity="P1")], "gaps": []}}
        result = computer.compute(data)
        assert result.deal_risk_label == "Medium"

    def test_xref_zero_total_returns_zero_rate(self) -> None:
        """Match rate should be 0.0 when there are no cross-references."""
        computer = ReportDataComputer()
        data = {"c": {"customer": "C", "findings": [], "gaps": []}}
        result = computer.compute(data)
        assert result.match_rate == pytest.approx(0.0)
        assert result.total_cross_refs == 0

    def test_xref_status_case_insensitive(self) -> None:
        """Cross-reference match_status should be case-insensitive."""
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [
                    {"data_point": "ARR", "match_status": "MATCH"},
                    {"data_point": "HC", "match_status": "Mismatch"},
                ],
            }
        }
        result = computer.compute(data)
        assert result.cross_ref_matches == 1
        assert result.cross_ref_mismatches == 1

    def test_xref_status_synonyms(self) -> None:
        """Cross-reference supports 'yes'/'no' as synonyms for match/mismatch."""
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [
                    {"data_point": "ARR", "match_status": "yes"},
                    {"data_point": "HC", "match_status": "no"},
                    {"data_point": "Rev", "match_status": "true"},
                    {"data_point": "Exp", "match_status": "false"},
                ],
            }
        }
        result = computer.compute(data)
        assert result.total_cross_refs == 4
        assert result.cross_ref_matches == 2
        assert result.cross_ref_mismatches == 2

    def test_xref_fallback_to_match_key(self) -> None:
        """When match_status is missing, falls back to 'match' key."""
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [
                    {"data_point": "ARR", "match": "true"},
                    {"data_point": "HC", "match": "false"},
                ],
            }
        }
        result = computer.compute(data)
        assert result.cross_ref_matches == 1
        assert result.cross_ref_mismatches == 1

    def test_xref_unrecognized_status_neither_match_nor_mismatch(self) -> None:
        """Unrecognized status like 'partial' counts in total but not match/mismatch."""
        computer = ReportDataComputer()
        data = {
            "c": {
                "customer": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [{"data_point": "ARR", "match_status": "partial"}],
            }
        }
        result = computer.compute(data)
        assert result.total_cross_refs == 1
        assert result.cross_ref_matches == 0
        assert result.cross_ref_mismatches == 0


class TestRiskScoreLogarithmic:
    """Tests for logarithmic risk score formula."""

    def test_risk_score_zero_when_no_findings(self) -> None:
        result = ReportDataComputer._compute_risk_score({"P0": 0, "P1": 0, "P2": 0, "P3": 0})
        assert result == 0.0

    def test_risk_score_single_p0(self) -> None:
        """Single P0 should produce a score between 15 and 20."""
        result = ReportDataComputer._compute_risk_score({"P0": 1, "P1": 0, "P2": 0, "P3": 0})
        assert 15 <= result <= 20

    def test_risk_score_does_not_saturate(self) -> None:
        """Real deal scenario (0 P0, ~70 P1, 282 P2, 287 P3) should NOT hit 100."""
        result = ReportDataComputer._compute_risk_score({"P0": 0, "P1": 70, "P2": 282, "P3": 287})
        assert result < 70, f"Expected < 70 for real deal without P0s, got {result}"

    def test_risk_score_clean_deal_low(self) -> None:
        """P2+P3 only deal should score < 20."""
        result = ReportDataComputer._compute_risk_score({"P0": 0, "P1": 0, "P2": 5, "P3": 10})
        assert result < 20

    def test_risk_score_p0_dominates(self) -> None:
        """3 P0 findings should score higher than 3 P1 findings."""
        score_p0 = ReportDataComputer._compute_risk_score({"P0": 3, "P1": 0, "P2": 0, "P3": 0})
        score_p1 = ReportDataComputer._compute_risk_score({"P0": 0, "P1": 3, "P2": 0, "P3": 0})
        assert score_p0 > score_p1

    def test_risk_score_capped_at_100(self) -> None:
        """Extreme scenario should not exceed 100."""
        result = ReportDataComputer._compute_risk_score({"P0": 1000, "P1": 1000, "P2": 1000, "P3": 1000})
        assert result <= 100.0

    def test_risk_score_moderate_deal(self) -> None:
        """5 P1, 20 P2, 50 P3 should score between 15 and 40."""
        result = ReportDataComputer._compute_risk_score({"P0": 0, "P1": 5, "P2": 20, "P3": 50})
        assert 15 <= result <= 40

    def test_risk_score_is_rounded(self) -> None:
        """Score should be rounded to 1 decimal place."""
        result = ReportDataComputer._compute_risk_score({"P0": 1, "P1": 2, "P2": 3, "P3": 4})
        # Check it has at most 1 decimal place
        assert result == round(result, 1)


class TestSeverityRecalibration:
    """Tests for post-hoc severity recalibration."""

    def test_customer_severity_table_excludes_recalibrated_p0(self) -> None:
        """_build_customer_severity_tables should not list recalibrated-away P0 titles."""
        merged: dict[str, object] = {
            "customer_contracts": {
                "customer": "Customer Contracts",
                "findings": [
                    _make_finding(
                        severity="P0",
                        title="Competitor-only Change of Control clause",
                        category="change_of_control",
                    ),
                    _make_finding(severity="P2", title="Minor issue"),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        # After recalibration, P0 count for this customer should be 0
        p0_rows = computed.customer_p0_summary
        assert len(p0_rows) == 0, f"Expected no P0 rows but got {p0_rows}"

    def test_customer_severity_table_keeps_genuine_p0(self) -> None:
        """Genuine P0 findings should still appear in the P0 table."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P0",
                        title="Undisclosed material litigation",
                        category="litigation",
                    ),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        p0_rows = computed.customer_p0_summary
        assert len(p0_rows) == 1
        assert p0_rows[0]["primary_issue"] == "Undisclosed material litigation"

    def test_multiple_rules_different_caps_mildest_wins(self) -> None:
        """When multiple rules match, the mildest (highest P-number) cap wins."""
        # This finding matches both transaction_fee (cap P1) and speculative_language (cap P2).
        # Mildest cap is P2, so P0 should be downgraded to P2.
        finding = _make_finding(
            severity="P0",
            title="Transaction fee must be verified",
            description="Advisory fee that may contain hidden costs",
            category="fees",
        )
        result = ReportDataComputer._recalibrate_severity(finding)
        assert result["severity"] == "P2"
        assert result.get("_recalibrated_from") == "P0"

    def test_tfc_cap_p0_downgraded_to_p2(self) -> None:
        """TfC finding at P0 should be capped to P2 (valuation concern, not deal-blocker)."""
        finding = _make_finding(
            severity="P0",
            title="Termination for convenience clause found",
            category="tfc",
        )
        result = ReportDataComputer._recalibrate_severity(finding)
        assert result["severity"] == "P2"
        assert result.get("_recalibrated_from") == "P0"

    def test_auditor_independence_p0_downgraded_to_p2(self) -> None:
        """Standard auditor independence clause at P0 should be capped to P2."""
        finding = _make_finding(
            severity="P0",
            title="Auditor independence requirements",
            description="Professional independence clause in engagement letter",
        )
        result = ReportDataComputer._recalibrate_severity(finding)
        assert result["severity"] == "P2"
        assert result.get("_recalibrated_from") == "P0"

    def test_require_all_prevents_false_positive(self) -> None:
        """competitor_only_coc requires BOTH title AND category match.

        A finding with 'competitor' in title but wrong category must NOT be recalibrated.
        """
        finding = _make_finding(
            severity="P0",
            title="Competitor analysis shows market risk",
            category="ip_ownership",
        )
        result = ReportDataComputer._recalibrate_severity(finding)
        # Should NOT be recalibrated — category doesn't match change_of_control/coc
        assert result["severity"] == "P0"
        assert "_recalibrated_from" not in result

    def test_wolf_pack_excludes_recalibrated_findings(self) -> None:
        """Wolf pack should exclude findings recalibrated from P0/P1 to lower severity."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P0",
                        title="Competitor-only Change of Control clause",
                        category="change_of_control",
                    ),
                    _make_finding(severity="P2", title="Minor issue"),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        # Competitor CoC recalibrated P0→P3, should not appear in wolf_pack (P0+P1 only)
        assert len(computed.wolf_pack) == 0
        assert len(computed.material_wolf_pack_p0) == 0

    def test_mixed_genuine_and_false_positive_p0(self) -> None:
        """Customer with both genuine and false-positive P0 should count correctly."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P0",
                        title="Undisclosed material litigation",
                        category="litigation",
                    ),
                    _make_finding(
                        severity="P0",
                        title="Competitor-only Change of Control clause",
                        category="change_of_control",
                    ),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        # Only genuine P0 should survive
        assert computed.findings_by_severity.get("P0", 0) == 1
        assert computed.findings_by_severity.get("P3", 0) == 1
        p0_rows = computed.customer_p0_summary
        assert len(p0_rows) == 1
        assert p0_rows[0]["p0_count"] == 1
        assert p0_rows[0]["primary_issue"] == "Undisclosed material litigation"


# ===========================================================================
# Data Quality Classification Tests
# ===========================================================================


class TestDataQualityClassification:
    """Tests for the three-way finding classification: material / data-quality / noise."""

    def test_noise_not_data_quality(self) -> None:
        """Noise findings (extraction failures) should NOT be classified as data quality."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding, _is_noise_finding

        finding = _make_finding(title="Unable to extract content from binary file")
        assert _is_noise_finding(finding) is True
        assert _is_data_quality_finding(finding) is False

    def test_dq_by_pattern(self) -> None:
        """Finding with 'data unavailable' in title is a data quality finding."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding

        finding = _make_finding(title="FY2026 revenue waterfall data unavailable")
        assert _is_data_quality_finding(finding) is True

    def test_dq_by_category(self) -> None:
        """Finding with 'data_gap' category is a data quality finding."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding

        finding = _make_finding(category="data_gap", title="Missing billing records")
        assert _is_data_quality_finding(finding) is True

    def test_material_not_dq(self) -> None:
        """A genuine DD finding (CoC clause) should NOT be classified as data quality."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding

        finding = _make_finding(title="CoC clause requires consent", category="change_of_control")
        assert _is_data_quality_finding(finding) is False

    def test_three_way_counts(self) -> None:
        """compute() should produce correct material/DQ/noise counts in a three-way split."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(severity="P1", title="CoC consent required", category="change_of_control"),
                    _make_finding(severity="P2", title="Revenue waterfall data unavailable"),
                    _make_finding(severity="P2", title="Unable to extract content from binary file"),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        assert computed.material_count == 1  # Only the CoC finding
        assert computed.data_quality_count == 1  # "data unavailable"
        assert computed.noise_count == 1  # "unable to extract"

    def test_dq_excluded_from_wolf_pack(self) -> None:
        """A P1 data-quality finding should NOT appear in the wolf pack."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(severity="P1", title="Billing data unavailable — cannot verify AR quality"),
                    _make_finding(severity="P1", title="Genuine P1 issue", category="ip_ownership"),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        wolf_titles = [f.get("title") for f in computed.material_wolf_pack]
        assert "Genuine P1 issue" in wolf_titles
        assert "Billing data unavailable — cannot verify AR quality" not in wolf_titles

    def test_dq_excluded_from_category_groups(self) -> None:
        """Data quality findings should not appear in domain category_groups."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P2",
                        agent="finance",
                        title="Records unavailable for Q3",
                        category="revenue_recognition",
                    ),
                    _make_finding(
                        severity="P2",
                        agent="finance",
                        title="Revenue mismatch 8%",
                        category="revenue_recognition",
                    ),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        # The DQ finding ("records unavailable") should be excluded from category_groups
        finance_cats = computed.category_groups.get("finance", {})
        all_findings_in_groups = [f for findings in finance_cats.values() for f in findings]
        titles_in_groups = [f.get("title") for f in all_findings_in_groups]
        assert "Revenue mismatch 8%" in titles_in_groups
        assert "Records unavailable for Q3" not in titles_in_groups

    def test_noise_excluded_from_category_groups(self) -> None:
        """Noise findings should not appear in domain category_groups."""
        merged: dict[str, object] = {
            "customer_a": {
                "customer": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P3",
                        agent="finance",
                        title="File not available for extraction",
                        category="revenue_recognition",
                    ),
                    _make_finding(
                        severity="P2",
                        agent="finance",
                        title="Revenue mismatch 8%",
                        category="revenue_recognition",
                    ),
                ],
                "gaps": [],
            }
        }
        computed = ReportDataComputer().compute(merged)
        finance_cats = computed.category_groups.get("finance", {})
        all_findings_in_groups = [f for findings in finance_cats.values() for f in findings]
        titles_in_groups = [f.get("title") for f in all_findings_in_groups]
        assert "Revenue mismatch 8%" in titles_in_groups
        assert "File not available for extraction" not in titles_in_groups


class TestNewCanonicalCategories:
    """Tests for new canonical category mappings added in this change."""

    def test_revenue_composition_normalization(self) -> None:
        """Revenue composition categories should normalize correctly."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("revenue_composition", "finance") == "Revenue Composition"
        assert _normalize_category("subscription_vs_services", "finance") == "Revenue Composition"
        assert _normalize_category("services_revenue_breakdown", "finance") == "Revenue Composition"

    def test_customer_segmentation_normalization(self) -> None:
        """Customer segmentation categories should normalize correctly."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("customer_segmentation", "commercial") == "Customer Segmentation"
        assert _normalize_category("cohort_analysis", "commercial") == "Customer Segmentation"
        assert _normalize_category("geographic_distribution", "commercial") == "Customer Segmentation"
