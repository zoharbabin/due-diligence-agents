"""Offline tests for eval-harness robustness (no API key required).

These guard the de-noising + verdict machinery that makes the live agent evals
reliable without masking real regressions:

- ``aggregate_metrics_median`` collapses N stochastic samples to the median of
  each scalar — variance reduction that a single lucky draw cannot game.
- ``evaluate_verdict`` must never turn a value below ``threshold - zone`` into a
  non-FAIL (the anti-masking invariant the ambiguity band relies on).
"""

from __future__ import annotations

from .conftest import aggregate_metrics_median
from .metrics import evaluate_verdict
from .models import AgentEvalMetrics, Verdict


def _m(agent: str = "commercial", *, recall: float, precision: float, f1: float, count: int) -> AgentEvalMetrics:
    return AgentEvalMetrics(
        agent_name=agent,
        finding_recall=recall,
        finding_precision=precision,
        citation_accuracy=1.0,
        severity_accuracy=1.0,
        false_positive_rate=0.0,
        f1_score=f1,
        finding_count=count,
    )


# ---------------------------------------------------------------------------
# Median aggregation
# ---------------------------------------------------------------------------


def test_median_picks_middle_sample_not_best() -> None:
    """Median, not max: a single lucky high draw cannot rescue a degraded agent."""
    samples = [
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.75, precision=0.625, f1=0.633, count=10),
        _m(recall=1.0, precision=0.8, f1=0.8, count=6),
    ]
    agg = aggregate_metrics_median(samples)
    assert agg.finding_recall == 0.75  # middle, not 1.0
    assert agg.f1_score == 0.633
    assert agg.finding_count == 8  # median of 8/10/6


def test_median_single_sample_is_identity() -> None:
    """DD_EVAL_SAMPLES=1 (default) must behave exactly like today."""
    only = _m(recall=0.75, precision=0.625, f1=0.633, count=10)
    agg = aggregate_metrics_median([only])
    assert agg.finding_recall == only.finding_recall
    assert agg.f1_score == only.f1_score
    assert agg.finding_count == only.finding_count
    assert agg.agent_name == only.agent_name


def test_median_even_count_uses_low_median_for_count() -> None:
    """finding_count stays an integer (statistics.median_low) for even N."""
    agg = aggregate_metrics_median(
        [
            _m(recall=1.0, precision=1.0, f1=1.0, count=4),
            _m(recall=1.0, precision=1.0, f1=1.0, count=6),
        ]
    )
    assert isinstance(agg.finding_count, int)
    assert agg.finding_count in (4, 6)


def test_median_one_lucky_draw_cannot_rescue_degraded_recall() -> None:
    """Anti-masking: 4 of 5 samples show a real recall drop; the median still fails the floor."""
    samples = [
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
        _m(recall=1.0, precision=0.8, f1=0.8, count=6),  # lucky draw
        _m(recall=0.5, precision=0.6, f1=0.55, count=8),
    ]
    agg = aggregate_metrics_median(samples)
    assert agg.finding_recall == 0.5  # median, < 0.80 floor → still FAILS
    assert agg.finding_recall < 0.80


# ---------------------------------------------------------------------------
# Verdict band cannot mask a real miss
# ---------------------------------------------------------------------------


def test_verdict_below_threshold_minus_zone_is_always_fail() -> None:
    """A value clearly below the band can never be coerced to non-FAIL — at any zone."""
    for zone in (0.0, 0.05, 0.10, 0.15, 0.30):
        v = evaluate_verdict(0.40, 0.80, ambiguity_zone=zone, higher_is_better=True)
        assert v == Verdict.FAIL


def test_verdict_inside_band_is_inconclusive_not_pass() -> None:
    """Inside the band is INCONCLUSIVE (logged), never an automatic PASS."""
    v = evaluate_verdict(0.74, 0.80, ambiguity_zone=0.10, higher_is_better=True)
    # The point: a sub-threshold value lands INCONCLUSIVE (logged), not PASS.
    assert v == Verdict.INCONCLUSIVE


def test_verdict_zero_zone_is_strict_pass_fail() -> None:
    assert evaluate_verdict(0.80, 0.80, ambiguity_zone=0.0) == Verdict.PASS
    assert evaluate_verdict(0.7999, 0.80, ambiguity_zone=0.0) == Verdict.FAIL
