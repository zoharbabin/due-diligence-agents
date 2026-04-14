"""Unit tests for the Analysis Chronicle (Issue #180)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge._utils import now_iso
from dd_agents.knowledge.chronicle import (
    AnalysisChronicle,
    AnalysisLogEntry,
    FindingsSummary,
    InteractionType,
    _generate_entry_id,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def log_path(tmp_path: Path) -> Path:
    """Return a path for the JSONL log file."""
    return tmp_path / "chronicle.jsonl"


@pytest.fixture()
def chronicle(log_path: Path) -> AnalysisChronicle:
    """Return a fresh AnalysisChronicle instance."""
    return AnalysisChronicle(log_path)


def _make_entry(
    interaction_type: InteractionType = InteractionType.PIPELINE_RUN,
    title: str = "Full pipeline run",
    entities: list[str] | None = None,
    findings_total: int | None = None,
    duration: float | None = None,
    cost: float | None = None,
    timestamp: str | None = None,
) -> AnalysisLogEntry:
    """Helper to create a test log entry."""
    findings = None
    if findings_total is not None:
        findings = FindingsSummary(total=findings_total, p0=1, p1=2)
    return AnalysisLogEntry(
        id=_generate_entry_id(),
        timestamp=timestamp or now_iso(),
        interaction_type=interaction_type,
        title=title,
        details={"scope": "full"},
        findings_summary=findings,
        entities_affected=entities or [],
        duration_seconds=duration,
        cost_usd=cost,
        user_initiated=False,
    )


# ---------------------------------------------------------------------------
# InteractionType enum
# ---------------------------------------------------------------------------


class TestInteractionType:
    """Tests for the InteractionType StrEnum."""

    def test_values(self) -> None:
        assert InteractionType.PIPELINE_RUN == "pipeline_run"
        assert InteractionType.SEARCH == "search"
        assert InteractionType.QUERY == "query"
        assert InteractionType.ANNOTATION == "annotation"
        assert InteractionType.KNOWLEDGE_COMPILATION == "knowledge_compilation"

    def test_member_count(self) -> None:
        assert len(InteractionType) == 6


# ---------------------------------------------------------------------------
# FindingsSummary model
# ---------------------------------------------------------------------------


class TestFindingsSummary:
    """Tests for FindingsSummary Pydantic model."""

    def test_defaults(self) -> None:
        fs = FindingsSummary(total=10)
        assert fs.total == 10
        assert fs.p0 == 0
        assert fs.p1 == 0
        assert fs.p2 == 0
        assert fs.p3 == 0
        assert fs.new_since_last == 0

    def test_all_fields(self) -> None:
        fs = FindingsSummary(total=50, p0=5, p1=10, p2=15, p3=20, new_since_last=8)
        assert fs.total == 50
        assert fs.p0 == 5
        assert fs.new_since_last == 8

    def test_round_trip(self) -> None:
        fs = FindingsSummary(total=3, p0=1, p1=2)
        data = fs.model_dump()
        restored = FindingsSummary.model_validate(data)
        assert restored == fs


# ---------------------------------------------------------------------------
# AnalysisLogEntry model
# ---------------------------------------------------------------------------


class TestAnalysisLogEntry:
    """Tests for AnalysisLogEntry Pydantic model."""

    def test_all_fields(self) -> None:
        entry = _make_entry(
            entities=["entity_a", "entity_b"],
            findings_total=25,
            duration=120.5,
            cost=0.45,
        )
        assert len(entry.id) == 12
        assert entry.interaction_type == InteractionType.PIPELINE_RUN
        assert entry.title == "Full pipeline run"
        assert entry.findings_summary is not None
        assert entry.findings_summary.total == 25
        assert entry.entities_affected == ["entity_a", "entity_b"]
        assert entry.duration_seconds == 120.5
        assert entry.cost_usd == 0.45
        assert entry.user_initiated is False

    def test_title_max_length(self) -> None:
        """Title is capped at 200 chars."""
        with pytest.raises(ValueError):
            AnalysisLogEntry(
                id="abc",
                timestamp=now_iso(),
                interaction_type=InteractionType.SEARCH,
                title="x" * 201,
            )

    def test_json_round_trip(self) -> None:
        entry = _make_entry(entities=["e1"], findings_total=5)
        json_str = entry.model_dump_json()
        restored = AnalysisLogEntry.model_validate_json(json_str)
        assert restored.id == entry.id
        assert restored.findings_summary is not None
        assert restored.findings_summary.total == 5

    def test_optional_fields_none(self) -> None:
        entry = _make_entry()
        assert entry.findings_summary is None
        assert entry.duration_seconds is None
        assert entry.cost_usd is None


# ---------------------------------------------------------------------------
# AnalysisChronicle — append and read
# ---------------------------------------------------------------------------


class TestChronicleAppendRead:
    """Tests for append and read round-trip."""

    def test_append_and_read_round_trip(self, chronicle: AnalysisChronicle) -> None:
        entry = _make_entry(title="Run A", entities=["e1"])
        chronicle.append(entry)
        results = chronicle.read_recent()
        assert len(results) == 1
        assert results[0].id == entry.id
        assert results[0].title == "Run A"

    def test_multiple_appends_preserve_order(self, chronicle: AnalysisChronicle) -> None:
        entries = [_make_entry(title=f"Run {i}") for i in range(5)]
        for e in entries:
            chronicle.append(e)
        results = chronicle.read_recent()
        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.title == f"Run {i}"

    def test_read_recent_with_limit(self, chronicle: AnalysisChronicle) -> None:
        for i in range(10):
            chronicle.append(_make_entry(title=f"Run {i}"))
        results = chronicle.read_recent(limit=3)
        assert len(results) == 3
        assert results[0].title == "Run 7"
        assert results[2].title == "Run 9"


# ---------------------------------------------------------------------------
# AnalysisChronicle — filtering
# ---------------------------------------------------------------------------


class TestChronicleFiltering:
    """Tests for read_by_type and read_for_entity."""

    def test_read_by_type(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(_make_entry(interaction_type=InteractionType.PIPELINE_RUN))
        chronicle.append(_make_entry(interaction_type=InteractionType.SEARCH, title="Search"))
        chronicle.append(_make_entry(interaction_type=InteractionType.PIPELINE_RUN))
        results = chronicle.read_by_type(InteractionType.PIPELINE_RUN)
        assert len(results) == 2

    def test_read_by_type_empty(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(_make_entry(interaction_type=InteractionType.SEARCH, title="S"))
        results = chronicle.read_by_type(InteractionType.ANNOTATION)
        assert len(results) == 0

    def test_read_for_entity(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(_make_entry(entities=["alpha", "beta"]))
        chronicle.append(_make_entry(entities=["gamma"]))
        chronicle.append(_make_entry(entities=["alpha"]))
        results = chronicle.read_for_entity("alpha")
        assert len(results) == 2

    def test_read_for_entity_no_match(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(_make_entry(entities=["alpha"]))
        results = chronicle.read_for_entity("omega")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# AnalysisChronicle — empty log
# ---------------------------------------------------------------------------


class TestChronicleEmpty:
    """Tests for behaviour on an empty/non-existent log file."""

    def test_read_recent_empty(self, chronicle: AnalysisChronicle) -> None:
        assert chronicle.read_recent() == []

    def test_read_by_type_empty(self, chronicle: AnalysisChronicle) -> None:
        assert chronicle.read_by_type(InteractionType.SEARCH) == []

    def test_read_for_entity_empty(self, chronicle: AnalysisChronicle) -> None:
        assert chronicle.read_for_entity("alpha") == []

    def test_timeline_summary_empty(self, chronicle: AnalysisChronicle) -> None:
        result = chronicle.generate_timeline_summary()
        assert result == "No analysis history recorded."

    def test_stats_empty(self, chronicle: AnalysisChronicle) -> None:
        stats = chronicle.get_stats()
        assert stats["total_entries"] == 0
        assert stats["by_type"] == {}
        assert stats["date_range"] == {"earliest": None, "latest": None}
        assert stats["entity_coverage"] == []


# ---------------------------------------------------------------------------
# AnalysisChronicle — corrupt line handling
# ---------------------------------------------------------------------------


class TestChronicleCorruptLines:
    """Tests for handling corrupt JSONL lines."""

    def test_skip_corrupt_lines(self, log_path: Path, chronicle: AnalysisChronicle) -> None:
        entry = _make_entry(title="Good entry")
        chronicle.append(entry)

        # Manually inject a corrupt line
        content = log_path.read_text(encoding="utf-8")
        content += "THIS IS NOT JSON\n"
        log_path.write_text(content, encoding="utf-8")

        # Append another good entry
        entry2 = _make_entry(title="Another good entry")
        chronicle.append(entry2)

        results = chronicle.read_recent()
        assert len(results) == 2
        assert results[0].title == "Good entry"
        assert results[1].title == "Another good entry"

    def test_all_corrupt_returns_empty(self, log_path: Path, chronicle: AnalysisChronicle) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("bad line 1\nbad line 2\n", encoding="utf-8")
        results = chronicle.read_recent()
        assert len(results) == 0


# ---------------------------------------------------------------------------
# AnalysisChronicle — timeline summary
# ---------------------------------------------------------------------------


class TestTimelineSummary:
    """Tests for generate_timeline_summary."""

    def test_format(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(
            _make_entry(
                title="Full pipeline run",
                timestamp="2026-03-07T14:30:00+00:00",
                findings_total=25,
                entities=["e1", "e2"],
                duration=120.0,
            )
        )
        result = chronicle.generate_timeline_summary()
        assert "[2026-03-07 14:30]" in result
        assert "Full pipeline run" in result
        assert "25 findings" in result
        assert "2 entities" in result
        assert "120s" in result

    def test_char_limit(self, chronicle: AnalysisChronicle) -> None:
        for i in range(100):
            chronicle.append(
                _make_entry(
                    title=f"Run number {i:03d} with a reasonably long title",
                    timestamp=f"2026-03-{(i % 28) + 1:02d}T10:00:00+00:00",
                )
            )
        result = chronicle.generate_timeline_summary(max_chars=500)
        assert len(result) <= 500

    def test_single_entry_no_truncation(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(_make_entry(title="Short", timestamp="2026-01-01T00:00:00+00:00"))
        result = chronicle.generate_timeline_summary(max_chars=5000)
        assert "... (earlier entries truncated)" not in result


# ---------------------------------------------------------------------------
# AnalysisChronicle — stats
# ---------------------------------------------------------------------------


class TestChronicleStats:
    """Tests for get_stats."""

    def test_stats_computation(self, chronicle: AnalysisChronicle) -> None:
        chronicle.append(
            _make_entry(
                interaction_type=InteractionType.PIPELINE_RUN,
                entities=["alpha"],
                timestamp="2026-01-01T00:00:00+00:00",
            )
        )
        chronicle.append(
            _make_entry(
                interaction_type=InteractionType.SEARCH,
                title="Search",
                entities=["beta"],
                timestamp="2026-02-01T00:00:00+00:00",
            )
        )
        chronicle.append(
            _make_entry(
                interaction_type=InteractionType.PIPELINE_RUN,
                entities=["alpha", "gamma"],
                timestamp="2026-03-01T00:00:00+00:00",
            )
        )

        stats = chronicle.get_stats()
        assert stats["total_entries"] == 3
        assert stats["by_type"]["pipeline_run"] == 2
        assert stats["by_type"]["search"] == 1
        assert stats["date_range"]["earliest"] == "2026-01-01T00:00:00+00:00"
        assert stats["date_range"]["latest"] == "2026-03-01T00:00:00+00:00"
        assert sorted(stats["entity_coverage"]) == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_generate_entry_id_length(self) -> None:
        entry_id = _generate_entry_id()
        assert len(entry_id) == 12
        assert entry_id.isalnum()

    def test_generate_entry_id_unique(self) -> None:
        ids = {_generate_entry_id() for _ in range(100)}
        assert len(ids) == 100

    def test_now_iso_format(self) -> None:
        ts = now_iso()
        assert "T" in ts
        assert "+" in ts or "Z" in ts or ts.endswith("+00:00")


# ---------------------------------------------------------------------------
# Error path tests (U4)
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_read_corrupt_jsonl_skips_bad_lines(self, chronicle: AnalysisChronicle) -> None:
        """Corrupt lines in the JSONL should be skipped, not crash."""
        # Write a valid entry, then corrupt the file
        entry = _make_entry(title="Valid Entry")
        chronicle.append(entry)

        # Append a corrupt line manually
        with chronicle.log_path.open("a", encoding="utf-8") as f:
            f.write("{INVALID JSON}\n")

        # Append another valid entry
        entry2 = _make_entry(title="After Corrupt")
        chronicle.append(entry2)

        entries = chronicle.read_recent(limit=100)
        titles = [e.title for e in entries]
        assert "Valid Entry" in titles
        assert "After Corrupt" in titles
        # Corrupt line was skipped
        assert len(entries) == 2

    def test_read_empty_file(self, tmp_path: Path) -> None:
        """Empty JSONL file should return no entries."""
        log_path = tmp_path / "empty.jsonl"
        log_path.write_text("", encoding="utf-8")
        chronicle = AnalysisChronicle(log_path)
        assert chronicle.read_recent() == []

    def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file should return no entries."""
        chronicle = AnalysisChronicle(tmp_path / "missing.jsonl")
        assert chronicle.read_recent() == []
        assert chronicle.get_stats()["total_entries"] == 0
