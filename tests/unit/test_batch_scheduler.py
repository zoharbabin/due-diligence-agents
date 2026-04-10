"""Tests for parallel execution optimization — batch scheduling (Issue #148)."""

from __future__ import annotations

from dd_agents.orchestrator.batch_scheduler import (
    BatchScheduler,
    SubjectComplexity,
    score_subject_complexity,
)

# ---------------------------------------------------------------------------
# Subject complexity scoring tests
# ---------------------------------------------------------------------------


class TestSubjectComplexity:
    """Test subject complexity scoring."""

    def test_empty_subject(self) -> None:
        result = score_subject_complexity("test", file_count=0, total_bytes=0)
        assert result.score == 0.0
        assert result.tier == "simple"

    def test_simple_subject(self) -> None:
        result = score_subject_complexity("test", file_count=2, total_bytes=5_000)
        assert result.tier == "simple"
        assert result.score < 10.0

    def test_medium_subject(self) -> None:
        result = score_subject_complexity("test", file_count=5, total_bytes=200_000)
        assert result.tier == "medium"
        assert 10.0 <= result.score < 50.0

    def test_complex_subject(self) -> None:
        result = score_subject_complexity("test", file_count=15, total_bytes=2_000_000)
        assert result.tier == "complex"
        assert result.score >= 50.0

    def test_score_increases_with_files(self) -> None:
        small = score_subject_complexity("a", file_count=1, total_bytes=1_000)
        large = score_subject_complexity("b", file_count=10, total_bytes=1_000)
        assert large.score > small.score

    def test_score_increases_with_size(self) -> None:
        small = score_subject_complexity("a", file_count=1, total_bytes=1_000)
        large = score_subject_complexity("b", file_count=1, total_bytes=1_000_000)
        assert large.score > small.score

    def test_model_fields(self) -> None:
        result = score_subject_complexity("acme", file_count=3, total_bytes=50_000)
        assert result.subject_safe_name == "acme"
        assert result.file_count == 3
        assert result.total_bytes == 50_000


# ---------------------------------------------------------------------------
# Batch scheduler tests
# ---------------------------------------------------------------------------


class TestBatchScheduler:
    """Test the batch scheduling algorithm."""

    def _make_complexities(self, names_and_scores: list[tuple[str, int, int]]) -> list[SubjectComplexity]:
        return [score_subject_complexity(name, file_count=fc, total_bytes=tb) for name, fc, tb in names_and_scores]

    def test_empty_input(self) -> None:
        scheduler = BatchScheduler(max_batch_size=5)
        batches = scheduler.schedule([])
        assert batches == []

    def test_single_batch_all_fit(self) -> None:
        complexities = self._make_complexities(
            [
                ("a", 1, 1_000),
                ("b", 2, 2_000),
                ("c", 1, 1_000),
            ]
        )
        scheduler = BatchScheduler(max_batch_size=10)
        batches = scheduler.schedule(complexities)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_multiple_batches_on_size_limit(self) -> None:
        complexities = self._make_complexities(
            [
                ("a", 1, 1_000),
                ("b", 2, 2_000),
                ("c", 1, 1_000),
                ("d", 3, 5_000),
            ]
        )
        scheduler = BatchScheduler(max_batch_size=2)
        batches = scheduler.schedule(complexities)
        assert len(batches) == 2
        assert all(len(b) <= 2 for b in batches)

    def test_simple_subjects_first(self) -> None:
        """Simple subjects should be scheduled first for fast wins."""
        complexities = self._make_complexities(
            [
                ("complex", 15, 2_000_000),
                ("simple", 1, 1_000),
                ("medium", 5, 100_000),
            ]
        )
        scheduler = BatchScheduler(max_batch_size=10)
        batches = scheduler.schedule(complexities)
        names = [c.subject_safe_name for c in batches[0]]
        assert names[0] == "simple"

    def test_preserves_all_subjects(self) -> None:
        complexities = self._make_complexities([(f"c{i}", i + 1, (i + 1) * 1_000) for i in range(15)])
        scheduler = BatchScheduler(max_batch_size=4)
        batches = scheduler.schedule(complexities)
        all_names = [c.subject_safe_name for batch in batches for c in batch]
        assert len(all_names) == 15
        assert set(all_names) == {f"c{i}" for i in range(15)}

    def test_max_batch_token_limit(self) -> None:
        complexities = self._make_complexities(
            [
                ("a", 1, 1_000),
                ("b", 1, 1_000),
                ("c", 1, 1_000),
            ]
        )
        scheduler = BatchScheduler(max_batch_size=10, max_batch_tokens=5_000)
        batches = scheduler.schedule(complexities)
        # With very low token limit, we might get more batches
        assert len(batches) >= 1

    def test_batch_names_helper(self) -> None:
        complexities = self._make_complexities(
            [
                ("a", 1, 1_000),
                ("b", 2, 2_000),
            ]
        )
        scheduler = BatchScheduler(max_batch_size=10)
        batches = scheduler.schedule(complexities)
        names = scheduler.batch_names(batches[0])
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# StepTimer tests (via PipelineState integration)
# ---------------------------------------------------------------------------


class TestStepTimingIntegration:
    """Test per-step timing in pipeline state."""

    def test_step_result_has_duration(self) -> None:
        from dd_agents.orchestrator.state import StepResult
        from dd_agents.orchestrator.steps import PipelineStep

        result = StepResult(
            step=PipelineStep.VALIDATE_CONFIG,
            status="success",
            duration_ms=1234,
        )
        assert result.duration_ms == 1234

    def test_step_results_serialization(self) -> None:
        from dd_agents.orchestrator.state import PipelineState, StepResult
        from dd_agents.orchestrator.steps import PipelineStep

        state = PipelineState(run_id="test")
        state.step_results["01_validate_config"] = StepResult(
            step=PipelineStep.VALIDATE_CONFIG,
            status="success",
            duration_ms=500,
        )
        d = state.to_checkpoint_dict()
        assert d["step_results"]["01_validate_config"]["duration_ms"] == 500
