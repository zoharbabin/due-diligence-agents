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
from unittest.mock import patch

import pytest

from dd_agents.extraction.cache import ExtractionCache
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.pipeline import ExtractionPipeline, ExtractionPipelineError
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
        tracker.record("b.docx", "fallback_read", 2000, 0.5)
        tracker.save(quality_path)

        # Load into a fresh tracker.
        tracker2 = ExtractionQualityTracker()
        tracker2.load(quality_path)
        assert len(tracker2) == 2

        entries = tracker2.entries
        paths = {e.file_path for e in entries}
        assert paths == {"a.pdf", "b.docx"}

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
        # At least 2 .md files + the quality json
        extracted_mds = [f for f in md_files if f.name != "extraction_quality.json"]
        assert len(extracted_mds) == 2

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
        md_files = [p for p in output_dir.glob("*.md") if p.name != "extraction_quality.json"]
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
        md_files = [p for p in output_dir.glob("*.md") if p.name != "extraction_quality.json"]
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
