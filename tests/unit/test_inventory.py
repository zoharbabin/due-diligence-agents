"""Unit tests for the inventory module: FileDiscovery, SubjectRegistryBuilder,
ReferenceFileClassifier, SubjectMentionBuilder, InventoryIntegrityVerifier.
"""

from __future__ import annotations

import csv
import json
from typing import TYPE_CHECKING

from dd_agents.inventory.discovery import FileDiscovery
from dd_agents.inventory.integrity import InventoryIntegrityVerifier
from dd_agents.inventory.mentions import SubjectMentionBuilder
from dd_agents.inventory.reference_files import ReferenceFileClassifier
from dd_agents.inventory.subjects import SubjectRegistryBuilder
from dd_agents.models.inventory import (
    FileEntry,
    ReferenceFile,
    SubjectMention,
    SubjectMentionIndex,
)

if TYPE_CHECKING:
    from pathlib import Path

# =========================================================================
# Helpers
# =========================================================================


def _create_data_room(tmp_path: Path) -> Path:
    """Create a minimal data room directory structure for testing.

    Layout:
        data_room/
            GroupA/
                Acme Corp/
                    msa.pdf
                    sow.docx
                Globex Inc/
                    contract.pdf
            GroupB/
                Alpine Systems/
                    agreement.pdf
                    addendum.docx
                    financials.xlsx
            revenue_summary.xlsx       (reference file)
            pricing_schedule.pdf       (reference file)
            corporate_bylaws.docx      (reference file)
    """
    dr = tmp_path / "data_room"
    dr.mkdir()

    # GroupA
    acme = dr / "GroupA" / "Acme Corp"
    acme.mkdir(parents=True)
    (acme / "msa.pdf").write_text("MSA content")
    (acme / "sow.docx").write_text("SOW content")

    globex = dr / "GroupA" / "Globex Inc"
    globex.mkdir(parents=True)
    (globex / "contract.pdf").write_text("Contract content")

    # GroupB
    alpine = dr / "GroupB" / "Alpine Systems"
    alpine.mkdir(parents=True)
    (alpine / "agreement.pdf").write_text("Agreement content")
    (alpine / "addendum.docx").write_text("Addendum content")
    (alpine / "financials.xlsx").write_text("Financial data")

    # Reference files at root
    (dr / "revenue_summary.xlsx").write_text("Revenue data for Acme Corp and Globex")
    (dr / "pricing_schedule.pdf").write_text("Pricing tiers")
    (dr / "corporate_bylaws.docx").write_text("Corporate governance bylaws")

    return dr


# =========================================================================
# FileDiscovery
# =========================================================================


class TestFileDiscovery:
    """Tests for file discovery."""

    def test_discover_finds_all_files(self, tmp_path: Path) -> None:
        """discover should find all non-excluded files."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        paths = {f.path for f in files}
        assert "GroupA/Acme Corp/msa.pdf" in paths
        assert "GroupA/Acme Corp/sow.docx" in paths
        assert "GroupA/Globex Inc/contract.pdf" in paths
        assert "GroupB/Alpine Systems/agreement.pdf" in paths
        assert "GroupB/Alpine Systems/addendum.docx" in paths
        assert "GroupB/Alpine Systems/financials.xlsx" in paths
        assert "revenue_summary.xlsx" in paths
        assert "pricing_schedule.pdf" in paths
        assert "corporate_bylaws.docx" in paths
        assert len(files) == 9

    def test_discover_excludes_dd_directory(self, tmp_path: Path) -> None:
        """discover should skip the _dd artifacts directory."""
        dr = _create_data_room(tmp_path)
        dd = dr / "_dd" / "forensic-dd" / "index"
        dd.mkdir(parents=True)
        (dd / "cache.json").write_text("{}")

        disco = FileDiscovery()
        files = disco.discover(dr)
        paths = {f.path for f in files}
        assert not any("_dd" in p for p in paths)

    def test_discover_excludes_dd_output_directory(self, tmp_path: Path) -> None:
        """discover should skip the dd_output SDK artifact directory."""
        dr = _create_data_room(tmp_path)
        sdk_out = dr / "dd_output" / "run_12345"
        sdk_out.mkdir(parents=True)
        (sdk_out / "output.json").write_text("{}")

        disco = FileDiscovery()
        files = disco.discover(dr)
        paths = {f.path for f in files}
        assert not any("dd_output" in p for p in paths)

    def test_discover_excludes_patterns(self, tmp_path: Path) -> None:
        """discover should skip files matching exclude patterns."""
        dr = _create_data_room(tmp_path)
        (dr / ".DS_Store").write_text("")
        (dr / "GroupA" / "Thumbs.db").write_text("")
        (dr / "GroupA" / "Acme Corp" / "~$temp.docx").write_text("")

        disco = FileDiscovery()
        files = disco.discover(dr)
        paths = {f.path for f in files}
        assert ".DS_Store" not in paths
        assert "GroupA/Thumbs.db" not in paths
        assert "GroupA/Acme Corp/~$temp.docx" not in paths

    def test_discover_returns_sorted_entries(self, tmp_path: Path) -> None:
        """discover should return entries sorted by path."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)
        paths = [f.path for f in files]
        assert paths == sorted(paths)

    def test_discover_records_file_size(self, tmp_path: Path) -> None:
        """FileEntry.size should reflect actual file size."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        msa = next(f for f in files if f.path.endswith("msa.pdf"))
        assert msa.size > 0

    def test_write_tree(self, tmp_path: Path) -> None:
        """write_tree should produce a readable directory tree file."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        tree_path = tmp_path / "output" / "tree.txt"
        disco.write_tree(files, tree_path)

        assert tree_path.exists()
        content = tree_path.read_text()
        # Should contain directory names from the tree
        assert "GroupA" in content
        assert "Acme Corp" in content
        assert "msa.pdf" in content

    def test_write_files_list(self, tmp_path: Path) -> None:
        """write_files_list should produce a flat list with one path per line."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        list_path = tmp_path / "output" / "files.txt"
        disco.write_files_list(files, list_path)

        assert list_path.exists()
        lines = list_path.read_text().strip().splitlines()
        assert len(lines) == len(files)
        assert all("/" in line or "." in line for line in lines)

    def test_discover_empty_data_room(self, tmp_path: Path) -> None:
        """discover should return empty list for an empty directory."""
        dr = tmp_path / "empty"
        dr.mkdir()

        disco = FileDiscovery()
        files = disco.discover(dr)
        assert files == []

    def test_discover_custom_exclude_patterns(self, tmp_path: Path) -> None:
        """discover should respect custom exclude patterns."""
        dr = _create_data_room(tmp_path)
        (dr / "notes.txt").write_text("notes")

        disco = FileDiscovery()
        # Exclude all .txt files
        files = disco.discover(dr, exclude_patterns=["*.txt"])
        paths = {f.path for f in files}
        assert "notes.txt" not in paths


# =========================================================================
# SubjectRegistryBuilder
# =========================================================================


class TestSubjectRegistryBuilder:
    """Tests for subject registry building."""

    def test_build_parses_group_subject_structure(self, tmp_path: Path) -> None:
        """build should correctly identify groups and subjects."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, counts = builder.build(dr, files)

        names = {c.name for c in subjects}
        assert "Acme Corp" in names
        assert "Globex Inc" in names
        assert "Alpine Systems" in names
        assert len(subjects) == 3

    def test_build_computes_safe_names(self, tmp_path: Path) -> None:
        """build should generate subject_safe_name for each subject."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, _ = builder.build(dr, files)

        safe_names = {c.safe_name for c in subjects}
        assert "acme" in safe_names
        assert "globex" in safe_names
        assert "alpine_systems" in safe_names

    def test_build_counts_files_per_subject(self, tmp_path: Path) -> None:
        """Each subject should have the correct file count."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, _ = builder.build(dr, files)

        acme = next(c for c in subjects if c.name == "Acme Corp")
        assert acme.file_count == 2  # msa.pdf, sow.docx

        globex = next(c for c in subjects if c.name == "Globex Inc")
        assert globex.file_count == 1  # contract.pdf

        alpine = next(c for c in subjects if c.name == "Alpine Systems")
        assert alpine.file_count == 3  # agreement.pdf, addendum.docx, financials.xlsx

    def test_build_produces_correct_counts(self, tmp_path: Path) -> None:
        """CountsJson should have correct totals."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, counts = builder.build(dr, files)

        assert counts.total_files == 9
        assert counts.total_subjects == 3
        assert counts.total_reference_files == 3  # root-level files

    def test_build_tracks_groups(self, tmp_path: Path) -> None:
        """CountsJson should track subjects_by_group."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        _, counts = builder.build(dr, files)

        assert counts.subjects_by_group["GroupA"] == 2
        assert counts.subjects_by_group["GroupB"] == 1

    def test_build_tracks_extensions(self, tmp_path: Path) -> None:
        """CountsJson should track files_by_extension."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        _, counts = builder.build(dr, files)

        assert ".pdf" in counts.files_by_extension
        assert ".docx" in counts.files_by_extension
        assert ".xlsx" in counts.files_by_extension

    def test_write_csv(self, tmp_path: Path) -> None:
        """write_csv should produce a valid CSV with header."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, _ = builder.build(dr, files)

        csv_path = tmp_path / "output" / "subjects.csv"
        builder.write_csv(subjects, csv_path)

        assert csv_path.exists()
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3
        assert "group" in rows[0]
        assert "name" in rows[0]
        assert "safe_name" in rows[0]

    def test_write_counts(self, tmp_path: Path) -> None:
        """write_counts should produce valid JSON."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        _, counts = builder.build(dr, files)

        counts_path = tmp_path / "output" / "counts.json"
        builder.write_counts(counts, counts_path)

        assert counts_path.exists()
        data = json.loads(counts_path.read_text())
        assert data["total_files"] == 9
        assert data["total_subjects"] == 3

    def test_single_target_groups_all_files(self, tmp_path: Path) -> None:
        """single_target layout should produce one subject with all files."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, counts = builder.build(dr, files, layout="single_target", target_name="Target Corp")

        assert len(subjects) == 1
        assert subjects[0].name == "Target Corp"
        assert subjects[0].file_count == 9  # all files
        assert counts.total_subjects == 1
        assert counts.total_reference_files == 0  # no reference files in single_target

    def test_single_target_safe_name(self, tmp_path: Path) -> None:
        """single_target layout should compute safe_name from target_name."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, _ = builder.build(dr, files, layout="single_target", target_name="NovaBridge Holdings ULC")

        assert len(subjects) == 1
        assert subjects[0].safe_name == "novabridge_holdings"

    def test_single_target_includes_nested_files(self, tmp_path: Path) -> None:
        """single_target layout should include files at all nesting levels."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects, _ = builder.build(dr, files, layout="single_target", target_name="Target Corp")

        file_paths = set(subjects[0].files)
        # Root-level file
        assert "revenue_summary.xlsx" in file_paths
        # Deeply nested file
        assert "GroupA/Acme Corp/msa.pdf" in file_paths

    def test_auto_layout_is_default(self, tmp_path: Path) -> None:
        """Default layout='auto' should produce the same results as before."""
        dr = _create_data_room(tmp_path)
        disco = FileDiscovery()
        files = disco.discover(dr)

        builder = SubjectRegistryBuilder()
        subjects_default, _ = builder.build(dr, files)
        subjects_auto, _ = builder.build(dr, files, layout="auto")

        assert len(subjects_default) == len(subjects_auto)
        assert {c.name for c in subjects_default} == {c.name for c in subjects_auto}


# =========================================================================
# ReferenceFileClassifier
# =========================================================================


class TestReferenceFileClassifier:
    """Tests for reference file classification and routing."""

    def test_classify_identifies_non_subject_files(self, tmp_path: Path) -> None:
        """classify should identify files not under subject directories."""
        files = [
            FileEntry(path="GroupA/Acme Corp/msa.pdf"),
            FileEntry(path="GroupA/Globex Inc/contract.pdf"),
            FileEntry(path="revenue_summary.xlsx"),
            FileEntry(path="pricing_schedule.pdf"),
            FileEntry(path="corporate_bylaws.docx"),
        ]
        subject_dirs = ["GroupA/Acme Corp", "GroupA/Globex Inc"]

        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, subject_dirs)

        ref_paths = {r.file_path for r in refs}
        assert "revenue_summary.xlsx" in ref_paths
        assert "pricing_schedule.pdf" in ref_paths
        assert "corporate_bylaws.docx" in ref_paths
        assert len(refs) == 3
        # Subject files should NOT be in reference list
        assert "GroupA/Acme Corp/msa.pdf" not in ref_paths

    def test_classify_financial_category(self) -> None:
        """Financial files should be classified as Financial."""
        files = [FileEntry(path="revenue_summary.xlsx")]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        assert len(refs) == 1
        assert refs[0].category == "Financial"

    def test_classify_pricing_category(self) -> None:
        """Pricing files should be classified as Pricing."""
        files = [FileEntry(path="pricing_schedule.pdf")]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        assert len(refs) == 1
        assert refs[0].category == "Pricing"

    def test_classify_corporate_legal_category(self) -> None:
        """Corporate/legal files should be classified correctly."""
        files = [FileEntry(path="corporate_bylaws.docx")]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        assert len(refs) == 1
        assert refs[0].category == "Corporate/Legal"

    def test_classify_compliance_category(self) -> None:
        """Compliance files should be classified correctly."""
        files = [FileEntry(path="soc2_audit_report.pdf")]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        assert len(refs) == 1
        assert refs[0].category == "Compliance"

    def test_classify_unknown_defaults_to_other(self) -> None:
        """Unknown files should be classified as Other."""
        files = [FileEntry(path="random_document.pdf")]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        assert len(refs) == 1
        assert refs[0].category == "Other"

    def test_route_to_agents_financial(self) -> None:
        """Financial files should route to finance and commercial agents."""
        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents("Financial")
        assert "finance" in agents
        assert "commercial" in agents

    def test_route_to_agents_legal(self) -> None:
        """Corporate/Legal files should route to legal agent."""
        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents("Corporate/Legal")
        assert "legal" in agents

    def test_route_to_agents_other(self) -> None:
        """Other files should route to all specialist agents."""
        from dd_agents.agents.registry import AgentRegistry

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents("Other")
        assert len(agents) == len(AgentRegistry.all_specialist_names())

    def test_classify_assigns_agents(self) -> None:
        """Every classified reference file should have at least one agent assigned."""
        files = [
            FileEntry(path="revenue.xlsx"),
            FileEntry(path="compliance_report.pdf"),
            FileEntry(path="unknown.pdf"),
        ]
        classifier = ReferenceFileClassifier()
        refs = classifier.classify(files, [])

        for ref in refs:
            assert len(ref.assigned_to_agents) >= 1

    def test_write_json(self, tmp_path: Path) -> None:
        """write_json should produce valid JSON."""
        refs = [
            ReferenceFile(
                file_path="revenue.xlsx",
                category="Financial",
                subcategory="revenue",
                description="Revenue data",
                assigned_to_agents=["finance"],
            ),
        ]
        classifier = ReferenceFileClassifier()
        out = tmp_path / "reference_files.json"
        classifier.write_json(refs, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 1
        assert data[0]["file_path"] == "revenue.xlsx"


# =========================================================================
# SubjectMentionBuilder
# =========================================================================


class TestSubjectMentionBuilder:
    """Tests for subject-mention index building."""

    def test_build_detects_mentions(self, tmp_path: Path) -> None:
        """build should detect subject names in reference file text."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        (text_dir / "revenue.md").write_text("Revenue for Acme Corp is $1M. Globex has $500K.")

        ref_files = [
            ReferenceFile(
                file_path="revenue.xlsx",
                text_path="revenue.md",
                category="Financial",
                subcategory="revenue",
                description="Revenue data",
                assigned_to_agents=["finance"],
            ),
        ]
        names = {
            "acme_corp": "Acme Corp",
            "globex": "Globex",
            "alpine_systems": "Alpine Systems",
        }

        builder = SubjectMentionBuilder()
        index = builder.build(ref_files, names, text_dir=text_dir)

        mentioned = {m.subject_safe_name for m in index.matches}
        assert "acme_corp" in mentioned
        assert "globex" in mentioned  # "Globex" appears in text (case-insensitive)
        assert "alpine_systems" not in mentioned  # Not in text

    def test_build_detects_case_insensitive(self, tmp_path: Path) -> None:
        """Mention detection should be case-insensitive."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        (text_dir / "data.md").write_text("Revenue for ACME CORP is $1M.")

        ref_files = [
            ReferenceFile(
                file_path="data.xlsx",
                text_path="data.md",
                category="Financial",
                subcategory="data",
                description="Data",
                assigned_to_agents=["finance"],
            ),
        ]
        names = {"acme_corp": "Acme Corp"}

        builder = SubjectMentionBuilder()
        index = builder.build(ref_files, names, text_dir=text_dir)
        assert len(index.matches) == 1

    def test_build_detects_phantom_contracts(self, tmp_path: Path) -> None:
        """Subjects with no mentions should appear in phantom contracts."""
        ref_files: list[ReferenceFile] = []
        names = {"lonely_corp": "Lonely Corp"}

        builder = SubjectMentionBuilder()
        index = builder.build(ref_files, names)

        assert "Lonely Corp" in index.subjects_without_reference_data

    def test_build_detects_ghost_subjects(self, tmp_path: Path) -> None:
        """Names in reference file metadata but not in subject list are ghosts."""
        ref_files = [
            ReferenceFile(
                file_path="data.xlsx",
                category="Financial",
                subcategory="data",
                description="Data",
                assigned_to_agents=["finance"],
                subjects_mentioned=["Ghost LLC"],
            ),
        ]
        names = {"acme_corp": "Acme Corp"}

        builder = SubjectMentionBuilder()
        index = builder.build(ref_files, names)

        assert "Ghost LLC" in index.unmatched_in_reference

    def test_write_json(self, tmp_path: Path) -> None:
        """write_json should produce valid JSON."""
        index = SubjectMentionIndex(
            matches=[
                SubjectMention(
                    subject_name="Acme Corp",
                    subject_safe_name="acme_corp",
                    reference_files=["rev.xlsx"],
                    mention_count=1,
                )
            ],
        )
        builder = SubjectMentionBuilder()
        out = tmp_path / "mentions.json"
        builder.write_json(index, out)

        data = json.loads(out.read_text())
        assert len(data["matches"]) == 1


# =========================================================================
# InventoryIntegrityVerifier
# =========================================================================


class TestInventoryIntegrityVerifier:
    """Tests for inventory integrity checks."""

    def test_passes_on_valid_inventory(self) -> None:
        """verify should return empty list when inventory is consistent."""
        all_files = [
            FileEntry(path="GroupA/Acme/msa.pdf"),
            FileEntry(path="GroupA/Acme/sow.docx"),
            FileEntry(path="revenue.xlsx"),
        ]
        subject_files = [
            FileEntry(path="GroupA/Acme/msa.pdf"),
            FileEntry(path="GroupA/Acme/sow.docx"),
        ]
        ref_files = [
            ReferenceFile(
                file_path="revenue.xlsx",
                category="Financial",
                subcategory="revenue",
                description="Revenue",
                assigned_to_agents=["finance"],
            ),
        ]

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(all_files, subject_files, ref_files)
        assert issues == []

    def test_catches_count_mismatch(self) -> None:
        """verify should flag when total != subject + reference."""
        all_files = [
            FileEntry(path="a.pdf"),
            FileEntry(path="b.pdf"),
            FileEntry(path="c.pdf"),
        ]
        subject_files = [FileEntry(path="a.pdf")]
        ref_files = [
            ReferenceFile(
                file_path="b.pdf",
                category="Other",
                subcategory="other",
                description="Other",
                assigned_to_agents=["legal"],
            ),
        ]

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(all_files, subject_files, ref_files)
        assert any("count mismatch" in i.lower() or "mismatch" in i.lower() for i in issues)

    def test_catches_orphan_files(self) -> None:
        """verify should detect files not classified as subject or reference."""
        all_files = [
            FileEntry(path="a.pdf"),
            FileEntry(path="b.pdf"),
            FileEntry(path="orphan.pdf"),
        ]
        subject_files = [FileEntry(path="a.pdf")]
        ref_files = [
            ReferenceFile(
                file_path="b.pdf",
                category="Other",
                subcategory="other",
                description="Other",
                assigned_to_agents=["legal"],
            ),
        ]

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(all_files, subject_files, ref_files)
        assert any("orphan" in i.lower() for i in issues)

    def test_catches_unclassified_reference(self) -> None:
        """verify should flag reference files with empty category."""
        all_files = [FileEntry(path="a.pdf")]
        subject_files: list[FileEntry] = []
        ref_files = [
            ReferenceFile(
                file_path="a.pdf",
                category="",
                subcategory="",
                description="",
                assigned_to_agents=["legal"],
            ),
        ]

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(all_files, subject_files, ref_files)
        assert any("empty category" in i.lower() for i in issues)

    def test_catches_extra_subject_files(self) -> None:
        """verify should flag subject files not in all_files."""
        all_files = [FileEntry(path="a.pdf")]
        subject_files = [
            FileEntry(path="a.pdf"),
            FileEntry(path="ghost.pdf"),
        ]
        ref_files: list[ReferenceFile] = []

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(all_files, subject_files, ref_files)
        assert any("subject file" in i.lower() for i in issues)
