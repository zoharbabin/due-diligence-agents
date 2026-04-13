"""Unit tests for dd_agents.entity_resolution.dedup — CrossDocumentDeduplicator.

Covers:
- Single canonical: multiple resolutions aggregate source_files and mention_count
- Multiple canonicals: different canonical names tracked separately
- No variants: source_name == canonical_name leaves variants empty
- write_summary / read back: JSON persistence round-trip
- get_summary: sorted keys, serializable output (lists not sets)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.entity_resolution.dedup import CrossDocumentDeduplicator

if TYPE_CHECKING:
    from pathlib import Path


class TestSingleCanonical:
    """Add multiple resolutions for the same canonical and verify aggregation."""

    def test_source_files_accumulated(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_2.pdf")
        dedup.add_resolution("Subject A", "Subject A", "file_3.pdf")

        summary = dedup.get_summary()
        entry = summary["Subject A"]
        assert sorted(entry["source_files"]) == ["file_1.pdf", "file_2.pdf", "file_3.pdf"]

    def test_mention_count_increments(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_2.pdf")
        dedup.add_resolution("Subject A Corp", "Subject A", "file_2.pdf")

        summary = dedup.get_summary()
        assert summary["Subject A"]["mention_count"] == 3

    def test_duplicate_source_file_not_duplicated(self) -> None:
        """Adding the same source_file twice should not duplicate it."""
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_1.pdf")

        summary = dedup.get_summary()
        assert summary["Subject A"]["source_files"] == ["file_1.pdf"]
        # But mention_count still tracks each call
        assert summary["Subject A"]["mention_count"] == 2

    def test_variants_collected(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_1.pdf")
        dedup.add_resolution("CA Corp", "Subject A", "file_2.pdf")
        dedup.add_resolution("Subject A", "Subject A", "file_3.pdf")

        summary = dedup.get_summary()
        assert sorted(summary["Subject A"]["variants"]) == ["CA Corp", "Cust A Inc."]


class TestMultipleCanonicals:
    """Different canonical names should be tracked independently."""

    def test_separate_entries(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Subject B", "Subject B", "file_2.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_3.pdf")

        summary = dedup.get_summary()
        assert "Subject A" in summary
        assert "Subject B" in summary
        assert summary["Subject A"]["mention_count"] == 2
        assert summary["Subject B"]["mention_count"] == 1

    def test_no_cross_contamination(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Variant X", "Subject A", "file_1.pdf")
        dedup.add_resolution("Variant Y", "Subject B", "file_2.pdf")

        summary = dedup.get_summary()
        assert summary["Subject A"]["variants"] == ["Variant X"]
        assert summary["Subject B"]["variants"] == ["Variant Y"]
        assert summary["Subject A"]["source_files"] == ["file_1.pdf"]
        assert summary["Subject B"]["source_files"] == ["file_2.pdf"]


class TestNoVariants:
    """When source_name == canonical_name, variants should remain empty."""

    def test_exact_match_no_variants(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Subject A", "Subject A", "file_2.pdf")

        summary = dedup.get_summary()
        assert summary["Subject A"]["variants"] == []

    def test_mixed_exact_and_variant(self) -> None:
        """Only non-matching source names appear in variants."""
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_2.pdf")
        dedup.add_resolution("Subject A", "Subject A", "file_3.pdf")

        summary = dedup.get_summary()
        assert summary["Subject A"]["variants"] == ["Cust A Inc."]


class TestWriteSummaryAndReadBack:
    """write_summary should persist a valid JSON file that can be read back."""

    def test_round_trip(self, tmp_path: Path) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")
        dedup.add_resolution("Cust A Inc.", "Subject A", "file_2.pdf")
        dedup.add_resolution("Subject B", "Subject B", "file_3.pdf")

        out_path = tmp_path / "dedup_summary.json"
        dedup.write_summary(out_path)

        assert out_path.exists()
        loaded = json.loads(out_path.read_text())

        assert "Subject A" in loaded
        assert "Subject B" in loaded
        assert loaded["Subject A"]["mention_count"] == 2
        assert loaded["Subject A"]["source_files"] == ["file_1.pdf", "file_2.pdf"]
        assert loaded["Subject A"]["variants"] == ["Cust A Inc."]
        assert loaded["Subject B"]["variants"] == []

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Subject A", "Subject A", "file_1.pdf")

        nested_path = tmp_path / "sub" / "dir" / "summary.json"
        dedup.write_summary(nested_path)

        assert nested_path.exists()
        loaded = json.loads(nested_path.read_text())
        assert loaded["Subject A"]["mention_count"] == 1

    def test_empty_deduplicator_writes_empty_object(self, tmp_path: Path) -> None:
        dedup = CrossDocumentDeduplicator()
        out_path = tmp_path / "empty.json"
        dedup.write_summary(out_path)

        loaded = json.loads(out_path.read_text())
        assert loaded == {}


class TestGetSummarySortedAndSerializable:
    """get_summary should return sorted keys and JSON-serializable types."""

    def test_keys_sorted_alphabetically(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Zebra Corp", "Zebra Corp", "file_1.pdf")
        dedup.add_resolution("Alpha Inc.", "Alpha Inc.", "file_2.pdf")
        dedup.add_resolution("Mu LLC", "Mu LLC", "file_3.pdf")

        summary = dedup.get_summary()
        keys = list(summary.keys())
        assert keys == ["Alpha Inc.", "Mu LLC", "Zebra Corp"]

    def test_serializable_no_sets(self) -> None:
        """source_files and variants must be lists, not sets."""
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Variant X", "Subject A", "file_1.pdf")
        dedup.add_resolution("Variant Y", "Subject A", "file_2.pdf")

        summary = dedup.get_summary()
        entry = summary["Subject A"]
        assert isinstance(entry["source_files"], list)
        assert isinstance(entry["variants"], list)
        # Must be directly JSON-serializable (no TypeError on sets)
        json.dumps(summary)

    def test_inner_lists_sorted(self) -> None:
        dedup = CrossDocumentDeduplicator()
        dedup.add_resolution("Zeta Variant", "Subject A", "z_file.pdf")
        dedup.add_resolution("Alpha Variant", "Subject A", "a_file.pdf")

        summary = dedup.get_summary()
        entry = summary["Subject A"]
        assert entry["source_files"] == ["a_file.pdf", "z_file.pdf"]
        assert entry["variants"] == ["Alpha Variant", "Zeta Variant"]
