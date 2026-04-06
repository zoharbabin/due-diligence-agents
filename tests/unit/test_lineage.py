"""Unit tests for cross-run finding lineage tracking (Issue #183)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge.lineage import (
    FindingLineageTracker,
    FindingStatus,
    compute_finding_fingerprint,
)


def _make_finding(
    *,
    title: str = "Missing clause",
    agent: str = "legal",
    category: str = "contract_risk",
    entity: str = "customer_a",
    severity: str = "high",
    source_path: str = "contracts/agreement.pdf",
    location: str = "5",
    description: str = "A clause is missing from the agreement.",
) -> dict[str, object]:
    """Build a minimal finding dict for testing."""
    return {
        "title": title,
        "agent": agent,
        "category": category,
        "analysis_unit": entity,
        "severity": severity,
        "description": description,
        "citations": [{"source_path": source_path, "location": location}],
    }


# ---- Fingerprinting tests ----


class TestFingerprinting:
    """Fingerprint stability and uniqueness."""

    def test_same_finding_same_fingerprint(self) -> None:
        f1 = _make_finding()
        f2 = _make_finding()
        assert compute_finding_fingerprint(f1) == compute_finding_fingerprint(f2)

    def test_different_findings_different_fingerprints(self) -> None:
        f1 = _make_finding(title="Missing clause")
        f2 = _make_finding(title="Revenue discrepancy", category="financial_risk")
        assert compute_finding_fingerprint(f1) != compute_finding_fingerprint(f2)

    def test_minor_title_variation_same_fingerprint(self) -> None:
        """Punctuation differences should not change the fingerprint."""
        f1 = _make_finding(title="Missing clause!")
        f2 = _make_finding(title="Missing clause")
        assert compute_finding_fingerprint(f1) == compute_finding_fingerprint(f2)

    def test_case_insensitive_title(self) -> None:
        f1 = _make_finding(title="Missing Clause")
        f2 = _make_finding(title="missing clause")
        assert compute_finding_fingerprint(f1) == compute_finding_fingerprint(f2)

    def test_different_entity_different_fingerprint(self) -> None:
        f1 = _make_finding(entity="customer_a")
        f2 = _make_finding(entity="customer_b")
        assert compute_finding_fingerprint(f1) != compute_finding_fingerprint(f2)

    def test_fingerprint_length(self) -> None:
        fp = compute_finding_fingerprint(_make_finding())
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_no_citations_fingerprint(self) -> None:
        finding = _make_finding()
        finding["citations"] = []
        fp = compute_finding_fingerprint(finding)
        assert len(fp) == 16  # still valid


# ---- Tracker lifecycle tests ----


class TestNewFinding:
    def test_new_finding_creates_lineage_entry(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        result = tracker.update_from_run("run_1", [_make_finding()])
        assert result.new_findings == 1
        assert result.updated_findings == 0
        assert result.resolved_findings == 0

    def test_new_finding_has_correct_fields(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        finding = _make_finding()
        tracker.update_from_run("run_1", [finding])

        fp = compute_finding_fingerprint(finding)
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.first_seen_run_id == "run_1"
        assert entry.last_seen_run_id == "run_1"
        assert entry.run_count == 1
        assert entry.current_severity == "high"
        assert entry.status == FindingStatus.ACTIVE
        assert entry.agent == "legal"
        assert entry.category == "contract_risk"


class TestUpdatedFinding:
    def test_updated_finding_increments_run_count(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        finding = _make_finding()
        tracker.update_from_run("run_1", [finding])
        result = tracker.update_from_run("run_2", [finding])

        assert result.updated_findings == 1
        assert result.new_findings == 0

        fp = compute_finding_fingerprint(finding)
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.run_count == 2
        assert entry.last_seen_run_id == "run_2"

    def test_updated_finding_updates_title_and_description(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding(description="Old description")])
        tracker.update_from_run("run_2", [_make_finding(description="New description")])

        fp = compute_finding_fingerprint(_make_finding())
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.latest_description == "New description"


class TestResolution:
    def test_absent_finding_marked_resolved(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding()])
        result = tracker.update_from_run("run_2", [])

        assert result.resolved_findings == 1
        fp = compute_finding_fingerprint(_make_finding())
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.status == FindingStatus.RESOLVED
        assert entry.resolution_run_id == "run_2"


class TestRecurrence:
    def test_recurred_finding_after_resolution(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        finding = _make_finding()
        tracker.update_from_run("run_1", [finding])
        tracker.update_from_run("run_2", [])  # resolved
        result = tracker.update_from_run("run_3", [finding])

        assert result.recurred_findings == 1
        fp = compute_finding_fingerprint(finding)
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.status == FindingStatus.RECURRED
        assert entry.recurrence_run_id == "run_3"
        assert entry.resolution_run_id is None  # cleared on recurrence
        assert entry.run_count == 2  # present in run_1 and run_3 (absent in run_2)


class TestSeverityChange:
    def test_severity_change_records_event(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding(severity="medium")])
        result = tracker.update_from_run("run_2", [_make_finding(severity="high")])

        assert result.severity_changes == 1
        fp = compute_finding_fingerprint(_make_finding())
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert entry.current_severity == "high"
        assert len(entry.severity_history) == 1
        assert entry.severity_history[0].old_severity == "medium"
        assert entry.severity_history[0].new_severity == "high"
        assert entry.severity_history[0].run_id == "run_2"


class TestPersistentFindings:
    def test_persistent_findings_filter_by_min_runs(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        finding = _make_finding()
        for i in range(5):
            tracker.update_from_run(f"run_{i + 1}", [finding])

        persistent = tracker.get_persistent_findings(min_runs=3)
        assert len(persistent) == 1
        assert persistent[0].run_count == 5

    def test_non_persistent_finding_excluded(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding()])
        tracker.update_from_run("run_2", [_make_finding()])

        persistent = tracker.get_persistent_findings(min_runs=3)
        assert len(persistent) == 0


class TestEntityLineage:
    def test_entity_lineage_filtering(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        f_a = _make_finding(entity="customer_a", title="Issue A")
        f_b = _make_finding(entity="customer_b", title="Issue B")
        tracker.update_from_run("run_1", [f_a, f_b])

        lineage_a = tracker.get_entity_lineage("customer_a")
        lineage_b = tracker.get_entity_lineage("customer_b")
        assert len(lineage_a) == 1
        assert len(lineage_b) == 1
        assert lineage_a[0].entity_safe_name == "customer_a"


class TestActiveResolved:
    def test_active_resolved_filtering(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        f1 = _make_finding(title="Issue one")
        f2 = _make_finding(title="Issue two", category="other")
        tracker.update_from_run("run_1", [f1, f2])
        tracker.update_from_run("run_2", [f1])  # f2 resolved

        active = tracker.get_active()
        resolved = tracker.get_resolved()
        assert len(active) == 1
        assert len(resolved) == 1
        assert active[0].latest_title == "Issue one"
        assert resolved[0].latest_title == "Issue two"


class TestEvolutionSummary:
    def test_summary_respects_char_limit(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        # Create 20 distinct findings all present in every run so the summary is long
        all_findings = [_make_finding(title=f"Finding number {i} " * 5, category=f"cat_{i}") for i in range(20)]
        for i in range(4):
            tracker.update_from_run(f"run_{i + 1}", all_findings)

        summary = tracker.generate_evolution_summary(max_chars=200)
        assert len(summary) <= 200
        assert summary.endswith("...")

    def test_empty_summary(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        summary = tracker.generate_evolution_summary()
        assert summary == "No finding lineage data available."


class TestSaveLoad:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "lineage.json"
        tracker = FindingLineageTracker(path)
        tracker.load()
        finding = _make_finding()
        tracker.update_from_run("run_1", [finding])
        tracker.save()

        tracker2 = FindingLineageTracker(path)
        tracker2.load()
        fp = compute_finding_fingerprint(finding)
        entry = tracker2.get_lineage(fp)
        assert entry is not None
        assert entry.first_seen_run_id == "run_1"
        assert entry.run_count == 1
        assert entry.status == FindingStatus.ACTIVE

    def test_corrupt_file_starts_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "lineage.json"
        path.write_text("{invalid json!!!", encoding="utf-8")
        tracker = FindingLineageTracker(path)
        tracker.load()
        assert tracker.get_active() == []


class TestEmptyLineage:
    def test_all_queries_return_empty(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        assert tracker.get_active() == []
        assert tracker.get_resolved() == []
        assert tracker.get_severity_changes() == []
        assert tracker.get_persistent_findings() == []
        assert tracker.get_entity_lineage("anything") == []
        assert tracker.get_lineage("nonexistent") is None


class TestUpdateWithEmptyFindings:
    def test_empty_findings_marks_all_resolved(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding(title="A"), _make_finding(title="B", category="other")])
        result = tracker.update_from_run("run_2", [])

        assert result.resolved_findings == 2
        assert len(tracker.get_resolved()) == 2
        assert len(tracker.get_active()) == 0


class TestDescriptionTruncation:
    def test_long_description_truncated_on_update(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        long_desc = "x" * 300
        tracker.update_from_run("run_1", [_make_finding(description=long_desc)])

        fp = compute_finding_fingerprint(_make_finding())
        entry = tracker.get_lineage(fp)
        assert entry is not None
        assert len(entry.latest_description) == 200


class TestSeverityChangesQuery:
    def test_get_severity_changes_since_run(self, tmp_path: Path) -> None:
        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        tracker.load()
        tracker.update_from_run("run_1", [_make_finding(severity="low")])
        tracker.update_from_run("run_2", [_make_finding(severity="medium")])
        tracker.update_from_run("run_3", [_make_finding(severity="high")])

        changes = tracker.get_severity_changes(since_run_id="run_3")
        assert len(changes) == 1
        changes_r2 = tracker.get_severity_changes(since_run_id="run_2")
        assert len(changes_r2) == 1
        all_changes = tracker.get_severity_changes()
        assert len(all_changes) == 1  # one finding with changes
