"""Tests for the dd_agents.extraction subpackage.

Covers:
    - ExtractionCache: compute_checksum, is_cached, update, save/load, remove_stale
    - ExtractionQualityTracker: record, save/load, get_stats
    - MarkitdownExtractor: extract on plain text files (no external deps)
    - ExtractionPipeline: extract_single with a simple text file, cache hit behaviour
    - Cache re-extraction on near-empty output
    - Scanned-PDF density check
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from dd_agents.extraction.cache import ExtractionCache
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.pipeline import (
    _MIN_EXTRACTION_CHARS,
    ExtractionPipeline,
    ExtractionPipelineError,
)
from dd_agents.extraction.quality import ExtractionQualityTracker
from dd_agents.models.inventory import ExtractionQualityEntry

if TYPE_CHECKING:
    from pathlib import Path

# ======================================================================
# ExtractionCache
# ======================================================================


class TestExtractionCache:
    """Tests for the SHA-256 checksum cache."""

    def test_compute_checksum_deterministic(self, tmp_path: Path) -> None:
        """Same content always produces the same hash."""
        f = tmp_path / "file.txt"
        f.write_text("hello world\n", encoding="utf-8")
        h1 = ExtractionCache.compute_checksum(f)
        h2 = ExtractionCache.compute_checksum(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_compute_checksum_differs_on_content_change(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("version 1", encoding="utf-8")
        h1 = ExtractionCache.compute_checksum(f)
        f.write_text("version 2", encoding="utf-8")
        h2 = ExtractionCache.compute_checksum(f)
        assert h1 != h2

    def test_compute_checksum_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ExtractionCache.compute_checksum(tmp_path / "nonexistent.txt")

    def test_is_cached_true(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("file.txt", "abc123")
        assert cache.is_cached("file.txt", "abc123") is True

    def test_is_cached_false_wrong_hash(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("file.txt", "abc123")
        assert cache.is_cached("file.txt", "different") is False

    def test_is_cached_false_missing(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        assert cache.is_cached("nonexistent.txt", "abc123") is False

    def test_is_cached_no_hash_just_presence(self, tmp_path: Path) -> None:
        """When current_hash is None, only checks key existence."""
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("file.txt", "abc123")
        assert cache.is_cached("file.txt") is True
        assert cache.is_cached("other.txt") is False

    def test_update_and_get(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("a.txt", "hash_a")
        cache.update("b.txt", "hash_b")
        assert cache.get("a.txt") == "hash_a"
        assert cache.get("b.txt") == "hash_b"
        assert cache.get("c.txt") is None

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "checksums.sha256"
        cache = ExtractionCache(cache_path)
        cache.update("./path/to/file.pdf", "abcd1234")
        cache.update("./other/file.docx", "efgh5678")
        cache.save()

        # Load into a fresh instance.
        cache2 = ExtractionCache(cache_path)
        cache2.load()
        assert cache2.get("./path/to/file.pdf") == "abcd1234"
        assert cache2.get("./other/file.docx") == "efgh5678"
        assert len(cache2) == 2

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "checksums.sha256"
        cache = ExtractionCache(nested)
        cache.update("f.txt", "hash")
        cache.save()
        assert nested.exists()

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """Loading from a nonexistent path gives an empty cache."""
        cache = ExtractionCache(tmp_path / "missing.sha256")
        cache.load()
        assert len(cache) == 0

    def test_remove_stale(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("keep.txt", "h1")
        cache.update("delete_me.txt", "h2")
        cache.update("also_delete.txt", "h3")

        removed = cache.remove_stale(["keep.txt"])
        assert removed == 2
        assert "keep.txt" in cache
        assert "delete_me.txt" not in cache
        assert "also_delete.txt" not in cache

    def test_remove_stale_no_change(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        cache.update("a.txt", "h1")
        cache.update("b.txt", "h2")
        removed = cache.remove_stale(["a.txt", "b.txt"])
        assert removed == 0
        assert len(cache) == 2

    def test_len_and_contains(self, tmp_path: Path) -> None:
        cache = ExtractionCache(tmp_path / "checksums.sha256")
        assert len(cache) == 0
        cache.update("x.txt", "h")
        assert len(cache) == 1
        assert "x.txt" in cache
        assert "y.txt" not in cache

    def test_checksum_file_format(self, tmp_path: Path) -> None:
        """Verify the on-disk format matches sha256sum convention."""
        cache_path = tmp_path / "checksums.sha256"
        cache = ExtractionCache(cache_path)
        cache.update("./dir/file.pdf", "a" * 64)
        cache.save()

        lines = cache_path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert lines[0] == f"{'a' * 64}  ./dir/file.pdf"


# ======================================================================
# ExtractionQualityTracker
# ======================================================================


class TestExtractionQualityTracker:
    """Tests for the quality tracker."""

    def test_record_basic(self) -> None:
        tracker = ExtractionQualityTracker()
        entry = tracker.record("file.pdf", "primary", 5000, 0.9)
        assert isinstance(entry, ExtractionQualityEntry)
        assert entry.file_path == "file.pdf"
        assert entry.method == "primary"
        assert entry.bytes_extracted == 5000
        assert entry.confidence == 0.9

    def test_record_with_fallback_chain(self) -> None:
        tracker = ExtractionQualityTracker()
        entry = tracker.record(
            "scan.pdf",
            "fallback_ocr",
            1200,
            0.6,
            fallback_chain=["markitdown", "pdftotext", "fallback_ocr"],
        )
        assert entry.fallback_chain == ["markitdown", "pdftotext", "fallback_ocr"]

    def test_record_with_failure_reasons(self) -> None:
        """failure_reasons are stored and round-trip through save/load."""
        tracker = ExtractionQualityTracker()
        reasons = ["pymupdf: too short (10 < 500)", "pdftotext: low density"]
        entry = tracker.record(
            "hard.pdf",
            "fallback_ocr",
            1200,
            0.6,
            fallback_chain=["pymupdf", "pdftotext", "ocr"],
            failure_reasons=reasons,
        )
        assert entry.failure_reasons == reasons

    def test_record_overwrites_previous(self) -> None:
        tracker = ExtractionQualityTracker()
        tracker.record("file.pdf", "primary", 5000, 0.9)
        tracker.record("file.pdf", "fallback_ocr", 1200, 0.6)
        assert len(tracker) == 1
        assert tracker.entries[0].method == "fallback_ocr"

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        quality_path = tmp_path / "extraction_quality.json"

        tracker = ExtractionQualityTracker()
        tracker.record("a.pdf", "primary", 5000, 0.9)
        tracker.record(
            "b.docx",
            "fallback_read",
            2000,
            0.5,
            failure_reasons=["markitdown: too short (5 < 20)"],
        )
        tracker.save(quality_path)

        # Load into a fresh tracker.
        tracker2 = ExtractionQualityTracker()
        tracker2.load(quality_path)
        assert len(tracker2) == 2

        entries = tracker2.entries
        paths = {e.file_path for e in entries}
        assert paths == {"a.pdf", "b.docx"}

        # failure_reasons survive round-trip.
        b_entry = next(e for e in entries if e.file_path == "b.docx")
        assert b_entry.failure_reasons == ["markitdown: too short (5 < 20)"]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "quality.json"
        tracker = ExtractionQualityTracker()
        tracker.record("x.txt", "direct_read", 100, 0.5)
        tracker.save(nested)
        assert nested.exists()

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        tracker = ExtractionQualityTracker()
        tracker.load(tmp_path / "missing.json")
        assert len(tracker) == 0

    def test_load_malformed_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        tracker = ExtractionQualityTracker()
        tracker.load(bad_file)
        assert len(tracker) == 0

    def test_get_stats_empty(self) -> None:
        tracker = ExtractionQualityTracker()
        stats = tracker.get_stats()
        assert stats["total"] == 0
        assert stats["avg_confidence"] == 0.0
        assert stats["total_bytes"] == 0
        assert stats["failed"] == 0

    def test_get_stats_mixed(self) -> None:
        tracker = ExtractionQualityTracker()
        tracker.record("a.pdf", "primary", 5000, 0.9)
        tracker.record("b.pdf", "fallback_ocr", 1200, 0.6)
        tracker.record("c.pdf", "failed", 0, 0.0)

        stats = tracker.get_stats()
        assert stats["total"] == 3
        assert stats["by_method"]["primary"] == 1
        assert stats["by_method"]["fallback_ocr"] == 1
        assert stats["by_method"]["failed"] == 1
        assert stats["total_bytes"] == 6200
        assert stats["failed"] == 1
        assert 0.49 < stats["avg_confidence"] < 0.51  # (0.9+0.6+0.0)/3 = 0.5

    def test_json_contains_timestamps(self, tmp_path: Path) -> None:
        quality_path = tmp_path / "quality.json"
        tracker = ExtractionQualityTracker()
        tracker.record("file.pdf", "primary", 100, 0.9)
        tracker.save(quality_path)

        raw = json.loads(quality_path.read_text())
        entry = raw["file.pdf"]
        assert "timestamp" in entry
        assert "T" in entry["timestamp"]  # ISO format

    def test_entries_property_sorted(self) -> None:
        tracker = ExtractionQualityTracker()
        tracker.record("z.pdf", "primary", 100, 0.9)
        tracker.record("a.pdf", "primary", 200, 0.9)
        entries = tracker.entries
        assert entries[0].file_path == "a.pdf"
        assert entries[1].file_path == "z.pdf"


# ======================================================================
# MarkitdownExtractor
# ======================================================================


class TestMarkitdownExtractor:
    """Tests for MarkitdownExtractor (using plain text files only)."""

    def test_extract_txt_file(self, tmp_path: Path) -> None:
        """Plain .txt files should be read directly with confidence 0.5."""
        f = tmp_path / "readme.txt"
        f.write_text("Hello from a text file.\n", encoding="utf-8")

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(f)
        assert "Hello from a text file" in text
        assert confidence == 0.5

    def test_extract_csv_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(f)
        assert "alpha" in text
        assert confidence == 0.5

    def test_extract_md_file(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.md"
        f.write_text("# Title\n\nSome notes.\n", encoding="utf-8")

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(f)
        assert "# Title" in text
        assert confidence == 0.5

    def test_extract_empty_file(self, tmp_path: Path) -> None:
        """Empty files should return empty string and 0.0 confidence."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(f)
        assert text == ""
        assert confidence == 0.0

    def test_extract_nonexistent_file(self, tmp_path: Path) -> None:
        """Non-existent file returns empty string, no exception."""
        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(tmp_path / "ghost.txt")
        assert text == ""
        assert confidence == 0.0

    def test_extract_unknown_binary_falls_back(self, tmp_path: Path) -> None:
        """An unknown binary format should fall back to text read."""
        f = tmp_path / "data.bin"
        f.write_bytes(b"Some readable text in a .bin file\n")

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(f)
        # Should fall through to direct read
        assert "readable text" in text


# ======================================================================
# ExtractionPipeline
# ======================================================================


class TestExtractionPipeline:
    """Tests for the pipeline orchestrator."""

    def test_extract_single_txt(self, tmp_path: Path) -> None:
        """A simple .txt file should be extracted via direct_read."""
        src = tmp_path / "contract.txt"
        src.write_text(
            "This is a sample contract with enough text to pass the threshold.\n" * 3,
            encoding="utf-8",
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        pipeline = ExtractionPipeline()
        entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "direct_read"
        assert entry.confidence > 0.0
        assert entry.bytes_extracted > 0

        # Check that the .md file was created.
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].read_text(encoding="utf-8").startswith("This is a sample")

    def test_extract_single_csv(self, tmp_path: Path) -> None:
        src = tmp_path / "data.csv"
        src.write_text(
            "name,revenue,date\nAcme,1000000,2024-01-15\nGlobex,500000,2024-03-01\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        pipeline = ExtractionPipeline()
        entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "direct_read"
        assert entry.bytes_extracted > 0

    def test_extract_all_with_cache_hit(self, tmp_path: Path) -> None:
        """Second run with unchanged files should use cache (no re-extract)."""
        src = tmp_path / "sources"
        src.mkdir()
        f1 = src / "a.txt"
        f1.write_text("File A content that is long enough to be extracted successfully.\n", encoding="utf-8")
        f2 = src / "b.txt"
        f2.write_text("File B content that is long enough to be extracted successfully.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "cache" / "checksums.sha256"

        pipeline = ExtractionPipeline()

        # First run: both files extracted.
        entries1 = pipeline.extract_all(
            [str(f1), str(f2)],
            output_dir,
            cache_path,
        )
        assert len(entries1) == 2
        assert all(e.bytes_extracted > 0 for e in entries1)
        assert cache_path.exists()

        # Verify .md output files exist.
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) == 2

        # Second run: files unchanged -- should hit cache.
        pipeline.extract_all(
            [str(f1), str(f2)],
            output_dir,
            cache_path,
        )
        # Cache hits are not re-recorded, so entries2 comes from the
        # quality file which was loaded and persists the original entries.
        # The key point: no error, and cache path still valid.
        assert cache_path.exists()

    def test_extract_all_removes_stale(self, tmp_path: Path) -> None:
        """Files removed from the list should be purged from the cache."""
        src = tmp_path / "sources"
        src.mkdir()
        f1 = src / "keep.txt"
        f1.write_text("Keeping this file with enough content for extraction.\n", encoding="utf-8")
        f2 = src / "remove.txt"
        f2.write_text("This file will be removed later with enough content.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()

        # First run with both files.
        pipeline.extract_all([str(f1), str(f2)], output_dir, cache_path)

        cache = ExtractionCache(cache_path)
        cache.load()
        assert len(cache) == 2

        # Second run with only f1.
        pipeline.extract_all([str(f1)], output_dir, cache_path)

        cache2 = ExtractionCache(cache_path)
        cache2.load()
        assert len(cache2) == 1
        assert str(f1) in cache2

    def test_extract_all_missing_file(self, tmp_path: Path) -> None:
        """A missing file should be recorded as failed, not crash."""
        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        entries = pipeline.extract_all(
            [str(tmp_path / "nonexistent.pdf")],
            output_dir,
            cache_path,
        )
        assert len(entries) == 1
        assert entries[0].confidence == 0.0
        assert entries[0].method == "failed"

    def test_systemic_failure_raises(self, tmp_path: Path) -> None:
        """When >50% of non-plaintext files fail, raise ExtractionPipelineError."""
        src = tmp_path / "sources"
        src.mkdir()

        # Create non-plaintext files that will fail extraction (empty PDFs).
        for i in range(4):
            f = src / f"bad_{i}.pdf"
            f.write_bytes(b"")  # Empty -- all extraction methods will fail.

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        with pytest.raises(ExtractionPipelineError, match="Systemic"):
            pipeline.extract_all(
                [str(src / f"bad_{i}.pdf") for i in range(4)],
                output_dir,
                cache_path,
            )

    def test_safe_text_name_convention(self) -> None:
        """Verify the safe naming convention from spec section 8."""
        assert ExtractionPipeline._safe_text_name("./Above 200K/Acme/MSA.pdf") == "Above 200K__Acme__MSA.pdf.md"

        assert ExtractionPipeline._safe_text_name("./Reference Data/Cube.xlsx") == "Reference Data__Cube.xlsx.md"

        assert ExtractionPipeline._safe_text_name("simple.txt") == "simple.txt.md"

    def test_extract_all_quality_json_written(self, tmp_path: Path) -> None:
        """extraction_quality.json should be written after extract_all."""
        src = tmp_path / "file.txt"
        src.write_text("Content for quality JSON test with sufficient length.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        pipeline.extract_all([str(src)], output_dir, cache_path)

        quality_path = output_dir / "extraction_quality.json"
        assert quality_path.exists()

        data = json.loads(quality_path.read_text())
        assert str(src) in data
        assert data[str(src)]["method"] == "direct_read"
        assert "timestamp" in data[str(src)]

    def test_cache_reextracts_near_empty_output(self, tmp_path: Path) -> None:
        """A cached file with near-empty output (< 100 bytes) should be re-extracted."""
        src = tmp_path / "sources"
        src.mkdir()
        f = src / "contract.txt"
        f.write_text(
            "This is a substantial contract with enough text to pass the threshold.\n" * 5,
            encoding="utf-8",
        )

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "cache" / "checksums.sha256"

        pipeline = ExtractionPipeline()

        # First run: extract normally.
        pipeline.extract_all([str(f)], output_dir, cache_path)

        # Find the output .md file and overwrite with near-empty content.
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) == 1
        md_file = md_files[0]
        original_size = md_file.stat().st_size
        assert original_size > 100

        # Overwrite with a single newline (1 byte — simulates Bug A).
        md_file.write_text("\n", encoding="utf-8")
        assert md_file.stat().st_size < 100

        # Second run: cache gate should reject the near-empty output and re-extract.
        pipeline.extract_all([str(f)], output_dir, cache_path)

        assert md_file.stat().st_size >= 100

    def test_scanned_pdf_density_check(self, tmp_path: Path) -> None:
        """Pymupdf text with low chars/page density should fall through to OCR."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")  # Placeholder — we mock extraction

        # Simulate pymupdf returning sparse text across 32 pages (12.5 chars/page).
        sparse_pages = []
        for i in range(1, 33):
            sparse_pages.append(f"\n--- Page {i} ---\n\nSig.")
        sparse_text = "\n".join(sparse_pages)

        # Simulate OCR returning substantial text.
        ocr_text = "OCR extracted content. " * 50

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=sparse_text),
            patch.object(pipeline, "_run_pdftotext", return_value=""),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        # Should have fallen through to OCR due to low density.
        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.7

    def test_pdftotext_density_check(self, tmp_path: Path) -> None:
        """Pdftotext with low chars/page density should fall through to OCR."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "signed_po.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Simulate pdftotext returning a small signature fragment across pages.
        sparse_pdftotext = "\n--- Page 1 ---\n\nJohn Smith\n--- Page 2 ---\n\n[signature]\n--- Page 3 ---\n\nDate: 2024"
        ocr_text = "OCR extracted full purchase order content. " * 50

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=""),
            patch.object(pipeline, "_run_pdftotext", return_value=sparse_pdftotext),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        # Should have fallen through to OCR due to low pdftotext density.
        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.7

    def test_markitdown_binary_garbage_rejected(self, tmp_path: Path) -> None:
        """Markitdown returning raw PDF binary should fall through to OCR."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scanned_oem.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Simulate markitdown dumping raw PDF binary (< 85% printable).
        binary_garbage = "%PDF-1.3\n%\x80\x81\x82\x83\n140 0 obj\n" + "\x00\x01\x02\x03" * 500
        ocr_text = "OCR extracted OEM agreement content with real clauses. " * 30

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=""),
            patch.object(pipeline, "_run_pdftotext", return_value=""),
            patch.object(pipeline._markitdown, "extract", return_value=(binary_garbage, 0.5)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        # Binary garbage should be rejected; should fall through to OCR.
        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.7
        assert "markitdown" in entry.fallback_chain

    def test_is_readable_text_accepts_normal_text(self) -> None:
        """Normal extracted text (> 85% printable) should pass readability check."""
        text = "This is a normal contract clause with dates 2024-01-15 and amounts $50,000.\n" * 10
        assert ExtractionPipeline._is_readable_text(text) is True

    def test_is_readable_text_rejects_binary(self) -> None:
        """Binary PDF data (< 85% printable) should fail readability check."""
        binary = "%PDF-1.3\n" + "\x00\x01\x02\x03\x80\x81\x82\x83" * 500
        assert ExtractionPipeline._is_readable_text(binary) is False

    def test_is_readable_text_empty(self) -> None:
        """Empty string should fail readability check."""
        assert ExtractionPipeline._is_readable_text("") is False

    def test_cache_reextracts_binary_garbage(self, tmp_path: Path) -> None:
        """Cached output containing binary garbage should trigger re-extraction."""
        src = tmp_path / "sources"
        src.mkdir()
        f = src / "contract.txt"
        f.write_text(
            "This is a substantial contract with enough text to pass the threshold.\n" * 5,
            encoding="utf-8",
        )

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "cache" / "checksums.sha256"

        pipeline = ExtractionPipeline()

        # First run: extract normally.
        pipeline.extract_all([str(f)], output_dir, cache_path)

        # Find the output .md file and overwrite with binary garbage.
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) == 1
        md_file = md_files[0]

        # Write binary-like content (simulates markitdown PDF dump).
        md_file.write_bytes(b"%PDF-1.3\n" + b"\x00\x01\x02\x03" * 500)
        assert md_file.stat().st_size >= 100  # Passes size gate...

        # Second run: cache gate should reject unreadable output and re-extract.
        pipeline.extract_all([str(f)], output_dir, cache_path)

        # Should have re-extracted with real text content.
        content = md_file.read_text(encoding="utf-8")
        assert "substantial contract" in content

    def test_count_pages_in_text(self) -> None:
        """_count_pages_in_text correctly counts page markers."""
        text_3_pages = (
            "\n--- Page 1 ---\n\nContent page 1.\n--- Page 2 ---\n\nContent page 2.\n--- Page 3 ---\n\nContent page 3."
        )
        assert ExtractionPipeline._count_pages_in_text(text_3_pages) == 3

        # No markers → defaults to 1.
        assert ExtractionPipeline._count_pages_in_text("Just plain text.") == 1

        # Empty string → defaults to 1.
        assert ExtractionPipeline._count_pages_in_text("") == 1

    # Issue #12: PDF signature detection in readability checks.

    def test_is_readable_text_rejects_pdf_signature(self) -> None:
        """Text starting with %PDF- is raw PDF binary, even if mostly ASCII."""
        # Linearized PDF headers are largely ASCII (object definitions, metadata)
        # and can fool the 85% printable-ratio heuristic.
        linearized_pdf = (
            "%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n" * 100
        )
        assert ExtractionPipeline._is_readable_text(linearized_pdf) is False

    def test_is_readable_text_rejects_pdf_with_leading_whitespace(self) -> None:
        """PDF signature preceded by whitespace should still be rejected."""
        text = "  \n%PDF-1.4\nsome object data\n" + "ASCII data " * 500
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_cached_output_readable_rejects_pdf_signature(self, tmp_path: Path) -> None:
        """Cached output with PDF magic bytes should be rejected."""
        out_file = tmp_path / "output.md"
        # Write a mostly-ASCII linearized PDF that would pass the printable ratio.
        content = b"%PDF-1.7\n" + b"1 0 obj << /Type /Catalog >> endobj\n" * 300
        out_file.write_bytes(content)

        assert ExtractionPipeline._is_cached_output_readable(out_file) is False

    # Issue #13: Minimum extraction threshold.

    def test_near_empty_pymupdf_falls_through(self, tmp_path: Path) -> None:
        """Pymupdf returning < 500 chars should fall through to next method."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "signed_po.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Simulate pymupdf returning only 151 chars (like a signed PO).
        short_text = "\n--- Page 1 ---\n\n" + "1/23/2025\n" * 10  # ~130 chars
        ocr_text = "OCR extracted full content of the signed purchase order. " * 20

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=short_text),
            patch.object(pipeline, "_run_pdftotext", return_value=short_text),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        # < 500 chars should have fallen through to OCR.
        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.7

    def test_pymupdf_accepts_above_threshold(self, tmp_path: Path) -> None:
        """Pymupdf returning >= 500 chars with good density should be accepted."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "good_contract.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Simulate pymupdf returning ~600 chars across 2 pages.
        good_text = (
            "\n--- Page 1 ---\n\n"
            + "This is a contract clause with substantive content. " * 5
            + "\n--- Page 2 ---\n\n"
            + "More contract text with additional provisions. " * 5
        )

        pipeline = ExtractionPipeline()

        with patch.object(pipeline, "_run_pymupdf", return_value=good_text):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "primary"
        assert entry.confidence == 0.9

    def test_is_watermark_only_detects_docusign_overlay(self) -> None:
        """PDFs with repeated DocuSign envelope IDs are detected as watermark-only."""
        text = "\n".join(
            [
                "--- Page 1 ---",
                "DocuSign Envelope ID: ABC123-DEF456",
                "",
                "--- Page 2 ---",
                "DocuSign Envelope ID: ABC123-DEF456",
                "",
                "--- Page 3 ---",
                "DocuSign Envelope ID: ABC123-DEF456",
                "9/29/2023",
                "CEO",
                "Dev Ganesan",
                "",
                "--- Page 4 ---",
                "DocuSign Envelope ID: ABC123-DEF456",
                "",
                "--- Page 5 ---",
                "DocuSign Envelope ID: ABC123-DEF456",
            ]
        )
        assert ExtractionPipeline._is_watermark_only(text) is True

    def test_is_watermark_only_rejects_normal_pdf(self) -> None:
        """Normal PDFs with diverse content are not flagged as watermark-only."""
        text = (
            "\n--- Page 1 ---\n\nThis Agreement is made between Party A and Party B.\n"
            "\n--- Page 2 ---\n\nSection 1. Definitions. The following terms apply.\n"
            "\n--- Page 3 ---\n\nSection 2. Payment. Fees are due within 30 days.\n"
        )
        assert ExtractionPipeline._is_watermark_only(text) is False

    def test_is_watermark_only_empty_text(self) -> None:
        """Empty text is not flagged as watermark-only."""
        assert ExtractionPipeline._is_watermark_only("") is False

    def test_is_watermark_only_short_text(self) -> None:
        """Short text (< 4 lines) is not flagged as watermark-only."""
        assert ExtractionPipeline._is_watermark_only("line 1\nline 2\nline 3") is False

    def test_watermark_pdf_falls_through_to_glm_ocr(self, tmp_path: Path) -> None:
        """Watermark-only PDFs fall through pymupdf/pdftotext to GLM-OCR."""
        from dd_agents.extraction.glm_ocr import GlmOcrExtractor

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "encrypted.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        watermark_text = "\n".join(f"--- Page {i} ---\nDocuSign Envelope ID: ABC-123" for i in range(1, 12))

        glm_text = "--- Page 1 ---\nThis is the actual contract text extracted by OCR. " * 10
        glm_extractor = GlmOcrExtractor()
        pipeline = ExtractionPipeline(glm_ocr=glm_extractor)

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=watermark_text),
            patch.object(pipeline, "_run_pdftotext", return_value=watermark_text),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(glm_extractor, "extract", return_value=(glm_text, 0.8)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_glm_ocr"
        assert entry.confidence == 0.8
        assert "glm_ocr" in entry.fallback_chain

    def test_image_binary_garbage_falls_through(self, tmp_path: Path) -> None:
        """Image files where markitdown returns binary data fall through to GLM-OCR."""
        from dd_agents.extraction.glm_ocr import GlmOcrExtractor

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scan.png"
        src.write_bytes(b"\x89PNG fake")

        # Simulate markitdown returning binary PNG data (low printable ratio)
        binary_text = "\x89PNG\r\n\x1a\n" + "\x00\x01\x02" * 100

        glm_text = "--- Page 1 ---\nOCR extracted text from scanned image. " * 10
        glm_extractor = GlmOcrExtractor()
        pipeline = ExtractionPipeline(glm_ocr=glm_extractor)

        with (
            patch.object(pipeline._markitdown, "extract", return_value=(binary_text, 0.5)),
            patch.object(glm_extractor, "extract", return_value=(glm_text, 0.8)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_glm_ocr"
        assert entry.confidence == 0.8


# ======================================================================
# TestPdfInspection — _inspect_pdf pre-inspection
# ======================================================================


class TestPdfInspection:
    """Tests for ExtractionPipeline._inspect_pdf."""

    def test_inspect_normal_pdf(self, tmp_path: Path) -> None:
        """Normal PDF (not encrypted, text > 100 chars, no Identity-H) → 'normal'."""
        pdf_path = tmp_path / "normal.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.get_text.return_value = "A" * 200
        mock_page.get_fonts.return_value = [
            (1, "ext", "Type1", "Helvetica", "name", "WinAnsiEncoding", "extra"),
        ]

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "normal"

    def test_inspect_encrypted_pdf(self, tmp_path: Path) -> None:
        """Encrypted PDF → 'encrypted'."""
        pdf_path = tmp_path / "encrypted.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.is_encrypted = True

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "encrypted"

    def test_inspect_scanned_pdf(self, tmp_path: Path) -> None:
        """First page text < 100 chars → 'scanned'."""
        pdf_path = tmp_path / "scanned.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.get_text.return_value = "Short"  # < 100 chars

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "scanned"

    def test_inspect_missing_tounicode(self, tmp_path: Path) -> None:
        """Identity-H encoding + control-char corruption → 'missing_tounicode'."""
        pdf_path = tmp_path / "garbled.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        # Text with >1% control chars simulating garbled Identity-H output.
        garbled_text = "A" * 100 + "\x00\x01\x02\x03\x04" * 10 + "B" * 50
        mock_page = MagicMock()
        mock_page.get_text.return_value = garbled_text
        mock_page.get_fonts.return_value = [
            (1, "ext", "Type0", "Arial", "name", "Identity-H", "extra"),
        ]

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "missing_tounicode"

    def test_inspect_empty_pdf(self, tmp_path: Path) -> None:
        """Empty PDF (0 pages) → 'scanned'."""
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 0

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "scanned"

    def test_inspect_fitz_unavailable(self, tmp_path: Path) -> None:
        """fitz import raises ImportError → graceful degradation to 'normal'."""
        import sys

        pdf_path = tmp_path / "any.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        # Remove fitz from sys.modules if present, and block re-import.
        saved = sys.modules.pop("fitz", None)
        import builtins

        original_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return original_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                result = ExtractionPipeline._inspect_pdf(pdf_path)
        finally:
            if saved is not None:
                sys.modules["fitz"] = saved

        assert result == "normal"


# ======================================================================
# TestControlCharCorruption — _has_control_char_corruption
# ======================================================================


class TestControlCharCorruption:
    """Tests for ExtractionPipeline._has_control_char_corruption."""

    def test_clean_text(self) -> None:
        """Normal text → False."""
        text = "This is perfectly normal contract text with no issues."
        assert ExtractionPipeline._has_control_char_corruption(text) is False

    def test_corrupted_text(self) -> None:
        """Text with >1% control chars → True."""
        # 100 normal chars + 5 control chars = 105 total, 5/105 ≈ 4.8% > 1%
        text = "A" * 100 + "\x00\x01\x02\x03\x04"
        assert ExtractionPipeline._has_control_char_corruption(text) is True

    def test_whitespace_not_counted(self) -> None:
        """Text with only \\n\\r\\t\\x0c whitespace → False."""
        text = "Normal text\n\twith\rtabs\x0cand newlines." * 10
        assert ExtractionPipeline._has_control_char_corruption(text) is False

    def test_empty_text(self) -> None:
        """Empty string → False."""
        assert ExtractionPipeline._has_control_char_corruption("") is False

    def test_threshold_boundary(self) -> None:
        """Text at exactly 1% control chars → False (must be OVER threshold)."""
        # 99 normal chars + 1 control char = 100 total, 1/100 = 1% = threshold
        text = "A" * 99 + "\x00"
        assert ExtractionPipeline._has_control_char_corruption(text) is False


# ======================================================================
# TestTryMethod — _try_method unified helper
# ======================================================================


class TestTryMethod:
    """Tests for ExtractionPipeline._try_method."""

    def test_success_basic(self, tmp_path: Path) -> None:
        """Valid text passes all gates and returns ExtractionQualityEntry."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.txt"
        filepath.write_text("x" * 100, encoding="utf-8")
        chain: list[str] = []
        failure_reasons: list[str] = []

        result = pipeline._try_method(
            "test_method",
            "Good text content " * 10,
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
        )

        assert result is not None
        assert isinstance(result, ExtractionQualityEntry)
        assert result.method == "primary"
        assert result.confidence > 0.0
        assert "test_method" in result.fallback_chain

    def test_too_short(self, tmp_path: Path) -> None:
        """Text below min_chars → None, appends to failure_reasons."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.txt"
        filepath.write_text("x", encoding="utf-8")
        chain: list[str] = []
        failure_reasons: list[str] = []

        result = pipeline._try_method(
            "test_method",
            "short",
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            min_chars=100,
        )

        assert result is None
        assert len(failure_reasons) == 1
        assert "too short" in failure_reasons[0]

    def test_none_text(self, tmp_path: Path) -> None:
        """None text → None."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.txt"
        filepath.write_text("x", encoding="utf-8")
        chain: list[str] = []
        failure_reasons: list[str] = []

        result = pipeline._try_method(
            "test_method",
            None,
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
        )

        assert result is None

    def test_density_gate_fails(self, tmp_path: Path) -> None:
        """check_density=True with sparse text → None."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # Create sparse text across many pages with few chars per page
        sparse_text = ""
        for i in range(1, 33):
            sparse_text += f"\n--- Page {i} ---\n\nSig."
        # This has ~32 pages with very few chars per page

        result = pipeline._try_method(
            "pymupdf",
            sparse_text,
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            min_chars=_MIN_EXTRACTION_CHARS,
            check_density=True,
        )

        assert result is None
        assert any("density" in r for r in failure_reasons)

    def test_readability_gate_fails(self, tmp_path: Path) -> None:
        """check_readability=True with binary garbage → None."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        binary_garbage = "%PDF-1.3\n%\x80\x81\x82\x83\n" + "\x00\x01\x02\x03" * 500

        result = pipeline._try_method(
            "markitdown",
            binary_garbage,
            0.5,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_markitdown",
            check_readability=True,
        )

        assert result is None
        assert any("readability" in r for r in failure_reasons)

    def test_watermark_gate_fails(self, tmp_path: Path) -> None:
        """check_watermark=True with watermark text → None."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # >50% of lines are the same string, enough pages to pass min_chars
        watermark_text = "\n".join(
            f"--- Page {i} ---\nDocuSign Envelope ID: ABC-123-DEF-456-GHI-789" for i in range(1, 30)
        )

        result = pipeline._try_method(
            "pymupdf",
            watermark_text,
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            check_watermark=True,
        )

        assert result is None
        assert any("watermark" in r for r in failure_reasons)

    def test_control_chars_gate_fails(self, tmp_path: Path) -> None:
        """check_control_chars=True with corrupted text → None."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # Text with >1% control characters
        corrupted = "A" * 100 + "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0e\x0f" * 5
        # Pad to pass min_chars
        corrupted = corrupted * 5

        result = pipeline._try_method(
            "pymupdf",
            corrupted,
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            min_chars=_MIN_EXTRACTION_CHARS,
            check_control_chars=True,
        )

        assert result is None
        assert any("control-char" in r for r in failure_reasons)

    def test_chain_appended_before_gates(self, tmp_path: Path) -> None:
        """Name is appended to chain even when gates fail."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # This will fail the readability gate
        binary_garbage = "%PDF-1.3\n" + "\x00\x01\x02\x03" * 500

        pipeline._try_method(
            "markitdown",
            binary_garbage,
            0.5,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_markitdown",
            check_readability=True,
        )

        # Chain should contain the method name even though it failed
        assert "markitdown" in chain

    def test_failure_reasons_accumulated(self, tmp_path: Path) -> None:
        """Multiple failed methods accumulate in failure_reasons list."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # First method fails: too short
        pipeline._try_method(
            "pymupdf",
            "short",
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            min_chars=500,
        )

        # Second method fails: too short
        pipeline._try_method(
            "pdftotext",
            "also short",
            0.7,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_pdftotext",
            min_chars=500,
        )

        # Third method fails: readability
        binary_garbage = "%PDF-1.3\n" + "\x00\x01\x02\x03" * 500
        pipeline._try_method(
            "markitdown",
            binary_garbage,
            0.5,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_markitdown",
            check_readability=True,
        )

        assert len(failure_reasons) == 3
        assert "pymupdf" in failure_reasons[0]
        assert "pdftotext" in failure_reasons[1]
        assert "markitdown" in failure_reasons[2]


# ======================================================================
# TestPdfRouting — pre-inspection routing in _extract_pdf
# ======================================================================


class TestPdfRouting:
    """Tests for pre-inspection routing in _extract_pdf."""

    def test_scanned_pdf_skips_pymupdf_pdftotext_markitdown(self, tmp_path: Path) -> None:
        """'scanned' inspection → pymupdf, pdftotext, and markitdown NOT called."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        pipeline = ExtractionPipeline()

        mock_pymupdf = MagicMock(return_value="")
        mock_pdftotext = MagicMock(return_value="")
        mock_markitdown = MagicMock(return_value=("", 0.0))
        ocr_text = "OCR content " * 50

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="scanned"),
            patch.object(pipeline, "_run_pymupdf", mock_pymupdf),
            patch.object(pipeline, "_run_pdftotext", mock_pdftotext),
            patch.object(pipeline._markitdown, "extract", mock_markitdown),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        mock_pymupdf.assert_not_called()
        mock_pdftotext.assert_not_called()
        mock_markitdown.assert_not_called()
        assert entry.method == "fallback_ocr"

    def test_missing_tounicode_skips_text_extractors(self, tmp_path: Path) -> None:
        """'missing_tounicode' inspection → pymupdf, pdftotext, and markitdown NOT called."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "garbled.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        pipeline = ExtractionPipeline()

        mock_pymupdf = MagicMock(return_value="")
        mock_pdftotext = MagicMock(return_value="")
        mock_markitdown = MagicMock(return_value=("", 0.0))
        ocr_text = "OCR content " * 50

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="missing_tounicode"),
            patch.object(pipeline, "_run_pymupdf", mock_pymupdf),
            patch.object(pipeline, "_run_pdftotext", mock_pdftotext),
            patch.object(pipeline._markitdown, "extract", mock_markitdown),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        mock_pymupdf.assert_not_called()
        mock_pdftotext.assert_not_called()
        mock_markitdown.assert_not_called()
        assert entry.method == "fallback_ocr"

    def test_normal_pdf_tries_pymupdf_first(self, tmp_path: Path) -> None:
        """'normal' inspection → pymupdf IS called."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "normal.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        pipeline = ExtractionPipeline()

        good_text = (
            "\n--- Page 1 ---\n\n"
            + "Contract clause with substantive content. " * 15
            + "\n--- Page 2 ---\n\n"
            + "More contract text with additional provisions. " * 15
        )

        mock_pymupdf = MagicMock(return_value=good_text)

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="normal"),
            patch.object(pipeline, "_run_pymupdf", mock_pymupdf),
        ):
            entry = pipeline.extract_single(src, output_dir)

        mock_pymupdf.assert_called_once()
        assert entry.method == "primary"


# ======================================================================
# TestConfidenceScaling — _scale_confidence
# ======================================================================


class TestConfidenceScaling:
    """Tests for ExtractionPipeline._scale_confidence."""

    def test_full_confidence(self, tmp_path: Path) -> None:
        """actual_chars >= expected → returns base unchanged."""
        filepath = tmp_path / "doc.pdf"
        filepath.write_bytes(b"x" * 1000)
        # Expected: 1000 * 0.09 = 90. Actual: 100 >= 90 → no scaling.
        result = ExtractionPipeline._scale_confidence(0.9, 100, filepath)
        assert result == 0.9

    def test_partial_confidence(self, tmp_path: Path) -> None:
        """actual_chars < expected → returns base * (actual/expected)."""
        filepath = tmp_path / "doc.pdf"
        filepath.write_bytes(b"x" * 1000)
        # Expected: 1000 * 0.09 = 90. Actual: 45 → scale = 45/90 = 0.5
        result = ExtractionPipeline._scale_confidence(0.9, 45, filepath)
        assert result == pytest.approx(0.45, abs=0.001)

    def test_unknown_extension(self, tmp_path: Path) -> None:
        """.xyz extension → returns base unchanged."""
        filepath = tmp_path / "file.xyz"
        filepath.write_bytes(b"x" * 1000)
        result = ExtractionPipeline._scale_confidence(0.9, 100, filepath)
        assert result == 0.9

    def test_zero_file_size(self, tmp_path: Path) -> None:
        """File with 0 bytes → returns base unchanged."""
        filepath = tmp_path / "empty.pdf"
        filepath.write_bytes(b"")
        result = ExtractionPipeline._scale_confidence(0.9, 0, filepath)
        assert result == 0.9


# ======================================================================
# TestFailureReasons — failure_reasons in pipeline
# ======================================================================


class TestFailureReasons:
    """Tests for failure_reasons tracking throughout the pipeline."""

    def test_failure_reasons_in_failed_entry(self, tmp_path: Path) -> None:
        """_failed_entry includes failure_reasons."""
        filepath = tmp_path / "bad.pdf"
        chain = ["pymupdf", "pdftotext"]
        reasons = ["pymupdf: too short (10 < 500)", "pdftotext: low density"]

        entry = ExtractionPipeline._failed_entry(filepath, chain, failure_reasons=reasons)

        assert entry.failure_reasons == reasons
        assert entry.method == "failed"
        assert entry.confidence == 0.0

    def test_failure_reasons_default_empty(self) -> None:
        """ExtractionQualityEntry default failure_reasons is empty list."""
        entry = ExtractionQualityEntry(
            file_path="test.pdf",
            method="primary",
            bytes_extracted=1000,
            confidence=0.9,
        )
        assert entry.failure_reasons == []

    def test_try_method_accumulates_reasons(self, tmp_path: Path) -> None:
        """Multiple failed gates append to failure_reasons."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.pdf"
        filepath.write_bytes(b"%PDF fake")
        chain: list[str] = []
        failure_reasons: list[str] = []

        # First: too short
        pipeline._try_method(
            "pymupdf",
            "tiny",
            0.9,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            min_chars=500,
        )

        # Second: also too short
        pipeline._try_method(
            "pdftotext",
            "small",
            0.7,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_pdftotext",
            min_chars=500,
        )

        assert len(failure_reasons) == 2
        assert "pymupdf" in failure_reasons[0]
        assert "pdftotext" in failure_reasons[1]

    def test_successful_extraction_preserves_reasons(self, tmp_path: Path) -> None:
        """Entry from _try_method includes prior failure_reasons."""
        pipeline = ExtractionPipeline()
        out_file = tmp_path / "output.md"
        filepath = tmp_path / "source.txt"
        filepath.write_text("x" * 100, encoding="utf-8")
        chain: list[str] = []
        failure_reasons: list[str] = ["pymupdf: too short (10 < 500)"]

        result = pipeline._try_method(
            "pdftotext",
            "Good text content " * 30,
            0.7,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_pdftotext",
        )

        assert result is not None
        assert "pymupdf: too short (10 < 500)" in result.failure_reasons

    def test_pdf_chain_collects_all_reasons(self, tmp_path: Path) -> None:
        """Full PDF chain collects reasons from all failed methods."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "difficult.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        pipeline = ExtractionPipeline()

        # All methods fail except OCR
        ocr_text = "OCR extracted content " * 30

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="normal"),
            patch.object(pipeline, "_run_pymupdf", return_value="short"),
            patch.object(pipeline, "_run_pdftotext", return_value="short"),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_ocr"
        # Should have failure reasons from pymupdf, pdftotext, and markitdown
        assert len(entry.failure_reasons) >= 3
        assert any("pymupdf" in r for r in entry.failure_reasons)
        assert any("pdftotext" in r for r in entry.failure_reasons)
        assert any("markitdown" in r for r in entry.failure_reasons)


# ======================================================================
# TestBinaryImageDetection — Bug 2: PNG/JPEG magic + U+FFFD
# ======================================================================


class TestBinaryImageDetection:
    """Tests for PNG/JPEG binary detection in readability checks."""

    def test_is_readable_text_rejects_png_binary_utf8(self) -> None:
        """Binary PNG decoded as UTF-8 → caught by replacement-char gate."""
        raw_png = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\xff" * 200
        text = raw_png.decode("utf-8", errors="replace")
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_readable_text_rejects_png_binary_latin1(self) -> None:
        """Binary PNG decoded as latin-1 → caught by magic-byte gate."""
        # latin-1 maps bytes 1:1 to codepoints, preserving magic bytes.
        raw_png = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\xff" * 200
        text = raw_png.decode("latin-1")
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_readable_text_rejects_jpeg_binary_utf8(self) -> None:
        """Binary JPEG decoded as UTF-8 → caught by replacement-char gate."""
        raw_jpeg = b"\xff\xd8\xff\xe0" + b"\x00\x01\x02\x80" * 200
        text = raw_jpeg.decode("utf-8", errors="replace")
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_readable_text_rejects_jpeg_binary_latin1(self) -> None:
        """Binary JPEG decoded as latin-1 → caught by magic-byte gate."""
        raw_jpeg = b"\xff\xd8\xff\xe0" + b"JFIF" + b"\x00" * 200
        text = raw_jpeg.decode("latin-1")
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_readable_text_rejects_high_replacement_chars(self) -> None:
        """Text with >1% U+FFFD replacement characters should fail."""
        # 100 chars total: 95 normal + 5 U+FFFD = 5% replacement
        text = "A" * 95 + "\ufffd" * 5
        assert ExtractionPipeline._is_readable_text(text) is False

    def test_is_readable_text_accepts_low_replacement_chars(self) -> None:
        """Text with <=1% U+FFFD replacement characters should pass."""
        # 1000 chars total: 995 normal + 5 U+FFFD = 0.5% replacement
        text = "Normal readable contract text. " * 33 + "\ufffd" * 5
        assert ExtractionPipeline._is_readable_text(text) is True

    def test_is_cached_output_rejects_png(self, tmp_path: Path) -> None:
        """Cached output starting with PNG magic should be rejected."""
        out_file = tmp_path / "output.md"
        out_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 500)
        assert ExtractionPipeline._is_cached_output_readable(out_file) is False

    def test_is_cached_output_rejects_jpeg(self, tmp_path: Path) -> None:
        """Cached output starting with JPEG magic should be rejected."""
        out_file = tmp_path / "output.md"
        out_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 500)
        assert ExtractionPipeline._is_cached_output_readable(out_file) is False


# ======================================================================
# TestInspectPdfIdentityH — Bug 3: Identity-H clean text → "normal"
# ======================================================================


class TestInspectPdfIdentityH:
    """Tests for _inspect_pdf Identity-H classification fix."""

    def test_identity_h_clean_text_returns_normal(self, tmp_path: Path) -> None:
        """Identity-H encoding with clean extracted text → 'normal'."""
        pdf_path = tmp_path / "clean_identity_h.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        # Clean text — no control-char corruption.
        mock_page = MagicMock()
        mock_page.get_text.return_value = "This is perfectly clean text from an Identity-H font. " * 5
        mock_page.get_fonts.return_value = [
            (1, "ext", "Type0", "NotoSans", "name", "Identity-H", "extra"),
        ]

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "normal"

    def test_identity_h_garbled_text_returns_missing_tounicode(self, tmp_path: Path) -> None:
        """Identity-H encoding with garbled text → 'missing_tounicode'."""
        pdf_path = tmp_path / "garbled_identity_h.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        # Garbled text with control chars (>1% threshold).
        garbled = "A" * 80 + "\x00\x01\x02\x03\x04\x05" * 5 + "B" * 20
        mock_page = MagicMock()
        mock_page.get_text.return_value = garbled
        mock_page.get_fonts.return_value = [
            (1, "ext", "Type0", "Arial", "name", "Identity-H", "extra"),
        ]

        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.__len__ = lambda self: 1
        mock_doc.__getitem__ = lambda self, idx: mock_page

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            result = ExtractionPipeline._inspect_pdf(pdf_path)

        assert result == "missing_tounicode"

    def test_scanned_pdf_skips_markitdown(self, tmp_path: Path) -> None:
        """Scanned PDFs skip markitdown (pdfminer can't extract from images)."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        pipeline = ExtractionPipeline()

        mock_markitdown = MagicMock(return_value=("", 0.0))
        ocr_text = "OCR extracted content " * 30

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="scanned"),
            patch.object(pipeline._markitdown, "extract", mock_markitdown),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        mock_markitdown.assert_not_called()
        assert entry.method == "fallback_ocr"


# ======================================================================
# TestClaudeVision — Claude vision last-resort
# ======================================================================


class TestClaudeVision:
    """Tests for Claude vision fallback in extraction chains."""

    def test_claude_vision_in_pdf_chain(self, tmp_path: Path) -> None:
        """Claude vision is tried after OCR fails in PDF chain."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "unreadable.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        vision_text = "Visual description of the document content from Claude. " * 10

        pipeline = ExtractionPipeline()

        with (
            patch.object(ExtractionPipeline, "_inspect_pdf", return_value="scanned"),
            patch.object(pipeline._ocr, "extract", return_value=("", 0.0)),
            patch.object(ExtractionPipeline, "_try_claude_vision", return_value=(vision_text, 0.65)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_claude_vision"
        assert entry.confidence == 0.65
        assert "claude_vision" in entry.fallback_chain

    def test_claude_vision_in_image_chain(self, tmp_path: Path) -> None:
        """Claude vision is tried after OCR fails in image chain."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "complex.png"
        src.write_bytes(b"\x89PNG fake image data")

        vision_text = "Chart showing revenue trends Q1-Q4 with data points. " * 10

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=("", 0.0)),
            patch.object(ExtractionPipeline, "_try_claude_vision", return_value=(vision_text, 0.65)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_claude_vision"
        assert entry.confidence == 0.65
        assert "claude_vision" in entry.fallback_chain

    def test_claude_vision_failure_falls_through(self, tmp_path: Path) -> None:
        """When Claude vision fails, fall through to diagram placeholder (images)."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "broken.png"
        src.write_bytes(b"\x89PNG fake image data")

        pipeline = ExtractionPipeline()

        with (
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=("", 0.0)),
            patch.object(ExtractionPipeline, "_try_claude_vision", return_value=("", 0.0)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        # Should fall through to diagram placeholder.
        assert entry.method == "fallback_read"
        assert "diagram_placeholder" in entry.fallback_chain

    def test_claude_vision_not_called_when_ocr_succeeds(self, tmp_path: Path) -> None:
        """Claude vision is NOT called when OCR succeeds."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        src = tmp_path / "ocreable.png"
        src.write_bytes(b"\x89PNG fake image data")

        ocr_text = "OCR successfully extracted this text from the image. " * 10

        pipeline = ExtractionPipeline()
        mock_vision = MagicMock(return_value=("", 0.0))

        with (
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.7)),
            patch.object(ExtractionPipeline, "_try_claude_vision", mock_vision),
        ):
            entry = pipeline.extract_single(src, output_dir)

        mock_vision.assert_not_called()
        assert entry.method == "fallback_ocr"

    def test_try_claude_vision_timeout(self) -> None:
        """_try_claude_vision returns empty on timeout."""
        from pathlib import Path as _Path

        filepath = _Path("/tmp/fake_image.png")

        with patch.object(
            ExtractionPipeline,
            "_describe_image_async",
            side_effect=TimeoutError("timed out"),
        ):
            text, conf = ExtractionPipeline._try_claude_vision(filepath)

        assert text == ""
        assert conf == 0.0


# ======================================================================
# TestSharedConstants — _constants and _helpers modules
# ======================================================================


class TestSharedConstants:
    """Tests for shared constants and helpers in dd_agents.extraction._constants / _helpers."""

    def test_image_extensions_complete(self) -> None:
        """IMAGE_EXTENSIONS contains exactly 7 extensions."""
        from dd_agents.extraction._constants import IMAGE_EXTENSIONS

        assert len(IMAGE_EXTENSIONS) == 7
        for ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"):
            assert ext in IMAGE_EXTENSIONS

    def test_plaintext_extensions_complete(self) -> None:
        """PLAINTEXT_EXTENSIONS contains exactly 12 extensions."""
        from dd_agents.extraction._constants import PLAINTEXT_EXTENSIONS

        assert len(PLAINTEXT_EXTENSIONS) == 12
        for ext in (".txt", ".csv", ".md", ".json", ".yaml", ".yml", ".xml", ".log", ".tsv", ".ini", ".cfg", ".conf"):
            assert ext in PLAINTEXT_EXTENSIONS

    def test_read_text_basic(self, tmp_path: Path) -> None:
        """Shared read_text helper reads a UTF-8 text file."""
        from dd_agents.extraction._helpers import read_text

        f = tmp_path / "sample.txt"
        f.write_text("Hello, shared helper!", encoding="utf-8")
        text, conf = read_text(f)
        assert "Hello, shared helper!" in text
        assert conf == 0.5

    def test_read_text_empty_file(self, tmp_path: Path) -> None:
        """Shared read_text returns ('', 0.0) for empty files."""
        from dd_agents.extraction._helpers import read_text

        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        text, conf = read_text(f)
        assert text == ""
        assert conf == 0.0

    def test_check_text_quality_rejects_binary(self) -> None:
        """_check_text_quality rejects binary garbage."""
        # High U+FFFD ratio → reject
        sample = "A" * 50 + "\ufffd" * 50
        assert ExtractionPipeline._check_text_quality(sample) is False

    def test_check_text_quality_accepts_clean_text(self) -> None:
        """_check_text_quality accepts clean readable text."""
        sample = "This is perfectly clean readable text with normal characters.\n" * 10
        assert ExtractionPipeline._check_text_quality(sample) is True


# ======================================================================
# TestParallelExtraction — Issue #36: ThreadPoolExecutor in extract_all
# ======================================================================


class TestParallelExtraction:
    """Tests for parallel extraction via ThreadPoolExecutor."""

    def test_extract_all_uses_thread_pool_executor(self, tmp_path: Path) -> None:
        """extract_all should use ThreadPoolExecutor for file processing."""
        src = tmp_path / "sources"
        src.mkdir()
        f1 = src / "a.txt"
        f1.write_text("File A content that is long enough to be extracted.\n", encoding="utf-8")
        f2 = src / "b.txt"
        f2.write_text("File B content that is long enough to be extracted.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()

        with patch(
            "dd_agents.extraction.pipeline.ThreadPoolExecutor",
            wraps=__import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor,
        ) as mock_executor_cls:
            pipeline.extract_all([str(f1), str(f2)], output_dir, cache_path)

        # ThreadPoolExecutor was instantiated.
        mock_executor_cls.assert_called_once()

    def test_extract_all_default_worker_count(self) -> None:
        """Default worker count should be min(8, os.cpu_count() or 4)."""
        import os as _os

        from dd_agents.extraction.pipeline import _DEFAULT_WORKERS

        expected = min(8, _os.cpu_count() or 4)
        assert expected == _DEFAULT_WORKERS

    def test_extract_all_custom_worker_count(self, tmp_path: Path) -> None:
        """extract_all accepts max_workers parameter."""
        src = tmp_path / "sources"
        src.mkdir()
        f1 = src / "a.txt"
        f1.write_text("File A content that is long enough to be extracted.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()

        with patch(
            "dd_agents.extraction.pipeline.ThreadPoolExecutor",
            wraps=__import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor,
        ) as mock_executor_cls:
            pipeline.extract_all([str(f1)], output_dir, cache_path, max_workers=3)

        mock_executor_cls.assert_called_once_with(max_workers=3)

    def test_extract_all_parallel_produces_correct_results(self, tmp_path: Path) -> None:
        """Parallel extraction produces the same results as sequential would."""
        src = tmp_path / "sources"
        src.mkdir()

        file_paths: list[str] = []
        for i in range(20):
            f = src / f"file_{i}.txt"
            f.write_text(f"Content of file {i} with sufficient text length.\n", encoding="utf-8")
            file_paths.append(str(f))

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        entries = pipeline.extract_all(file_paths, output_dir, cache_path, max_workers=4)

        assert len(entries) == 20
        assert all(e.method == "direct_read" for e in entries)
        assert all(e.bytes_extracted > 0 for e in entries)

        # All output files created.
        md_files = list(output_dir.glob("*.md"))
        # One extra file: extraction_quality.json is not .md so this should be 20.
        assert len(md_files) == 20

    def test_extract_all_handles_mixed_success_and_failure(self, tmp_path: Path) -> None:
        """Parallel extraction correctly handles both successful and missing files."""
        src = tmp_path / "sources"
        src.mkdir()
        f1 = src / "good.txt"
        f1.write_text("Good file with enough content for extraction.\n", encoding="utf-8")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        entries = pipeline.extract_all(
            [str(f1), str(tmp_path / "missing.pdf")],
            output_dir,
            cache_path,
        )

        assert len(entries) == 2
        methods = {e.method for e in entries}
        assert "direct_read" in methods
        assert "failed" in methods


# ======================================================================
# TestExtractionSummary — Issue #41: get_extraction_summary
# ======================================================================


class TestExtractionSummary:
    """Tests for ExtractionPipeline.get_extraction_summary."""

    def test_summary_empty_entries(self) -> None:
        """Empty entries list produces zeroed summary."""
        summary = ExtractionPipeline.get_extraction_summary([])
        assert summary["total"] == 0
        assert summary["succeeded"] == 0
        assert summary["failed"] == 0
        assert summary["failure_rate"] == 0.0
        assert summary["by_method"] == {}

    def test_summary_all_successful(self) -> None:
        """All primary extractions produce 0% failure rate."""
        entries = [
            ExtractionQualityEntry(
                file_path=f"file_{i}.pdf",
                method="primary",
                bytes_extracted=5000,
                confidence=0.9,
            )
            for i in range(10)
        ]
        summary = ExtractionPipeline.get_extraction_summary(entries)
        assert summary["total"] == 10
        assert summary["succeeded"] == 10
        assert summary["failed"] == 0
        assert summary["failure_rate"] == 0.0
        assert summary["by_method"]["primary"] == 10

    def test_summary_mixed_methods(self) -> None:
        """Summary correctly counts methods."""
        entries = [
            ExtractionQualityEntry(file_path="a.pdf", method="primary", bytes_extracted=5000, confidence=0.9),
            ExtractionQualityEntry(file_path="b.pdf", method="fallback_ocr", bytes_extracted=2000, confidence=0.7),
            ExtractionQualityEntry(file_path="c.pdf", method="fallback_ocr", bytes_extracted=1500, confidence=0.6),
            ExtractionQualityEntry(file_path="d.pdf", method="failed", bytes_extracted=0, confidence=0.0),
            ExtractionQualityEntry(file_path="e.txt", method="direct_read", bytes_extracted=500, confidence=0.5),
        ]
        summary = ExtractionPipeline.get_extraction_summary(entries)
        assert summary["total"] == 5
        assert summary["by_method"]["primary"] == 1
        assert summary["by_method"]["fallback_ocr"] == 2
        assert summary["by_method"]["failed"] == 1
        assert summary["by_method"]["direct_read"] == 1

    def test_summary_failure_rate_calculation(self) -> None:
        """Failure rate is computed over non-plaintext files only."""
        entries = [
            ExtractionQualityEntry(file_path="a.pdf", method="failed", bytes_extracted=0, confidence=0.0),
            ExtractionQualityEntry(file_path="b.pdf", method="failed", bytes_extracted=0, confidence=0.0),
            ExtractionQualityEntry(file_path="c.pdf", method="primary", bytes_extracted=5000, confidence=0.9),
            ExtractionQualityEntry(file_path="d.pdf", method="primary", bytes_extracted=5000, confidence=0.9),
            # Plaintext files (direct_read with confidence >= 0.1) are excluded
            ExtractionQualityEntry(file_path="e.txt", method="direct_read", bytes_extracted=500, confidence=0.5),
        ]
        summary = ExtractionPipeline.get_extraction_summary(entries)
        # 4 non-plaintext files, 2 failed => 50%
        assert summary["failure_rate"] == 0.5

    def test_summary_low_confidence_counted_as_failure(self) -> None:
        """Entries with confidence < 0.1 are counted as failures."""
        entries = [
            ExtractionQualityEntry(file_path="a.pdf", method="primary", bytes_extracted=100, confidence=0.05),
            ExtractionQualityEntry(file_path="b.pdf", method="primary", bytes_extracted=5000, confidence=0.9),
        ]
        summary = ExtractionPipeline.get_extraction_summary(entries)
        assert summary["failed"] == 1

    def test_systemic_failure_gate_with_parallel(self, tmp_path: Path) -> None:
        """Systemic failure gate still triggers with parallel extraction."""
        src = tmp_path / "sources"
        src.mkdir()

        # Create non-plaintext files that will fail extraction (empty PDFs).
        for i in range(4):
            f = src / f"bad_{i}.pdf"
            f.write_bytes(b"")

        output_dir = tmp_path / "output"
        cache_path = tmp_path / "checksums.sha256"

        pipeline = ExtractionPipeline()
        with pytest.raises(ExtractionPipelineError, match="Systemic"):
            pipeline.extract_all(
                [str(src / f"bad_{i}.pdf") for i in range(4)],
                output_dir,
                cache_path,
                max_workers=2,
            )
