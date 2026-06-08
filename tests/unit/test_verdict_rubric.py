"""Unit tests for the deterministic verdict rubric (Issue #195).

Covers:
- Determinism: identical inputs → identical output
- Threshold boundaries: P0/P1 exact cutoffs
- Custom rubric overrides
- Exposure percentage factor
- Cross-domain compound severity factor
- Executive takeaways generation
- Financial exposure de-duplication
- Verdict integration with computed_metrics
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.verdict import (
    SIGNAL_CONDITIONAL,
    SIGNAL_NO_GO,
    SIGNAL_PROCEED,
    SIGNAL_PROCEED_CONDITIONS,
    VerdictRubric,
    compute_verdict,
    generate_executive_takeaways,
)

# ===========================================================================
# Determinism
# ===========================================================================


class TestDeterminism:
    """Identical inputs must always produce identical output."""

    def test_same_inputs_same_output(self) -> None:
        """Calling compute_verdict twice with same args returns equal results."""
        args: dict[str, Any] = {"p0_count": 2, "p1_count": 5, "exposure_pct": 30.0, "risk_score": 72.0}
        r1 = compute_verdict(**args)
        r2 = compute_verdict(**args)
        assert r1.signal == r2.signal
        assert r1.rationale == r2.rationale
        assert r1.contributing_factors == r2.contributing_factors

    def test_frozen_rubric(self) -> None:
        """VerdictRubric is immutable."""
        import pytest

        rubric = VerdictRubric()
        with pytest.raises((TypeError, AttributeError)):
            rubric.no_go_p0_min = 5  # type: ignore[misc]

    def test_frozen_result(self) -> None:
        """VerdictResult is immutable."""
        import pytest

        result = compute_verdict(p0_count=0, p1_count=0, exposure_pct=0.0)
        with pytest.raises((TypeError, AttributeError)):
            result.signal = "CHANGED"  # type: ignore[misc]


# ===========================================================================
# Threshold Boundaries
# ===========================================================================


class TestThresholds:
    """Test exact threshold cutoffs for each signal."""

    def test_zero_p0_zero_p1_is_proceed(self) -> None:
        """No findings → PROCEED."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=0.0)
        assert r.signal == SIGNAL_PROCEED

    def test_one_p0_is_no_go(self) -> None:
        """Exactly 1 P0 → NO-GO (default threshold)."""
        r = compute_verdict(p0_count=1, p1_count=0, exposure_pct=0.0)
        assert r.signal == SIGNAL_NO_GO

    def test_many_p0_is_no_go(self) -> None:
        """Multiple P0s → NO-GO."""
        r = compute_verdict(p0_count=5, p1_count=10, exposure_pct=50.0)
        assert r.signal == SIGNAL_NO_GO

    def test_three_p1_is_conditional(self) -> None:
        """P1 >= 3 → CONDITIONAL."""
        r = compute_verdict(p0_count=0, p1_count=3, exposure_pct=0.0)
        assert r.signal == SIGNAL_CONDITIONAL

    def test_two_p1_is_proceed_with_conditions(self) -> None:
        """P1 = 2 → PROCEED WITH CONDITIONS (between 1 and 3)."""
        r = compute_verdict(p0_count=0, p1_count=2, exposure_pct=0.0)
        assert r.signal == SIGNAL_PROCEED_CONDITIONS

    def test_one_p1_is_proceed_with_conditions(self) -> None:
        """P1 = 1 → PROCEED WITH CONDITIONS."""
        r = compute_verdict(p0_count=0, p1_count=1, exposure_pct=0.0)
        assert r.signal == SIGNAL_PROCEED_CONDITIONS

    def test_p0_takes_precedence_over_p1(self) -> None:
        """P0 present with many P1 → still NO-GO (P0 rule takes priority)."""
        r = compute_verdict(p0_count=1, p1_count=10, exposure_pct=0.0)
        assert r.signal == SIGNAL_NO_GO

    def test_high_exposure_alone_is_proceed_with_conditions(self) -> None:
        """High revenue exposure (>20%) alone → PROCEED WITH CONDITIONS."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=30.0)
        assert r.signal == SIGNAL_PROCEED_CONDITIONS
        assert "30%" in r.rationale

    def test_exposure_at_threshold_is_proceed(self) -> None:
        """Exposure exactly at threshold (20%) → PROCEED (must exceed, not equal)."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=20.0)
        assert r.signal == SIGNAL_PROCEED

    def test_exposure_just_above_threshold(self) -> None:
        """Exposure just above threshold (20.1%) → PROCEED WITH CONDITIONS."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=20.1)
        assert r.signal == SIGNAL_PROCEED_CONDITIONS


# ===========================================================================
# Custom Rubric Overrides
# ===========================================================================


class TestCustomRubric:
    """Test configurable rubric thresholds."""

    def test_raised_no_go_threshold(self) -> None:
        """With no_go_p0_min=3, 2 P0s is CONDITIONAL (if P1>=3) not NO-GO."""
        rubric = VerdictRubric(no_go_p0_min=3, conditional_p1_min=3)
        r = compute_verdict(p0_count=2, p1_count=5, exposure_pct=0.0, rubric=rubric)
        assert r.signal == SIGNAL_CONDITIONAL

    def test_lowered_conditional_threshold(self) -> None:
        """With conditional_p1_min=2, 2 P1s → CONDITIONAL."""
        rubric = VerdictRubric(conditional_p1_min=2)
        r = compute_verdict(p0_count=0, p1_count=2, exposure_pct=0.0, rubric=rubric)
        assert r.signal == SIGNAL_CONDITIONAL

    def test_default_rubric_values(self) -> None:
        """Default rubric has expected conservative thresholds."""
        rubric = VerdictRubric()
        assert rubric.no_go_p0_min == 1
        assert rubric.conditional_p1_min == 3
        assert rubric.proceed_with_conditions_p1_min == 1
        assert rubric.high_exposure_pct == 20.0


# ===========================================================================
# Contributing Factors & Exposure
# ===========================================================================


class TestContributingFactors:
    """Test that contributing factors are correctly populated."""

    def test_no_go_includes_p0_count(self) -> None:
        """NO-GO rationale references P0 count."""
        r = compute_verdict(p0_count=2, p1_count=0, exposure_pct=0.0)
        assert "2 critical deal-breaker(s)" in r.rationale

    def test_no_go_includes_cross_domain_factor(self) -> None:
        """NO-GO with cross-domain compounds includes that factor."""
        r = compute_verdict(p0_count=1, p1_count=0, exposure_pct=0.0, cross_domain_critical_count=3)
        assert any("cross-domain" in f for f in r.contributing_factors)

    def test_no_go_includes_exposure_factor(self) -> None:
        """NO-GO with high exposure includes revenue factor."""
        r = compute_verdict(p0_count=1, p1_count=0, exposure_pct=25.0)
        assert any("revenue at risk" in f for f in r.contributing_factors)

    def test_conditional_includes_exposure_factor(self) -> None:
        """CONDITIONAL with high exposure includes revenue factor."""
        r = compute_verdict(p0_count=0, p1_count=4, exposure_pct=30.0)
        assert any("revenue at risk" in f for f in r.contributing_factors)

    def test_proceed_includes_no_blockers(self) -> None:
        """PROCEED includes 'No material blockers' factor."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=0.0)
        assert any("No material blockers" in f for f in r.contributing_factors)

    def test_risk_score_passthrough(self) -> None:
        """risk_score is stored on the result unchanged."""
        r = compute_verdict(p0_count=0, p1_count=0, exposure_pct=0.0, risk_score=55.5)
        assert r.risk_score == 55.5


# ===========================================================================
# Executive Takeaways Generation
# ===========================================================================


class TestExecutiveTakeaways:
    """Test generate_executive_takeaways deterministic behavior."""

    def test_empty_inputs_returns_clean_signal(self) -> None:
        """With no findings, returns a 'no material blockers' takeaway."""
        result = generate_executive_takeaways(
            cross_domain_risks=[],
            material_findings=[],
            display_names={},
            total_contracted_arr=0.0,
            revenue_by_subject={},
        )
        assert len(result) >= 1
        assert any("No material blockers" in t["text"] for t in result)

    def test_cross_domain_risk_generates_takeaway(self) -> None:
        """Cross-domain risk with 2+ domains generates a takeaway."""
        risks = [
            {
                "entity": "acme",
                "domains": ["legal", "finance"],
                "finding_count": 4,
                "has_p0": True,
            }
        ]
        result = generate_executive_takeaways(
            cross_domain_risks=risks,
            material_findings=[{"agent": "legal"}],
            display_names={"acme": "Acme Corp"},
            total_contracted_arr=1000000.0,
            revenue_by_subject={"acme": 500000.0},
        )
        assert any("Acme Corp" in t["text"] for t in result)
        assert any("critical" in t.get("severity", "") for t in result)

    def test_revenue_concentration_takeaway(self) -> None:
        """Entity >30% of ARR generates concentration warning."""
        result = generate_executive_takeaways(
            cross_domain_risks=[],
            material_findings=[],
            display_names={"big_co": "Big Co"},
            total_contracted_arr=100000.0,
            revenue_by_subject={"big_co": 60000.0},
        )
        assert any("60%" in t["text"] for t in result)
        assert any("concentrated" in t["text"].lower() or "concentration" in t["text"].lower() for t in result)

    def test_no_concentration_below_threshold(self) -> None:
        """Entity <30% of ARR does NOT generate concentration warning."""
        result = generate_executive_takeaways(
            cross_domain_risks=[],
            material_findings=[],
            display_names={"small_co": "Small Co"},
            total_contracted_arr=100000.0,
            revenue_by_subject={"small_co": 20000.0},
        )
        assert not any("concentration" in t["text"].lower() for t in result)

    def test_max_five_takeaways(self) -> None:
        """Never returns more than 5 takeaways."""
        risks = [
            {"entity": f"e{i}", "domains": ["legal", "finance", "commercial"], "finding_count": 3, "has_p0": True}
            for i in range(10)
        ]
        result = generate_executive_takeaways(
            cross_domain_risks=risks,
            material_findings=[{"agent": "legal"} for _ in range(10)],
            display_names={},
            total_contracted_arr=1000000.0,
            revenue_by_subject={f"e{i}": 500000.0 for i in range(10)},
        )
        assert len(result) <= 5

    def test_clean_domains_reported(self) -> None:
        """Domains without material findings are noted as clean."""
        result = generate_executive_takeaways(
            cross_domain_risks=[],
            material_findings=[{"agent": "legal"}, {"agent": "finance"}],
            display_names={},
            total_contracted_arr=0.0,
            revenue_by_subject={},
        )
        clean_ta = [t for t in result if "No material blockers" in t["text"]]
        assert len(clean_ta) == 1
        assert clean_ta[0]["severity"] == "good"


# ===========================================================================
# Integration: computed_metrics uses verdict
# ===========================================================================


class TestVerdictInComputedMetrics:
    """Test that ReportDataComputer.compute() invokes verdict logic."""

    def _make_merged(self, findings: list[dict[str, Any]]) -> dict[str, Any]:
        return {"test_entity": {"subject": "test_entity", "findings": findings, "gaps": []}}

    def _make_finding(self, severity: str = "P2", title: str = "Finding") -> dict[str, Any]:
        return {
            "severity": severity,
            "title": title,
            "description": "A finding",
            "agent": "legal",
            "category": "uncategorized",
            "citations": [],
        }

    def test_verdict_field_populated(self) -> None:
        """compute() populates verdict dict with signal and rationale."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P0")])
        data = ReportDataComputer().compute(merged)
        assert data.verdict is not None
        assert data.verdict["signal"] == SIGNAL_NO_GO

    def test_verdict_proceed_on_clean(self) -> None:
        """No material findings → PROCEED."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P3")])
        data = ReportDataComputer().compute(merged)
        assert data.verdict is not None
        assert data.verdict["signal"] == SIGNAL_PROCEED

    def test_verdict_conditional_on_three_p1(self) -> None:
        """Three P1 findings → CONDITIONAL."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P1", f"Issue {i}") for i in range(3)])
        data = ReportDataComputer().compute(merged)
        assert data.verdict is not None
        assert data.verdict["signal"] == SIGNAL_CONDITIONAL

    def test_executive_takeaways_populated(self) -> None:
        """compute() populates executive_takeaways list."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P0")])
        data = ReportDataComputer().compute(merged)
        assert isinstance(data.executive_takeaways, list)

    def test_valuation_dedup(self) -> None:
        """One entity's revenue counts once even when at risk across two categories.

        A single subject with both a change-of-control and a termination-for-
        convenience finding must not have its ARR double-counted in the
        valuation bridge total exposure.
        """
        from dd_agents.reporting.computed_metrics import ReportDataComputer

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
                    },
                    {
                        "severity": "P1",
                        "title": "Termination for convenience clause",
                        "description": "Counterparty may terminate without cause",
                        "agent": "legal",
                        "category": "termination",
                        "citations": [],
                    },
                ],
                "gaps": [],
                "cross_references": [
                    {"data_point": "ARR", "reference_value": "$1,000,000"},
                ],
            }
        }
        data = ReportDataComputer().compute(merged)
        # Subject ARR counted once across both categories, not 2x.
        assert data.valuation_bridge["total_exposure"] == 1_000_000.0

    def test_no_revenue_data_gates_bridge(self) -> None:
        """With no revenue data the valuation bridge is empty and fails closed."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P3")])
        data = ReportDataComputer().compute(merged)
        assert data.valuation_bridge == {}
        # No exposure rule fires → otherwise-clean findings stay PROCEED.
        assert data.verdict is not None
        assert data.verdict["signal"] == SIGNAL_PROCEED

    def test_verdict_rubric_override_from_config(self) -> None:
        """A custom rubric passed into compute() reaches compute_verdict."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged = self._make_merged([self._make_finding("P0")])
        # Raise the NO-GO threshold so a single P0 no longer trips it.
        data = ReportDataComputer().compute(merged, rubric=VerdictRubric(no_go_p0_min=2))
        assert data.verdict is not None
        assert data.verdict["signal"] != SIGNAL_NO_GO
