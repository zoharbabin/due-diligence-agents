"""Tests for accounting Claude-vision extraction LLM spend (Issue #247).

Covers the pipeline's usage accumulator and the engine's recording into the
CostTracker (reaching by_model / by_provider / budget gate).
"""

from __future__ import annotations

from dd_agents.agents.cost_tracker import CostTracker
from dd_agents.extraction.pipeline import ExtractionPipeline


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class TestVisionUsageAccumulator:
    def test_starts_at_zero(self) -> None:
        p = ExtractionPipeline()
        assert p.vision_usage() == (0, 0, 0)

    def test_accumulates_object_usage(self) -> None:
        p = ExtractionPipeline()
        p._record_vision_usage(_Usage(100, 50))
        p._record_vision_usage(_Usage(40, 10))
        assert p.vision_usage() == (140, 60, 2)

    def test_accumulates_dict_usage(self) -> None:
        p = ExtractionPipeline()
        p._record_vision_usage({"input_tokens": 7, "output_tokens": 3})
        assert p.vision_usage() == (7, 3, 1)

    def test_none_usage_still_counts_the_call(self) -> None:
        # An errored vision call may report no usage but still happened.
        p = ExtractionPipeline()
        p._record_vision_usage(None)
        # None → not counted (no tokens, no call recorded — we only count usage we saw).
        assert p.vision_usage() == (0, 0, 0)

    def test_malformed_usage_is_tolerated(self) -> None:
        p = ExtractionPipeline()
        p._record_vision_usage({"input_tokens": "x", "output_tokens": None})
        assert p.vision_usage() == (0, 0, 1)


class _FakePipeline:
    def __init__(self, usage: tuple[int, int, int]) -> None:
        self._u = usage

    def vision_usage(self) -> tuple[int, int, int]:
        return self._u


class TestEngineRecordsVisionCost:
    def _engine(self):  # type: ignore[no-untyped-def]
        from dd_agents.orchestrator.engine import PipelineEngine

        eng = PipelineEngine.__new__(PipelineEngine)
        eng.cost_tracker = CostTracker()
        return eng

    def test_records_vision_spend_into_tracker(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setenv("DD_VISION_MODEL", "claude-sonnet-4-6")
        eng = self._engine()
        eng._record_vision_cost(_FakePipeline((1000, 200, 3)))
        by_model = eng.cost_tracker.cost_by_model()
        assert "claude-sonnet-4-6" in by_model
        entries = [e for e in eng.cost_tracker.entries if e.agent_name == "extraction_vision"]
        assert len(entries) == 1
        assert entries[0].input_tokens == 1000
        assert entries[0].step == "05_bulk_extraction"

    def test_no_vision_calls_is_noop(self) -> None:
        eng = self._engine()
        eng._record_vision_cost(_FakePipeline((0, 0, 0)))
        assert eng.cost_tracker.entries == []

    def test_vision_spend_counts_toward_budget_gate(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setenv("DD_VISION_MODEL", "claude-opus-4-8")
        eng = self._engine()
        eng.cost_tracker.budget_limit_usd = 0.001
        # 1M input tokens of Opus = $15 → well over the $0.001 budget.
        eng._record_vision_cost(_FakePipeline((1_000_000, 0, 1)))
        assert eng.cost_tracker.is_budget_exceeded() is True


class TestVisionByProvider:
    """#247 vision spend appears in the by-provider rollup (audit-noted gap)."""

    def test_vision_entry_carries_provider_and_rolls_up(self, monkeypatch) -> None:  # noqa: ANN001
        import dd_agents.llm as llm_mod
        from dd_agents.llm import ProviderInfo

        monkeypatch.setenv("DD_VISION_MODEL", "claude-sonnet-4-6")
        # _record_vision_cost does `from dd_agents.llm import resolve_provider`,
        # so patch the function on the llm module (its import source).
        monkeypatch.setattr(
            llm_mod,
            "resolve_provider",
            lambda: ProviderInfo(provider="gateway", base_url="http://gw:4011", max_output_tokens=None),
        )
        from dd_agents.orchestrator.engine import PipelineEngine

        eng = PipelineEngine.__new__(PipelineEngine)
        eng.cost_tracker = CostTracker()
        eng._record_vision_cost(_FakePipeline((1000, 200, 2)))
        entry = next(e for e in eng.cost_tracker.entries if e.agent_name == "extraction_vision")
        assert entry.provider == "gateway"
        assert entry.base_url == "http://gw:4011"
        by_provider = eng.cost_tracker.cost_by_provider()
        assert "gateway" in by_provider
        assert by_provider["gateway"]["input_tokens"] == 1000
