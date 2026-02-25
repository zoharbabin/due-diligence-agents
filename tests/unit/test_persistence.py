"""Unit tests for the persistence module: TierManager, RunManager, IncrementalClassifier."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.models.enums import CustomerClassificationStatus
from dd_agents.models.persistence import CustomerClassEntry
from dd_agents.persistence.incremental import IncrementalClassifier
from dd_agents.persistence.run_manager import RunManager
from dd_agents.persistence.tiers import VERSIONED_SUBDIRS, TierManager

if TYPE_CHECKING:
    from pathlib import Path

# =========================================================================
# TierManager
# =========================================================================


class TestTierManager:
    """Tests for the three-tier persistence lifecycle manager."""

    def test_ensure_dirs_creates_all_paths(self, tmp_path: Path) -> None:
        """ensure_dirs should create PERMANENT dirs and all VERSIONED sub-dirs."""
        mgr = TierManager(tmp_path)
        run_dir = mgr.ensure_dirs(tmp_path, "20260215_100000")

        # PERMANENT directories
        assert (tmp_path / "_dd" / "forensic-dd" / "index" / "text").is_dir()
        assert (tmp_path / "_dd" / "forensic-dd" / "runs").is_dir()
        assert (tmp_path / "_dd" / "forensic-dd" / "inventory").is_dir()

        # VERSIONED sub-directories
        for subdir in VERSIONED_SUBDIRS:
            assert (run_dir / subdir).is_dir(), f"Missing: {subdir}"

        # Inventory snapshot dir
        assert (run_dir / "inventory_snapshot").is_dir()

    def test_ensure_dirs_returns_correct_run_dir(self, tmp_path: Path) -> None:
        """ensure_dirs should return the correct run directory path."""
        mgr = TierManager(tmp_path)
        run_dir = mgr.ensure_dirs(tmp_path, "20260215_100000")
        expected = tmp_path / "_dd" / "forensic-dd" / "runs" / "20260215_100000"
        assert run_dir == expected

    def test_ensure_dirs_idempotent(self, tmp_path: Path) -> None:
        """Calling ensure_dirs twice should not raise or corrupt."""
        mgr = TierManager(tmp_path)
        mgr.ensure_dirs(tmp_path, "20260215_100000")
        mgr.ensure_dirs(tmp_path, "20260215_100000")
        assert (tmp_path / "_dd" / "forensic-dd" / "runs" / "20260215_100000").is_dir()

    def test_archive_versioned_snapshots_inventory(self, tmp_path: Path) -> None:
        """archive_versioned should copy inventory to the prior run's snapshot dir."""
        mgr = TierManager(tmp_path)
        # Set up a prior run with a latest symlink
        runs_dir = tmp_path / "_dd" / "forensic-dd" / "runs"
        prior_run_dir = runs_dir / "20260214_090000"
        prior_run_dir.mkdir(parents=True)
        latest_link = runs_dir / "latest"
        latest_link.symlink_to("20260214_090000")

        # Create inventory with content
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        (inv_dir / "tree.txt").write_text("sample tree")
        (inv_dir / "files.txt").write_text("file1.pdf\nfile2.docx\n")

        # Re-point inventory_dir
        mgr.inventory_dir = inv_dir

        # Archive
        new_run_dir = runs_dir / "20260215_100000"
        new_run_dir.mkdir(parents=True)
        mgr.archive_versioned(new_run_dir, runs_dir)

        snapshot = prior_run_dir / "inventory_snapshot"
        assert snapshot.is_dir()
        assert (snapshot / "tree.txt").read_text() == "sample tree"
        assert (snapshot / "files.txt").read_text() == "file1.pdf\nfile2.docx\n"

    def test_archive_versioned_no_latest_symlink(self, tmp_path: Path) -> None:
        """archive_versioned should be a no-op if there is no latest symlink."""
        mgr = TierManager(tmp_path)
        runs_dir = tmp_path / "_dd" / "forensic-dd" / "runs"
        runs_dir.mkdir(parents=True)

        new_run_dir = runs_dir / "20260215_100000"
        new_run_dir.mkdir()

        # Should not raise
        mgr.archive_versioned(new_run_dir, runs_dir)

    def test_archive_versioned_skips_if_snapshot_exists(self, tmp_path: Path) -> None:
        """archive_versioned should not overwrite an existing snapshot."""
        mgr = TierManager(tmp_path)
        runs_dir = tmp_path / "_dd" / "forensic-dd" / "runs"
        prior_dir = runs_dir / "20260214_090000"
        prior_dir.mkdir(parents=True)
        latest_link = runs_dir / "latest"
        latest_link.symlink_to("20260214_090000")

        # Pre-existing snapshot
        snapshot = prior_dir / "inventory_snapshot"
        snapshot.mkdir()
        (snapshot / "marker.txt").write_text("original")

        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        (inv_dir / "marker.txt").write_text("new content")
        mgr.inventory_dir = inv_dir

        new_run_dir = runs_dir / "20260215_100000"
        new_run_dir.mkdir()
        mgr.archive_versioned(new_run_dir, runs_dir)

        # Should still have original content
        assert (snapshot / "marker.txt").read_text() == "original"

    def test_wipe_fresh_clears_and_recreates(self, tmp_path: Path) -> None:
        """wipe_fresh should remove then recreate inventory directories."""
        mgr = TierManager(tmp_path)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        (inv_dir / "tree.txt").write_text("data")
        (inv_dir / "files.txt").write_text("data")

        mgr.wipe_fresh([inv_dir])

        assert inv_dir.is_dir()
        assert not (inv_dir / "tree.txt").exists()
        assert not (inv_dir / "files.txt").exists()

    def test_wipe_fresh_handles_nonexistent_dir(self, tmp_path: Path) -> None:
        """wipe_fresh should handle directories that don't exist yet."""
        mgr = TierManager(tmp_path)
        new_dir = tmp_path / "nonexistent"
        mgr.wipe_fresh([new_dir])
        assert new_dir.is_dir()


# =========================================================================
# RunManager
# =========================================================================


class TestRunManager:
    """Tests for run initialization and finalization."""

    def test_initialize_creates_run_id(self, tmp_path: Path) -> None:
        """initialize_run should produce a run_id with timestamp and random suffix."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)

        # run_id format: run_YYYYMMDD_HHMMSS_<6hex>  (Issue #63)
        assert meta.run_id.startswith("run_")
        parts = meta.run_id.split("_")
        assert len(parts) == 4
        assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
        assert parts[2].isdigit() and len(parts[2]) == 6  # HHMMSS
        assert len(parts[3]) == 6  # hex suffix

    def test_initialize_creates_directory_structure(self, tmp_path: Path) -> None:
        """initialize_run should create the full VERSIONED directory tree."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)

        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / meta.run_id
        assert run_dir.is_dir()

        # Check key sub-directories
        assert (run_dir / "findings" / "legal" / "gaps").is_dir()
        assert (run_dir / "findings" / "finance" / "gaps").is_dir()
        assert (run_dir / "findings" / "commercial" / "gaps").is_dir()
        assert (run_dir / "findings" / "producttech" / "gaps").is_dir()
        assert (run_dir / "findings" / "merged" / "gaps").is_dir()
        assert (run_dir / "judge").is_dir()
        assert (run_dir / "report").is_dir()
        assert (run_dir / "audit" / "legal").is_dir()
        assert (run_dir / "audit" / "judge").is_dir()
        assert (run_dir / "audit" / "reporting_lead").is_dir()

    def test_initialize_writes_initial_metadata(self, tmp_path: Path) -> None:
        """initialize_run should write metadata.json with in_progress status."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)

        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / meta.run_id
        meta_path = run_dir / "metadata.json"
        assert meta_path.exists()

        data = json.loads(meta_path.read_text())
        assert data["run_id"] == meta.run_id
        assert data["completion_status"] == "in_progress"
        assert data["skill"] == "forensic-dd"

    def test_initialize_wipes_fresh_tier(self, tmp_path: Path) -> None:
        """initialize_run should wipe the FRESH tier (inventory directory)."""
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        (inv_dir / "old_file.txt").write_text("stale data")

        mgr = RunManager(tmp_path)
        mgr.initialize_run(tmp_path)

        assert inv_dir.is_dir()
        assert not (inv_dir / "old_file.txt").exists()

    def test_initialize_with_deal_config(self, tmp_path: Path) -> None:
        """initialize_run should use deal_config for metadata fields."""
        config = {
            "execution": {"execution_mode": "incremental"},
            "target": {"name": "TestCorp"},
        }
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path, deal_config=config)

        assert meta.execution_mode == "incremental"
        assert meta.config_hash  # Should be non-empty

    def test_finalize_updates_history(self, tmp_path: Path) -> None:
        """finalize_run should append an entry to run_history.json."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)
        entry = mgr.finalize_run(meta)

        assert entry.run_id == meta.run_id
        assert entry.skill == "forensic-dd"

        history_path = tmp_path / "_dd" / "run_history.json"
        assert history_path.exists()
        history = json.loads(history_path.read_text())
        assert len(history) == 1
        assert history[0]["run_id"] == meta.run_id

    def test_finalize_creates_latest_symlink(self, tmp_path: Path) -> None:
        """finalize_run should create a 'latest' symlink pointing to the run."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)
        mgr.finalize_run(meta)

        latest = tmp_path / "_dd" / "forensic-dd" / "runs" / "latest"
        assert latest.is_symlink()
        target = latest.resolve().name
        assert target == meta.run_id

    def test_finalize_marks_metadata_completed(self, tmp_path: Path) -> None:
        """finalize_run should set completion_status to 'completed'."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)
        mgr.finalize_run(meta)

        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / meta.run_id
        data = json.loads((run_dir / "metadata.json").read_text())
        assert data["completion_status"] == "completed"

    def test_finalize_appends_to_existing_history(self, tmp_path: Path) -> None:
        """finalize_run should append, not overwrite, existing history entries."""
        # Create pre-existing history
        dd_dir = tmp_path / "_dd"
        dd_dir.mkdir(parents=True)
        history_path = dd_dir / "run_history.json"
        history_path.write_text(json.dumps([{"run_id": "old_run", "skill": "forensic-dd"}]))

        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)
        mgr.finalize_run(meta)

        history = json.loads(history_path.read_text())
        assert len(history) == 2
        assert history[0]["run_id"] == "old_run"
        assert history[1]["run_id"] == meta.run_id

    def test_get_prior_run_id(self, tmp_path: Path) -> None:
        """get_prior_run_id should return the latest run or None."""
        mgr = RunManager(tmp_path)
        assert mgr.get_prior_run_id() is None

        meta = mgr.initialize_run(tmp_path)
        mgr.finalize_run(meta)
        assert mgr.get_prior_run_id() == meta.run_id


# =========================================================================
# IncrementalClassifier
# =========================================================================


class TestIncrementalClassifier:
    """Tests for customer classification in incremental mode."""

    def test_new_customer(self) -> None:
        """Customers in current but not prior should be classified as NEW."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={"acme": ["hash1", "hash2"]},
            prior_files={},
            staleness_threshold=3,
        )
        assert len(result.customers) == 1
        assert result.customers[0].classification == CustomerClassificationStatus.NEW
        assert result.classification_summary.new == 1

    def test_deleted_customer(self) -> None:
        """Customers in prior but not current should be classified as DELETED."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={},
            prior_files={"acme": ["hash1"]},
            staleness_threshold=3,
        )
        assert len(result.customers) == 1
        assert result.customers[0].classification == CustomerClassificationStatus.DELETED
        assert result.classification_summary.deleted == 1

    def test_changed_customer(self) -> None:
        """Customers with different checksums should be classified as CHANGED."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={"acme": ["hash1", "hash3"]},
            prior_files={"acme": ["hash1", "hash2"]},
            staleness_threshold=3,
        )
        assert len(result.customers) == 1
        assert result.customers[0].classification == CustomerClassificationStatus.CHANGED
        assert result.classification_summary.changed == 1

    def test_unchanged_customer(self) -> None:
        """Customers with identical checksums and below threshold should be UNCHANGED."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={"acme": ["hash1", "hash2"]},
            prior_files={"acme": ["hash1", "hash2"]},
            staleness_threshold=3,
        )
        assert len(result.customers) == 1
        assert result.customers[0].classification == CustomerClassificationStatus.UNCHANGED
        assert result.customers[0].consecutive_unchanged_runs == 1
        assert result.classification_summary.unchanged == 1

    def test_stale_refresh_customer(self) -> None:
        """Customers unchanged for >= threshold runs should be STALE_REFRESH."""
        classifier = IncrementalClassifier()

        prior_entry = CustomerClassEntry(
            customer="acme",
            customer_safe_name="acme",
            classification=CustomerClassificationStatus.UNCHANGED,
            reason="",
            consecutive_unchanged_runs=2,
        )

        result = classifier.classify_customers(
            current_files={"acme": ["hash1"]},
            prior_files={"acme": ["hash1"]},
            staleness_threshold=3,
            prior_classifications={"acme": prior_entry},
        )

        assert len(result.customers) == 1
        assert result.customers[0].classification == CustomerClassificationStatus.STALE_REFRESH
        assert result.customers[0].consecutive_unchanged_runs == 3
        assert result.classification_summary.stale_refresh == 1

    def test_mixed_classification(self) -> None:
        """Classify a mix of customers correctly."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={
                "acme": ["h1"],
                "globex": ["h2", "h3"],
                "new_corp": ["h4"],
            },
            prior_files={
                "acme": ["h1"],
                "globex": ["h2", "hX"],
                "old_corp": ["h5"],
            },
            staleness_threshold=5,
        )

        summary = result.classification_summary
        assert summary.unchanged == 1  # acme
        assert summary.changed == 1  # globex
        assert summary.new == 1  # new_corp
        assert summary.deleted == 1  # old_corp
        assert len(result.customers) == 4

    def test_carry_forward_findings(self, tmp_path: Path) -> None:
        """carry_forward_findings should copy findings with _carried_forward metadata."""
        classifier = IncrementalClassifier()

        # Set up prior findings
        prior = tmp_path / "prior" / "findings"
        legal_dir = prior / "legal"
        legal_dir.mkdir(parents=True)
        (legal_dir / "acme.json").write_text(
            json.dumps(
                {
                    "customer": "acme",
                    "findings": [{"id": "f1"}],
                }
            )
        )

        # Also set up a gap file
        gaps_dir = legal_dir / "gaps"
        gaps_dir.mkdir()
        (gaps_dir / "acme.json").write_text(
            json.dumps(
                [
                    {"gap_type": "Missing_Doc", "customer": "acme"},
                ]
            )
        )

        # Set up current findings dir
        current = tmp_path / "current" / "findings"
        current.mkdir(parents=True)

        carried = classifier.carry_forward_findings(
            unchanged_customers=["acme"],
            prior_findings_dir=prior,
            current_findings_dir=current,
        )

        assert carried == 1
        target = current / "legal" / "acme.json"
        assert target.exists()
        data = json.loads(target.read_text())
        assert data["_carried_forward"] is True
        assert data["_carried_from_run"] == "prior"

        # Gap should also be carried forward
        gap_target = current / "legal" / "gaps" / "acme.json"
        assert gap_target.exists()
        gap_data = json.loads(gap_target.read_text())
        assert gap_data[0]["_carried_forward"] is True

    def test_carry_forward_no_prior_findings(self, tmp_path: Path) -> None:
        """carry_forward_findings should handle missing prior findings gracefully."""
        classifier = IncrementalClassifier()
        prior = tmp_path / "prior" / "findings"
        prior.mkdir(parents=True)
        current = tmp_path / "current" / "findings"
        current.mkdir(parents=True)

        carried = classifier.carry_forward_findings(
            unchanged_customers=["nonexistent"],
            prior_findings_dir=prior,
            current_findings_dir=current,
        )
        assert carried == 0

    def test_classification_execution_mode(self) -> None:
        """Classification document should have execution_mode 'incremental'."""
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={"a": ["h1"]},
            prior_files={},
            staleness_threshold=3,
        )
        assert result.execution_mode == "incremental"

    def test_files_modified_detected_correctly(self) -> None:
        """files_modified should use filename-based comparison, not index-based.

        Regression (Issue #66): the old code used ``list.index()`` which
        compared positions instead of content, and returned [] when list
        lengths differed.
        """
        classifier = IncrementalClassifier()
        # Common files: file_a.pdf, file_b.pdf.
        # file_c.pdf added, file_d.pdf removed.
        result = classifier.classify_customers(
            current_files={"acme": ["file_a.pdf", "file_b.pdf", "file_c.pdf"]},
            prior_files={"acme": ["file_a.pdf", "file_b.pdf", "file_d.pdf"]},
            staleness_threshold=3,
        )
        entry = result.customers[0]
        assert entry.classification == CustomerClassificationStatus.CHANGED
        assert "file_c.pdf" in entry.files_added
        assert "file_d.pdf" in entry.files_removed
        # Common files (file_a, file_b) should appear as potentially modified.
        assert "file_a.pdf" in entry.files_modified
        assert "file_b.pdf" in entry.files_modified

    def test_files_modified_with_different_list_lengths(self) -> None:
        """files_modified should work even when current and prior have different lengths.

        Regression (Issue #66): old code returned [] when len(current) != len(prior).
        """
        classifier = IncrementalClassifier()
        result = classifier.classify_customers(
            current_files={"acme": ["file_a.pdf", "file_b.pdf", "file_c.pdf"]},
            prior_files={"acme": ["file_a.pdf", "file_b.pdf"]},
            staleness_threshold=3,
        )
        entry = result.customers[0]
        assert entry.classification == CustomerClassificationStatus.CHANGED
        assert "file_c.pdf" in entry.files_added
        # Common files still detected
        assert "file_a.pdf" in entry.files_modified
        assert "file_b.pdf" in entry.files_modified


# =========================================================================
# Issue #62: archive_versioned with empty inventory_snapshot
# =========================================================================


class TestArchiveVersionedEmptySnapshot:
    """Test that archiving works even when inventory_snapshot is an empty placeholder."""

    def test_archive_versioned_overwrites_empty_snapshot(self, tmp_path: Path) -> None:
        """archive_versioned should archive even if an empty inventory_snapshot exists.

        Regression (Issue #62): ensure_run_dirs creates an empty
        inventory_snapshot dir, which caused archive_versioned to skip
        archiving because ``snapshot_dir.exists()`` was True.
        """
        mgr = TierManager(tmp_path)
        runs_dir = tmp_path / "_dd" / "forensic-dd" / "runs"
        prior_dir = runs_dir / "20260214_090000"
        prior_dir.mkdir(parents=True)
        latest_link = runs_dir / "latest"
        latest_link.symlink_to("20260214_090000")

        # Create the empty placeholder (as ensure_run_dirs would)
        snapshot = prior_dir / "inventory_snapshot"
        snapshot.mkdir(parents=True)
        assert not any(snapshot.iterdir())  # empty

        # Create inventory with content
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        (inv_dir / "tree.txt").write_text("tree data")
        mgr.inventory_dir = inv_dir

        new_run_dir = runs_dir / "20260215_100000"
        new_run_dir.mkdir()
        mgr.archive_versioned(new_run_dir, runs_dir)

        # Snapshot should now have content
        assert (snapshot / "tree.txt").exists()
        assert (snapshot / "tree.txt").read_text() == "tree data"


# =========================================================================
# Issue #63: RunManager run_id collision and atomic writes
# =========================================================================


class TestRunManagerCollisionAndAtomicWrites:
    """Tests for run_id uniqueness and atomic file writes."""

    def test_run_id_has_random_suffix(self, tmp_path: Path) -> None:
        """run_id should contain a random suffix to prevent collisions.

        Regression (Issue #63): old format was just YYYYMMDD_HHMMSS which
        could collide if two runs started in the same second.
        """
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)

        # New format: run_YYYYMMDD_HHMMSS_<6hex>
        assert meta.run_id.startswith("run_")
        parts = meta.run_id.split("_")
        assert len(parts) == 4  # run, YYYYMMDD, HHMMSS, hex
        assert len(parts[3]) == 6  # 6-char hex suffix

    def test_consecutive_run_ids_differ(self, tmp_path: Path) -> None:
        """Two consecutive initializations should produce different run_ids."""
        mgr1 = RunManager(tmp_path)
        meta1 = mgr1.initialize_run(tmp_path)

        mgr2 = RunManager(tmp_path)
        meta2 = mgr2.initialize_run(tmp_path)

        assert meta1.run_id != meta2.run_id

    def test_atomic_write_metadata(self, tmp_path: Path) -> None:
        """metadata.json should be written atomically (no .tmp residue)."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)

        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / meta.run_id
        # metadata.json exists
        assert (run_dir / "metadata.json").exists()
        # No .tmp file left behind
        assert not (run_dir / "metadata.tmp").exists()

    def test_atomic_write_history(self, tmp_path: Path) -> None:
        """run_history.json should be written atomically (no .tmp residue)."""
        mgr = RunManager(tmp_path)
        meta = mgr.initialize_run(tmp_path)
        mgr.finalize_run(meta)

        history_path = tmp_path / "_dd" / "run_history.json"
        assert history_path.exists()
        assert not history_path.with_suffix(".tmp").exists()
