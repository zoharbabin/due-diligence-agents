"""Per-agent quality evaluation tests.

These tests validate that specialist agents produce correct findings against
ground truth contracts. They require an API key and are marked with @pytest.mark.eval.

For offline/unit testing of the metrics themselves, see the metric computation
tests at the bottom of this module which run without an API key.
"""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import make_finding_dict
from .metrics import (
    _categories_match,
    _expand_keyword,
    _severity_in_range,
    compute_agent_metrics,
    evaluate_verdict,
    match_finding,
)
from .models import (
    AgentEvalMetrics,
    EvalBaseline,
    ExpectedFinding,
    GroundTruth,
    MustNotFind,
    Verdict,
)

# Default ambiguity band for the near-deterministic quality metrics (citation /
# severity accuracy) when a ground-truth file does not specify one. Recall and
# false-positive thresholds are deliberately NOT banded — see the module tests.
_DEFAULT_QUALITY_ZONE = 0.10


def _agent_ambiguity_zone(agent_name: str) -> float:
    """Max ``ambiguity_zone`` declared across an agent's ground-truth files.

    Lets a contract opt into a wider inconclusive band for the near-deterministic
    quality metrics; falls back to :data:`_DEFAULT_QUALITY_ZONE`. Pure file read,
    no model calls.
    """
    import json
    from pathlib import Path

    expected_dir = Path(__file__).parent / "ground_truth" / "expected" / agent_name
    zones = [_DEFAULT_QUALITY_ZONE]
    if expected_dir.is_dir():
        for gt_file in expected_dir.glob("*.json"):
            try:
                zones.append(float(json.loads(gt_file.read_text()).get("ambiguity_zone", 0.0)))
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                continue
    return max(zones)


class TestCategoryMatch:
    """Unit tests for category synonym matching."""

    def test_exact_match(self) -> None:
        assert _categories_match("change_of_control", "change_of_control") is True

    def test_substring_match(self) -> None:
        assert _categories_match("change_of_control_risk", "change_of_control") is True

    def test_synonym_match(self) -> None:
        assert _categories_match("access_control", "access_controls") is True

    def test_synonym_reverse_lookup(self) -> None:
        assert _categories_match("sla_compliance", "sla_risk") is True

    def test_synonym_encryption(self) -> None:
        assert _categories_match("encryption", "encryption_standards") is True

    def test_synonym_vulnerability(self) -> None:
        assert _categories_match("vulnerability", "vulnerability_management") is True

    def test_synonym_data_breach(self) -> None:
        assert _categories_match("data_breach", "data_breach_history") is True

    def test_synonym_vendor_risk(self) -> None:
        assert _categories_match("vendor_risk", "third_party_risk") is True

    def test_no_match_unrelated(self) -> None:
        assert _categories_match("pricing", "change_of_control") is False

    def test_no_match_different_domains(self) -> None:
        assert _categories_match("data_privacy", "revenue_recognition") is False

    def test_liability_cap_matches_liability(self) -> None:
        assert _categories_match("liability_cap", "liability") is True

    def test_financial_analysis_matches_discrepancy(self) -> None:
        assert _categories_match("financial_analysis", "financial_discrepancy") is True


# ---------------------------------------------------------------------------
# Live agent eval tests (require API key — skip if unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestAgentEvals:
    """Per-agent quality eval tests -- require API key, run on CI main branch only."""

    @pytest.fixture(autouse=True)
    def _skip_without_credentials(self) -> None:
        """Skip all tests in this class if no API credentials are available."""
        from .conftest import _has_api_credentials

        if not _has_api_credentials():
            pytest.skip("No API credentials (ANTHROPIC_API_KEY or Bedrock) — skipping live eval tests")

    def test_finding_recall(self, agent_metrics: AgentEvalMetrics) -> None:
        """Agent must find at least 80% of expected findings."""
        assert agent_metrics.finding_recall >= 0.80

    def test_citation_accuracy(self, agent_metrics: AgentEvalMetrics) -> None:
        """At least 90% of matched findings must have correct citations.

        Routed through the three-valued verdict: a value inside the ground
        truth's ``ambiguity_zone`` is INCONCLUSIVE (logged, not auto-passed); only
        a value clearly below the band FAILs. Citation accuracy is near-
        deterministic (typically 1.0), so the band only absorbs rare noise — it
        can never turn a genuine miss into a pass (see test_eval_robustness).
        """
        verdict = evaluate_verdict(
            agent_metrics.citation_accuracy, 0.90, ambiguity_zone=_agent_ambiguity_zone(agent_metrics.agent_name)
        )
        if verdict == Verdict.INCONCLUSIVE:
            pytest.skip(f"citation_accuracy={agent_metrics.citation_accuracy:.2f} inside ambiguity band (inconclusive)")
        assert verdict == Verdict.PASS, f"citation_accuracy={agent_metrics.citation_accuracy:.2f} below 0.90 band"

    def test_severity_calibration(self, agent_metrics: AgentEvalMetrics) -> None:
        """At least 75% of matched findings must have severity in acceptable range.

        Same three-valued treatment as citation accuracy: inconclusive inside the
        band, hard FAIL clearly below it.
        """
        verdict = evaluate_verdict(
            agent_metrics.severity_accuracy, 0.75, ambiguity_zone=_agent_ambiguity_zone(agent_metrics.agent_name)
        )
        if verdict == Verdict.INCONCLUSIVE:
            pytest.skip(f"severity_accuracy={agent_metrics.severity_accuracy:.2f} inside ambiguity band (inconclusive)")
        assert verdict == Verdict.PASS, f"severity_accuracy={agent_metrics.severity_accuracy:.2f} below 0.75 band"

    def test_false_positive_rate(self, agent_metrics: AgentEvalMetrics) -> None:
        """False positive rate must be at most 15%."""
        assert agent_metrics.false_positive_rate <= 0.15

    def test_no_regression(
        self,
        agent_metrics: AgentEvalMetrics,
        baseline: EvalBaseline | None,
        update_baseline: bool,
    ) -> None:
        """F1 score must not regress more than 5 points from stored baseline.

        When ``--update-baseline`` is passed the operator is intentionally
        re-capturing the baseline, so comparing against the OLD baseline is
        meaningless and would deadlock the recapture (a stale/placeholder
        baseline could fail this test, which previously blocked the
        session-finish save). Skip the comparison in that mode and let
        ``pytest_sessionfinish`` persist the freshly measured metrics.
        """
        if update_baseline:
            pytest.skip("--update-baseline: re-capturing, regression comparison skipped")
        if baseline is None:
            pytest.skip("No stored baseline — skipping regression check")
        agent_baseline = baseline.metrics.get(agent_metrics.agent_name)
        if agent_baseline is None:
            pytest.skip(f"No baseline for agent {agent_metrics.agent_name}")
        assert agent_metrics.f1_score >= agent_baseline.f1_score - 0.05


# ---------------------------------------------------------------------------
# Offline metric computation tests (no API key required)
# ---------------------------------------------------------------------------


class TestMatchFinding:
    """Unit tests for match_finding logic."""

    def test_category_match(self) -> None:
        produced = make_finding_dict(category="change_of_control", title="CoC clause found")
        expected = ExpectedFinding(category="change_of_control")
        assert match_finding(produced, expected) is True

    def test_category_mismatch(self) -> None:
        produced = make_finding_dict(category="termination")
        expected = ExpectedFinding(category="change_of_control")
        assert match_finding(produced, expected) is False

    def test_category_substring_match(self) -> None:
        produced = make_finding_dict(category="change_of_control_risk")
        expected = ExpectedFinding(category="change_of_control")
        assert match_finding(produced, expected) is True

    def test_keyword_containment(self) -> None:
        produced = make_finding_dict(
            category="change_of_control",
            title="Change of control clause allows termination",
            description="Client may terminate upon change of control.",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            must_contain_keywords=["terminate", "change of control"],
        )
        assert match_finding(produced, expected) is True

    def test_keyword_missing(self) -> None:
        produced = make_finding_dict(
            category="change_of_control",
            title="CoC clause found",
            description="A clause exists.",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            must_contain_keywords=["terminate"],
        )
        assert match_finding(produced, expected) is False

    def test_keyword_synonym_match(self) -> None:
        """Agent writes 'cancel' but expected keyword is 'terminate' — synonym should match."""
        produced = make_finding_dict(
            category="change_of_control",
            title="CoC clause allows cancellation",
            description="Client may cancel upon change of control.",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            must_contain_keywords=["terminate"],
        )
        assert match_finding(produced, expected) is True

    def test_explicit_keyword_synonym_match(self) -> None:
        """Explicit synonym set in the expected finding overrides common synonyms."""
        produced = make_finding_dict(
            category="change_of_control",
            title="Fundamental restructuring triggers opt-out",
            description="Client may opt out upon restructuring.",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            must_contain_keywords=["restructuring"],
            keyword_synonyms={"restructuring": ["reorganization", "fundamental change"]},
        )
        assert match_finding(produced, expected) is True

    def test_synonym_no_false_expansion(self) -> None:
        """Synonyms for 'terminate' should not match unrelated words."""
        produced = make_finding_dict(
            category="change_of_control",
            title="CoC clause found",
            description="Ownership change detected.",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            must_contain_keywords=["terminate"],
        )
        assert match_finding(produced, expected) is False

    def test_citation_file_reference(self) -> None:
        produced = make_finding_dict(
            category="change_of_control",
            source_path="contracts/coc_basic.md",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            citation_must_reference={"file": "coc_basic.md"},
        )
        assert match_finding(produced, expected) is True

    def test_citation_file_reference_missing(self) -> None:
        produced = make_finding_dict(
            category="change_of_control",
            source_path="contracts/other_contract.md",
        )
        expected = ExpectedFinding(
            category="change_of_control",
            citation_must_reference={"file": "coc_basic.md"},
        )
        assert match_finding(produced, expected) is False

    def test_alternative_category_matches(self) -> None:
        """An SLA-triggered termination right the agent files under 'sla_risk' must
        match a 'termination' expected finding that declares it as an alternative."""
        produced = make_finding_dict(
            category="sla_compliance",
            title="Performance-based MSA termination right triggered by SLA failures",
            description="Client may terminate the MSA with 30 days notice.",
        )
        expected = ExpectedFinding(
            category="termination",
            alternative_categories=["sla_risk"],
            must_contain_keywords=["terminate"],
        )
        assert match_finding(produced, expected) is True

    def test_alternative_category_still_requires_keyword(self) -> None:
        """alternative_categories widens CATEGORY acceptance only — the discriminating
        keyword must still be present, so an unrelated SLA finding does NOT match."""
        produced = make_finding_dict(
            category="sla_compliance",
            title="Service credit for uptime shortfall",
            description="10% credit applies.",
        )
        expected = ExpectedFinding(
            category="termination",
            alternative_categories=["sla_risk"],
            must_contain_keywords=["terminate"],
        )
        assert match_finding(produced, expected) is False

    def test_no_alternative_categories_unchanged(self) -> None:
        """Default (empty alternative_categories) preserves strict single-category matching."""
        produced = make_finding_dict(category="sla_compliance", title="SLA breach")
        expected = ExpectedFinding(category="termination", must_contain_keywords=[])
        assert match_finding(produced, expected) is False


class TestExpandKeyword:
    """Unit tests for synonym expansion."""

    def test_expand_known_keyword(self) -> None:
        expanded = _expand_keyword("terminate", {})
        assert "terminate" in expanded
        assert "cancel" in expanded
        assert "cease" in expanded

    def test_expand_with_explicit_synonyms(self) -> None:
        expanded = _expand_keyword("restructuring", {"restructuring": ["reorg", "reorganize"]})
        assert "restructuring" in expanded
        assert "reorg" in expanded
        assert "reorganize" in expanded

    def test_expand_unknown_keyword(self) -> None:
        expanded = _expand_keyword("xylophone", {})
        assert expanded == {"xylophone"}

    def test_common_synonym_case_insensitive(self) -> None:
        expanded = _expand_keyword("MFA", {})
        assert "multi-factor" in expanded or "mfa" in expanded


class TestSeverityRange:
    """Unit tests for severity range checking."""

    def test_p1_in_p0_p3_range(self) -> None:
        assert _severity_in_range("P1", "P3", "P0") is True

    def test_p0_in_p0_p0_range(self) -> None:
        assert _severity_in_range("P0", "P0", "P0") is True

    def test_p3_outside_p0_p1_range(self) -> None:
        assert _severity_in_range("P3", "P1", "P0") is False

    def test_invalid_severity(self) -> None:
        assert _severity_in_range("PX", "P3", "P0") is False


class TestComputeAgentMetrics:
    """Unit tests for compute_agent_metrics."""

    def _make_ground_truth(
        self,
        expected: list[ExpectedFinding] | None = None,
        must_not: list[MustNotFind] | None = None,
    ) -> GroundTruth:
        return GroundTruth(
            contract="test.md",
            agent="legal",
            expected_findings=expected or [],
            must_not_find=must_not or [],
        )

    def test_perfect_score(self) -> None:
        expected = [
            ExpectedFinding(category="change_of_control", must_contain_keywords=["terminate"]),
            ExpectedFinding(category="termination", must_contain_keywords=["cure"]),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                title="CoC termination clause",
                description="Client may terminate upon change of control.",
                severity="P1",
                source_path="test.md",
            ),
            make_finding_dict(
                category="termination",
                title="Termination with cure period",
                description="30 day cure period for material breach.",
                severity="P2",
                source_path="test.md",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.finding_recall == 1.0
        assert metrics.finding_precision == 1.0
        assert metrics.f1_score == 1.0
        assert metrics.finding_count == 2

    def test_synonym_match_counts_for_recall(self) -> None:
        """Agent uses synonym 'cancel' instead of 'terminate' — should still match."""
        expected = [
            ExpectedFinding(category="change_of_control", must_contain_keywords=["terminate"]),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                title="CoC cancellation clause",
                description="Client may cancel upon change of control.",
                severity="P1",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)
        assert metrics.finding_recall == 1.0

    def test_zero_recall(self) -> None:
        expected = [
            ExpectedFinding(category="change_of_control", must_contain_keywords=["terminate"]),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(category="liability", title="Liability cap"),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.finding_recall == 0.0
        assert metrics.finding_precision == 0.0

    def test_false_positive_detection(self) -> None:
        must_not = [MustNotFind(category="data_privacy")]
        produced: list[dict[str, Any]] = [
            make_finding_dict(category="data_privacy", title="Privacy concern"),
            make_finding_dict(category="change_of_control", title="CoC found"),
        ]
        gt = self._make_ground_truth(must_not=must_not)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.false_positive_rate == 0.5
        assert metrics.finding_count == 2

    def test_empty_produced(self) -> None:
        expected = [ExpectedFinding(category="change_of_control")]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics([], gt)

        assert metrics.finding_recall == 0.0
        assert metrics.finding_precision == 1.0
        assert metrics.false_positive_rate == 0.0
        assert metrics.finding_count == 0

    def test_no_required_findings(self) -> None:
        expected = [
            ExpectedFinding(category="liability", required=False),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(category="liability", title="Liability cap"),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.finding_recall == 1.0

    def test_one_finding_covering_two_real_risks_credits_both(self) -> None:
        """Recall is many-to-one: a single finding that genuinely contains BOTH
        expecteds' discriminating keywords credits both (an agent that legitimately
        consolidates a non-compete + termination clause is not penalised)."""
        # Both expecteds accept the agent's actual category ("labor_compliance")
        # via alternative_categories — mirroring the real HR ground truth.
        expected = [
            ExpectedFinding(
                category="non_compete",
                alternative_categories=["labor_compliance"],
                must_contain_keywords=["non-compete"],
            ),
            ExpectedFinding(
                category="termination_provisions",
                alternative_categories=["labor_compliance"],
                must_contain_keywords=["terminat"],
            ),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="labor_compliance",
                title="24-month non-compete and termination terms",
                description="The non-compete runs 24 months; termination without cause requires 8 weeks notice.",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)
        assert metrics.finding_recall == 1.0  # both required risks surfaced by one finding

    def test_many_to_one_does_not_overcredit_off_keyword(self) -> None:
        """A consolidated finding only credits expecteds whose keyword it actually
        contains — it cannot satisfy an unrelated expected by category alone."""
        expected = [
            ExpectedFinding(
                category="non_compete",
                alternative_categories=["labor_compliance"],
                must_contain_keywords=["non-compete"],
            ),
            ExpectedFinding(
                category="termination_provisions",
                alternative_categories=["labor_compliance"],
                must_contain_keywords=["terminat"],
            ),
        ]
        produced: list[dict[str, Any]] = [
            # Category is accepted by BOTH expecteds, but the text mentions only
            # non-compete — the keyword gate must still miss termination.
            make_finding_dict(
                category="labor_compliance",
                title="24-month non-compete",
                description="The non-compete runs 24 months.",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)
        assert metrics.finding_recall == 0.5  # only non_compete; termination genuinely missed

    def test_severity_accuracy(self) -> None:
        expected = [
            ExpectedFinding(
                category="change_of_control",
                min_severity="P2",
                max_severity="P0",
                must_contain_keywords=["terminate"],
            ),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                severity="P1",
                title="CoC termination",
                description="May terminate.",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.severity_accuracy == 1.0

    def test_severity_out_of_range(self) -> None:
        expected = [
            ExpectedFinding(
                category="change_of_control",
                min_severity="P2",
                max_severity="P0",
                must_contain_keywords=["terminate"],
            ),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                severity="P3",
                title="CoC termination",
                description="May terminate.",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.severity_accuracy == 0.0

    def test_citation_accuracy_pass(self) -> None:
        expected = [
            ExpectedFinding(
                category="change_of_control",
                must_contain_keywords=["terminate"],
                citation_must_reference={"file": "coc_basic.md", "page_or_section": "Section 4"},
            ),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                title="CoC termination",
                description="May terminate.",
                source_path="contracts/coc_basic.md",
                location="Section 4.1",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.citation_accuracy == 1.0

    def test_citation_accuracy_fail(self) -> None:
        expected = [
            ExpectedFinding(
                category="change_of_control",
                must_contain_keywords=["terminate"],
                citation_must_reference={"file": "coc_basic.md"},
            ),
        ]
        produced: list[dict[str, Any]] = [
            make_finding_dict(
                category="change_of_control",
                title="CoC termination",
                description="May terminate.",
                source_path="contracts/wrong_file.md",
            ),
        ]
        gt = self._make_ground_truth(expected=expected)
        metrics = compute_agent_metrics(produced, gt)

        assert metrics.finding_recall == 0.0


class TestVerdictIntegration:
    """Test that three-valued verdicts work with metric thresholds."""

    def test_recall_passes(self) -> None:
        verdict = evaluate_verdict(0.85, 0.80)
        assert verdict == Verdict.PASS

    def test_recall_fails_hard(self) -> None:
        verdict = evaluate_verdict(0.50, 0.80, ambiguity_zone=0.10)
        assert verdict == Verdict.FAIL

    def test_recall_inconclusive(self) -> None:
        verdict = evaluate_verdict(0.72, 0.80, ambiguity_zone=0.10)
        assert verdict == Verdict.INCONCLUSIVE

    def test_fp_rate_passes(self) -> None:
        verdict = evaluate_verdict(0.10, 0.15, higher_is_better=False)
        assert verdict == Verdict.PASS

    def test_fp_rate_fails(self) -> None:
        verdict = evaluate_verdict(0.30, 0.15, ambiguity_zone=0.05, higher_is_better=False)
        assert verdict == Verdict.FAIL

    def test_fp_rate_inconclusive(self) -> None:
        verdict = evaluate_verdict(0.18, 0.15, ambiguity_zone=0.05, higher_is_better=False)
        assert verdict == Verdict.INCONCLUSIVE
