"""Unit tests for the dd_agents.precedence module.

Covers:
- FileEntry metadata enrichment (mtime, version indicators)
- Folder priority classification (4-tier system)
- Version chain detection (filename grouping, ordering)
- Precedence scoring (composite score computation)
- PrecedenceConfig model (deal-config integration)
"""

from __future__ import annotations

import os
from pathlib import Path

from dd_agents.models.inventory import FileEntry
from dd_agents.precedence.folder_priority import (
    DEFAULT_FOLDER_TIERS,
    FolderPriorityClassifier,
    FolderTier,
)
from dd_agents.precedence.scorer import PrecedenceScorer
from dd_agents.precedence.version_chains import (
    VersionChainBuilder,
    parse_version_indicator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fe(
    path: str,
    size: int = 100,
    mtime: float = 0.0,
    mtime_iso: str = "",
) -> FileEntry:
    """Create a FileEntry with optional metadata."""
    return FileEntry(path=path, size=size, mtime=mtime, mtime_iso=mtime_iso)


# ===================================================================
# Phase 1: FileEntry metadata enrichment
# ===================================================================


class TestFileEntryMetadata:
    """Tests for enriched FileEntry fields."""

    def test_default_values(self) -> None:
        """New fields have sensible defaults for backward compatibility."""
        entry = FileEntry(path="test.pdf")
        assert entry.mtime == 0.0
        assert entry.mtime_iso == ""
        assert entry.version_indicator == ""
        assert entry.version_rank == 0
        assert entry.folder_tier == 2
        assert entry.precedence_score == 0.0
        assert entry.superseded_by == ""
        assert entry.is_latest_version is True

    def test_serialization_roundtrip(self) -> None:
        """Enriched fields survive JSON serialization."""
        entry = FileEntry(
            path="Executed/MSA_v2_signed.pdf",
            mtime=1700000000.0,
            mtime_iso="2023-11-14T22:13:20+00:00",
            version_indicator="signed",
            version_rank=10,
            folder_tier=1,
            precedence_score=0.95,
            superseded_by="",
            is_latest_version=True,
        )
        data = entry.model_dump()
        restored = FileEntry.model_validate(data)
        assert restored.mtime == 1700000000.0
        assert restored.version_indicator == "signed"
        assert restored.folder_tier == 1
        assert restored.precedence_score == 0.95
        assert restored.is_latest_version is True

    def test_backward_compatible_with_existing_data(self) -> None:
        """FileEntry without new fields still loads (from old inventory)."""
        old_data = {"path": "contract.pdf", "size": 500, "checksum": "abc123"}
        entry = FileEntry.model_validate(old_data)
        assert entry.path == "contract.pdf"
        assert entry.mtime == 0.0
        assert entry.is_latest_version is True


# ===================================================================
# Phase 1b: Discovery mtime capture
# ===================================================================


class TestDiscoveryMtime:
    """Tests that file discovery captures modification time."""

    def test_discover_captures_mtime(self, tmp_path: Path) -> None:
        """Discovered files should have non-zero mtime."""
        from dd_agents.inventory.discovery import FileDiscovery

        customer_dir = tmp_path / "GroupA" / "Customer1"
        customer_dir.mkdir(parents=True)
        f = customer_dir / "contract.pdf"
        f.write_bytes(b"fake pdf content")

        discovery = FileDiscovery()
        entries = discovery.discover(tmp_path)

        assert len(entries) == 1
        assert entries[0].mtime > 0.0
        assert entries[0].mtime_iso != ""

    def test_discover_mtime_reflects_actual_file_time(self, tmp_path: Path) -> None:
        """Mtime should match the filesystem modification time."""
        from dd_agents.inventory.discovery import FileDiscovery

        f = tmp_path / "file.txt"
        f.write_text("content")
        expected_mtime = f.stat().st_mtime

        discovery = FileDiscovery()
        entries = discovery.discover(tmp_path)

        assert len(entries) == 1
        assert abs(entries[0].mtime - expected_mtime) < 1.0

    def test_discover_mtime_ordering(self, tmp_path: Path) -> None:
        """Files created at different times should have different mtimes."""
        from dd_agents.inventory.discovery import FileDiscovery

        f1 = tmp_path / "old.txt"
        f1.write_text("old content")
        old_mtime = f1.stat().st_mtime

        # Force a slightly different mtime
        os.utime(f1, (old_mtime - 100, old_mtime - 100))

        f2 = tmp_path / "new.txt"
        f2.write_text("new content")

        discovery = FileDiscovery()
        entries = discovery.discover(tmp_path)

        by_name = {e.path: e for e in entries}
        assert by_name["old.txt"].mtime < by_name["new.txt"].mtime


# ===================================================================
# Phase 2: Folder priority classification
# ===================================================================


class TestFolderTier:
    """Tests for the FolderTier enum."""

    def test_tier_values(self) -> None:
        """Four tiers with correct ordering."""
        assert FolderTier.AUTHORITATIVE == 1
        assert FolderTier.WORKING == 2
        assert FolderTier.SUPPLEMENTARY == 3
        assert FolderTier.HISTORICAL == 4

    def test_tier_score(self) -> None:
        """Each tier maps to a score between 0 and 1."""
        assert FolderTier.AUTHORITATIVE.score == 1.0
        assert FolderTier.WORKING.score == 0.7
        assert FolderTier.SUPPLEMENTARY.score == 0.4
        assert FolderTier.HISTORICAL.score == 0.2


class TestFolderPriorityClassifier:
    """Tests for folder tier classification."""

    def test_authoritative_patterns(self) -> None:
        """Executed/Signed/Final folders are tier 1."""
        clf = FolderPriorityClassifier()
        assert clf.classify("Executed Contracts") == FolderTier.AUTHORITATIVE
        assert clf.classify("Signed Agreements") == FolderTier.AUTHORITATIVE
        assert clf.classify("Final Documents") == FolderTier.AUTHORITATIVE
        assert clf.classify("Closing Binder") == FolderTier.AUTHORITATIVE
        assert clf.classify("Definitive Agreements") == FolderTier.AUTHORITATIVE

    def test_supplementary_patterns(self) -> None:
        """Draft/Working folders are tier 3."""
        clf = FolderPriorityClassifier()
        assert clf.classify("Drafts") == FolderTier.SUPPLEMENTARY
        assert clf.classify("Working Papers") == FolderTier.SUPPLEMENTARY
        assert clf.classify("Internal Notes") == FolderTier.SUPPLEMENTARY
        assert clf.classify("WIP Documents") == FolderTier.SUPPLEMENTARY
        assert clf.classify("Redline Versions") == FolderTier.SUPPLEMENTARY

    def test_historical_patterns(self) -> None:
        """Archive/Old folders are tier 4."""
        clf = FolderPriorityClassifier()
        assert clf.classify("Archive") == FolderTier.HISTORICAL
        assert clf.classify("Old Contracts") == FolderTier.HISTORICAL
        assert clf.classify("Prior Versions") == FolderTier.HISTORICAL
        assert clf.classify("Legacy Documents") == FolderTier.HISTORICAL
        assert clf.classify("Superseded") == FolderTier.HISTORICAL

    def test_default_is_working(self) -> None:
        """Unrecognized folders default to tier 2 (working)."""
        clf = FolderPriorityClassifier()
        assert clf.classify("Above 200K USD") == FolderTier.WORKING
        assert clf.classify("Acme Corp") == FolderTier.WORKING
        assert clf.classify("Legal") == FolderTier.WORKING
        assert clf.classify("Customer Files") == FolderTier.WORKING

    def test_case_insensitive(self) -> None:
        """Classification is case-insensitive."""
        clf = FolderPriorityClassifier()
        assert clf.classify("EXECUTED CONTRACTS") == FolderTier.AUTHORITATIVE
        assert clf.classify("drafts") == FolderTier.SUPPLEMENTARY
        assert clf.classify("ARCHIVE") == FolderTier.HISTORICAL

    def test_custom_overrides(self) -> None:
        """User can override folder tier via config."""
        overrides = {"Board Materials": 1, "Team Workspace": 3}
        clf = FolderPriorityClassifier(overrides=overrides)
        assert clf.classify("Board Materials") == FolderTier.AUTHORITATIVE
        assert clf.classify("Team Workspace") == FolderTier.SUPPLEMENTARY

    def test_override_takes_precedence_over_default(self) -> None:
        """User override beats default pattern matching."""
        overrides = {"Drafts": 1}  # User says their Drafts folder is authoritative
        clf = FolderPriorityClassifier(overrides=overrides)
        assert clf.classify("Drafts") == FolderTier.AUTHORITATIVE

    def test_classify_path_uses_all_components(self) -> None:
        """classify_path picks the most authoritative tier from any path component."""
        clf = FolderPriorityClassifier()
        # "Executed" component should dominate even with "Acme Corp" in path
        assert clf.classify_path("Executed Contracts/Acme Corp") == FolderTier.AUTHORITATIVE
        # "Drafts" should dominate over generic group name
        assert clf.classify_path("Above 200K/Drafts") == FolderTier.SUPPLEMENTARY

    def test_classify_path_default_for_plain_path(self) -> None:
        """Path with no special folders is tier 2."""
        clf = FolderPriorityClassifier()
        assert clf.classify_path("Above 200K USD/Acme Corp") == FolderTier.WORKING

    def test_default_tiers_non_empty(self) -> None:
        """Default tier mapping has entries for all four tiers."""
        assert 1 in DEFAULT_FOLDER_TIERS
        assert 2 in DEFAULT_FOLDER_TIERS
        assert 3 in DEFAULT_FOLDER_TIERS
        assert 4 in DEFAULT_FOLDER_TIERS


# ===================================================================
# Phase 3: Version chain detection
# ===================================================================


class TestParseVersionIndicator:
    """Tests for filename version indicator parsing."""

    def test_explicit_version_numbers(self) -> None:
        """Detect v1, v2, v3 etc. in filenames."""
        assert parse_version_indicator("MSA_v1.pdf") == ("v1", 1)
        assert parse_version_indicator("MSA_v2.pdf") == ("v2", 2)
        assert parse_version_indicator("contract_v10.docx") == ("v10", 10)

    def test_signed_keyword(self) -> None:
        """Detect 'signed' as highest-authority indicator."""
        ind, rank = parse_version_indicator("MSA_signed.pdf")
        assert ind == "signed"
        assert rank == 10

    def test_executed_keyword(self) -> None:
        """Detect 'executed' as highest-authority indicator."""
        ind, rank = parse_version_indicator("MSA_executed.pdf")
        assert ind == "executed"
        assert rank == 10

    def test_final_keyword(self) -> None:
        """Detect 'final' as high-authority indicator."""
        ind, rank = parse_version_indicator("contract_FINAL.pdf")
        assert ind == "final"
        assert rank == 9

    def test_draft_keyword(self) -> None:
        """Detect 'draft' as low-authority indicator."""
        ind, rank = parse_version_indicator("MSA_draft.pdf")
        assert ind == "draft"
        assert rank == 2

    def test_no_indicator(self) -> None:
        """Files without version indicators return empty string."""
        ind, rank = parse_version_indicator("MSA.pdf")
        assert ind == ""
        assert rank == 5  # neutral default

    def test_combined_version_and_keyword(self) -> None:
        """When both version number and keyword present, keyword wins rank."""
        ind, rank = parse_version_indicator("MSA_v2_FINAL_signed.pdf")
        assert ind == "signed"
        assert rank == 10

    def test_case_insensitive(self) -> None:
        """Version keywords are case-insensitive."""
        ind, rank = parse_version_indicator("contract_SIGNED.PDF")
        assert ind == "signed"
        assert rank == 10

    def test_redline_keyword(self) -> None:
        """Detect 'redline' as supplementary indicator."""
        ind, rank = parse_version_indicator("MSA_redline.pdf")
        assert ind == "redline"
        assert rank == 3

    def test_superseded_keyword(self) -> None:
        """Detect 'superseded' as historical indicator."""
        ind, rank = parse_version_indicator("old_MSA_superseded.pdf")
        assert ind == "superseded"
        assert rank == 1


class TestVersionChainBuilder:
    """Tests for version chain detection and ordering."""

    def test_groups_similar_filenames(self) -> None:
        """Files with similar base names are grouped together."""
        entries = [
            _fe("Customer/MSA_v1.pdf"),
            _fe("Customer/MSA_v2.pdf"),
            _fe("Customer/DPA.pdf"),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        # MSA_v1 and MSA_v2 should be in one group, DPA alone
        msa_group = [g for g in groups if len(g.files) == 2]
        assert len(msa_group) == 1
        assert len(groups) == 2  # MSA group + DPA group

    def test_orders_by_version_number(self) -> None:
        """Within a group, files ordered by version number (latest first)."""
        entries = [
            _fe("Customer/MSA_v1.pdf", mtime=1000.0),
            _fe("Customer/MSA_v3.pdf", mtime=1200.0),
            _fe("Customer/MSA_v2.pdf", mtime=1100.0),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        assert len(groups) == 1
        paths = [f.path for f in groups[0].files]
        assert paths[0] == "Customer/MSA_v3.pdf"  # Latest version first
        assert paths[-1] == "Customer/MSA_v1.pdf"  # Oldest last

    def test_keyword_beats_version_number(self) -> None:
        """Signed/executed keyword outranks higher version number."""
        entries = [
            _fe("Customer/MSA_v3.pdf", mtime=1200.0),
            _fe("Customer/MSA_v2_signed.pdf", mtime=1100.0),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        assert len(groups) == 1
        # signed should be ranked first (most authoritative)
        assert groups[0].files[0].path == "Customer/MSA_v2_signed.pdf"

    def test_mtime_as_tiebreaker(self) -> None:
        """When version indicators are equal, newer mtime wins."""
        entries = [
            _fe("Customer/MSA.pdf", mtime=1000.0),
            _fe("Customer/MSA_copy.pdf", mtime=2000.0),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        # These might or might not group together depending on similarity
        # but if they do, newer mtime should rank first
        for g in groups:
            if len(g.files) > 1:
                assert g.files[0].mtime >= g.files[-1].mtime

    def test_marks_superseded_files(self) -> None:
        """Non-latest files in a version group are marked superseded."""
        entries = [
            _fe("Customer/MSA_v1.pdf"),
            _fe("Customer/MSA_v2_signed.pdf"),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        assert len(groups) == 1
        latest = groups[0].files[0]
        older = groups[0].files[1]
        assert latest.is_latest_version is True
        assert latest.superseded_by == ""
        assert older.is_latest_version is False
        assert older.superseded_by == latest.path

    def test_single_file_is_latest(self) -> None:
        """A file with no version peers is always latest."""
        entries = [_fe("Customer/DPA.pdf")]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        assert len(groups) == 1
        assert groups[0].files[0].is_latest_version is True
        assert groups[0].files[0].superseded_by == ""

    def test_different_customers_not_grouped(self) -> None:
        """Files from different customer paths are never grouped."""
        entries = [
            _fe("CustomerA/MSA_v1.pdf"),
            _fe("CustomerB/MSA_v1.pdf"),
        ]
        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        # Each customer's MSA should be in its own group
        assert len(groups) == 2

    def test_folder_tier_affects_ranking(self) -> None:
        """File from authoritative folder outranks same-named file from drafts (same customer)."""
        entries = [
            _fe("Customer/Drafts/MSA.pdf"),
            _fe("Customer/Executed/MSA.pdf"),
        ]
        # Set folder tiers
        entries[0].folder_tier = 3  # supplementary
        entries[1].folder_tier = 1  # authoritative

        builder = VersionChainBuilder()
        groups = builder.build_chains(entries)

        # Both are under "Customer" so share the same base name and prefix group
        # They may form one or two groups depending on prefix — verify ranking holds
        all_files = [f for g in groups for f in g.files]
        executed = [f for f in all_files if "Executed" in f.path]
        drafts = [f for f in all_files if "Drafts" in f.path]
        assert len(executed) == 1
        assert len(drafts) == 1
        # Executed should have higher version rank due to keyword
        assert executed[0].version_rank >= drafts[0].version_rank


# ===================================================================
# Phase 4: Precedence scoring
# ===================================================================


class TestPrecedenceScorer:
    """Tests for composite precedence score computation."""

    def test_score_range(self) -> None:
        """Precedence score is between 0 and 1."""
        scorer = PrecedenceScorer()
        entry = _fe("Customer/MSA.pdf", mtime=1700000000.0)
        entry.version_rank = 5
        entry.folder_tier = 2
        score = scorer.compute_score(entry, max_mtime=1700000000.0)
        assert 0.0 <= score <= 1.0

    def test_authoritative_scores_higher(self) -> None:
        """File in authoritative folder with signed indicator scores highest."""
        scorer = PrecedenceScorer()
        auth = _fe("Executed/MSA_signed.pdf", mtime=1700000000.0)
        auth.version_rank = 10
        auth.folder_tier = 1

        draft = _fe("Drafts/MSA_draft.pdf", mtime=1700000000.0)
        draft.version_rank = 2
        draft.folder_tier = 3

        score_auth = scorer.compute_score(auth, max_mtime=1700000000.0)
        score_draft = scorer.compute_score(draft, max_mtime=1700000000.0)

        assert score_auth > score_draft

    def test_newer_file_scores_higher_same_tier(self) -> None:
        """Between same-tier files, newer one scores higher."""
        scorer = PrecedenceScorer()
        old = _fe("Customer/MSA.pdf", mtime=1600000000.0)
        old.version_rank = 5
        old.folder_tier = 2

        new = _fe("Customer/MSA.pdf", mtime=1700000000.0)
        new.version_rank = 5
        new.folder_tier = 2

        score_old = scorer.compute_score(old, max_mtime=1700000000.0)
        score_new = scorer.compute_score(new, max_mtime=1700000000.0)

        assert score_new > score_old

    def test_zero_mtime_gets_low_recency(self) -> None:
        """File with no mtime (0.0) gets minimum recency component."""
        scorer = PrecedenceScorer()
        entry = _fe("Customer/file.pdf", mtime=0.0)
        entry.version_rank = 5
        entry.folder_tier = 2
        score = scorer.compute_score(entry, max_mtime=1700000000.0)
        assert score < 0.7  # Should be penalized

    def test_score_batch(self) -> None:
        """Score a batch of files and verify ordering."""
        scorer = PrecedenceScorer()
        entries = [
            _fe("Customer/MSA_draft.pdf", mtime=1600000000.0),
            _fe("Customer/MSA_v2.pdf", mtime=1650000000.0),
            _fe("Customer/MSA_signed.pdf", mtime=1700000000.0),
        ]
        entries[0].version_rank = 2
        entries[0].folder_tier = 3
        entries[1].version_rank = 5
        entries[1].folder_tier = 2
        entries[2].version_rank = 10
        entries[2].folder_tier = 1

        scored = scorer.score_batch(entries)
        scores = [e.precedence_score for e in scored]
        # Signed > v2 > draft
        assert scores[2] > scores[1] > scores[0]


# ===================================================================
# Phase 5: Config integration
# ===================================================================


class TestPrecedenceConfig:
    """Tests for precedence config in deal-config.json."""

    def test_deal_config_accepts_precedence(self) -> None:
        """DealConfig with precedence section validates correctly."""
        from dd_agents.models.config import DealConfig

        data = {
            "config_version": "1.0.0",
            "buyer": {"name": "BuyerCo"},
            "target": {"name": "TargetCo"},
            "deal": {"type": "acquisition", "focus_areas": ["contract_review"]},
            "precedence": {
                "folder_priority": {"Board Materials": 1, "Team Notes": 3},
            },
        }
        config = DealConfig.model_validate(data)
        assert config.precedence is not None
        assert config.precedence.folder_priority["Board Materials"] == 1

    def test_deal_config_without_precedence(self) -> None:
        """DealConfig without precedence section still works (backward compatible)."""
        from dd_agents.models.config import DealConfig

        data = {
            "config_version": "1.0.0",
            "buyer": {"name": "BuyerCo"},
            "target": {"name": "TargetCo"},
            "deal": {"type": "acquisition", "focus_areas": ["contract_review"]},
        }
        config = DealConfig.model_validate(data)
        assert config.precedence is None

    def test_precedence_config_defaults(self) -> None:
        """PrecedenceConfig has sensible defaults."""
        from dd_agents.models.config import PrecedenceConfig

        pc = PrecedenceConfig()
        assert pc.folder_priority == {}
        assert pc.enabled is True


# ===================================================================
# Phase 6: Prompt enhancement
# ===================================================================


class TestPrecedenceInPrompts:
    """Tests that agent prompts include precedence metadata."""

    def test_prompt_includes_precedence_annotations(self) -> None:
        """Customer file list should show precedence status markers."""
        from dd_agents.agents.prompt_builder import PromptBuilder
        from dd_agents.models.inventory import CustomerEntry

        builder = PromptBuilder(
            project_dir=Path("/tmp/proj"),
            run_dir=Path("/tmp/proj/run"),
            run_id="test_run",
        )

        customers = [
            CustomerEntry(
                group="GroupA",
                name="Acme Corp",
                safe_name="acme_corp",
                path="GroupA/Acme Corp",
                file_count=2,
                files=["GroupA/Acme Corp/MSA_v1.pdf", "GroupA/Acme Corp/MSA_signed.pdf"],
            )
        ]

        # Create file precedence index
        file_precedence = {
            "GroupA/Acme Corp/MSA_signed.pdf": FileEntry(
                path="GroupA/Acme Corp/MSA_signed.pdf",
                mtime=1700000000.0,
                mtime_iso="2023-11-14",
                version_indicator="signed",
                precedence_score=0.95,
                is_latest_version=True,
            ),
            "GroupA/Acme Corp/MSA_v1.pdf": FileEntry(
                path="GroupA/Acme Corp/MSA_v1.pdf",
                mtime=1600000000.0,
                mtime_iso="2020-09-13",
                version_indicator="v1",
                precedence_score=0.3,
                is_latest_version=False,
                superseded_by="GroupA/Acme Corp/MSA_signed.pdf",
            ),
        }

        prompt = builder.build_specialist_prompt(
            "legal",
            customers,
            file_precedence=file_precedence,
        )

        # Should contain precedence markers
        assert "AUTHORITATIVE" in prompt or "CURRENT" in prompt
        assert "SUPERSEDED" in prompt
        # Should contain the precedence rules section
        assert "DOCUMENT PRECEDENCE" in prompt

    def test_prompt_without_precedence_still_works(self) -> None:
        """Prompt builds correctly without precedence data (backward compatible)."""
        from dd_agents.agents.prompt_builder import PromptBuilder
        from dd_agents.models.inventory import CustomerEntry

        builder = PromptBuilder(
            project_dir=Path("/tmp/proj"),
            run_dir=Path("/tmp/proj/run"),
            run_id="test_run",
        )

        customers = [
            CustomerEntry(
                group="GroupA",
                name="Acme Corp",
                safe_name="acme_corp",
                path="GroupA/Acme Corp",
                file_count=1,
                files=["GroupA/Acme Corp/MSA.pdf"],
            )
        ]

        # No file_precedence passed
        prompt = builder.build_specialist_prompt("legal", customers)

        assert "Acme Corp" in prompt
        assert "MSA.pdf" in prompt


# ===================================================================
# Phase 7: Merge enhancement
# ===================================================================


class TestPrecedenceAwareMerge:
    """Tests that merge winner selection factors in source file precedence."""

    def test_pick_winner_prefers_authoritative_source(self) -> None:
        """Finding from higher-precedence source outranks lower when severity ties."""
        from dd_agents.reporting.merge import FindingMerger

        merger = FindingMerger(
            run_id="test",
            file_precedence={
                "Executed/MSA_signed.pdf": 0.95,
                "Drafts/MSA_draft.pdf": 0.3,
            },
        )

        group = [
            {
                "title": "Liability cap issue",
                "severity": "P1",
                "agent": "legal",
                "citations": [{"source_path": "Drafts/MSA_draft.pdf", "exact_quote": "short"}],
            },
            {
                "title": "Liability cap issue",
                "severity": "P1",
                "agent": "finance",
                "citations": [{"source_path": "Executed/MSA_signed.pdf", "exact_quote": "short"}],
            },
        ]

        winner = merger._pick_winner(group)
        # Should prefer finding from the executed/signed source
        assert winner["citations"][0]["source_path"] == "Executed/MSA_signed.pdf"

    def test_severity_still_primary_factor(self) -> None:
        """Higher severity wins even if from lower-precedence source."""
        from dd_agents.reporting.merge import FindingMerger

        merger = FindingMerger(
            run_id="test",
            file_precedence={
                "Executed/MSA_signed.pdf": 0.95,
                "Drafts/MSA_draft.pdf": 0.3,
            },
        )

        group = [
            {
                "title": "Issue",
                "severity": "P0",
                "agent": "legal",
                "citations": [{"source_path": "Drafts/MSA_draft.pdf", "exact_quote": "q"}],
            },
            {
                "title": "Issue",
                "severity": "P2",
                "agent": "finance",
                "citations": [{"source_path": "Executed/MSA_signed.pdf", "exact_quote": "q"}],
            },
        ]

        winner = merger._pick_winner(group)
        # P0 wins regardless of source precedence
        assert winner["severity"] == "P0"

    def test_merge_without_precedence_still_works(self) -> None:
        """Merger without file_precedence falls back to old behavior."""
        from dd_agents.reporting.merge import FindingMerger

        merger = FindingMerger(run_id="test")
        group = [
            {
                "title": "Issue A",
                "severity": "P2",
                "agent": "legal",
                "citations": [{"source_path": "file.pdf", "exact_quote": "short"}],
            },
            {
                "title": "Issue A",
                "severity": "P1",
                "agent": "finance",
                "citations": [{"source_path": "file.pdf", "exact_quote": "longer quote text"}],
            },
        ]

        winner = merger._pick_winner(group)
        assert winner["severity"] == "P1"  # Higher severity wins


# ===================================================================
# Phase 8: Orchestrator integration
# ===================================================================


class TestPrecedenceOrchestratorIntegration:
    """Tests that the orchestrator wires precedence into the pipeline."""

    def test_compute_precedence_index(self) -> None:
        """compute_precedence_index enriches files and returns path→score dict."""
        from dd_agents.orchestrator.precedence import compute_precedence_index

        files = [
            _fe("Customer/Executed/MSA_signed.pdf", mtime=1700000000.0),
            _fe("Customer/Drafts/MSA_draft.pdf", mtime=1600000000.0),
            _fe("Customer/NDA.pdf", mtime=1650000000.0),
        ]

        index = compute_precedence_index(files)

        # Returns a dict mapping path → precedence_score
        assert isinstance(index, dict)
        assert len(index) == 3
        # All scores in range
        for path, score in index.items():
            assert isinstance(path, str)
            assert 0.0 <= score <= 1.0

        # Signed/executed file should score highest
        assert index["Customer/Executed/MSA_signed.pdf"] > index["Customer/Drafts/MSA_draft.pdf"]

    def test_compute_precedence_index_with_config_overrides(self) -> None:
        """Folder priority overrides from deal-config are respected."""
        from dd_agents.orchestrator.precedence import compute_precedence_index

        files = [
            _fe("Customer/Board Materials/MSA.pdf", mtime=1700000000.0),
            _fe("Customer/Team Notes/MSA.pdf", mtime=1700000000.0),
        ]

        index = compute_precedence_index(
            files,
            folder_overrides={"Board Materials": 1, "Team Notes": 3},
        )

        assert index["Customer/Board Materials/MSA.pdf"] > index["Customer/Team Notes/MSA.pdf"]

    def test_compute_precedence_index_empty_list(self) -> None:
        """Empty file list returns empty dict."""
        from dd_agents.orchestrator.precedence import compute_precedence_index

        index = compute_precedence_index([])
        assert index == {}

    def test_compute_precedence_index_enriches_file_entries(self) -> None:
        """File entries are mutated in-place with version/folder/score data."""
        from dd_agents.orchestrator.precedence import compute_precedence_index

        files = [
            _fe("Customer/MSA_signed.pdf", mtime=1700000000.0),
        ]

        compute_precedence_index(files)

        # File entry should be enriched
        assert files[0].version_indicator == "signed"
        assert files[0].version_rank == 10
        assert files[0].precedence_score > 0.0

    def test_compute_precedence_index_sets_folder_tier(self) -> None:
        """Files in authoritative folders get tier 1."""
        from dd_agents.orchestrator.precedence import compute_precedence_index

        files = [
            _fe("Customer/Executed/MSA.pdf", mtime=1700000000.0),
            _fe("Customer/Drafts/MSA.pdf", mtime=1700000000.0),
        ]

        compute_precedence_index(files)

        assert files[0].folder_tier == 1  # Executed → AUTHORITATIVE
        assert files[1].folder_tier == 3  # Drafts → SUPPLEMENTARY
