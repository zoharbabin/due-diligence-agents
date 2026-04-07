"""Extraction pipeline -- orchestrates the fallback chain for all files.

PURPOSE: Extraction serves the **search/vector index** (TF-IDF, chunking,
vector store).  Specialist agents read original files directly via the
SDK Read tool — they do NOT depend on extracted text for analysis (Issue #87).
The verify_citation tool uses extracted text as a fallback for quote
verification.

The pipeline converts every data-room file to a single canonical
markdown representation.  PDFs are pre-inspected to route the chain:

    Normal:  pymupdf → pdftotext → markitdown → GLM-OCR → pytesseract → Claude vision → direct read
    Scanned: GLM-OCR → pytesseract → Claude vision → direct read
    Images:  markitdown → GLM-OCR → pytesseract → Claude vision → diagram placeholder

Extracted files are written as ``<safe_name>.md`` into the output
directory.  Unchanged files (SHA-256 match) are skipped.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from dd_agents.extraction._constants import (
    IMAGE_EXTENSIONS,
    PLAINTEXT_EXTENSIONS,
    SPREADSHEET_EXTENSIONS,
)
from dd_agents.extraction._helpers import read_text
from dd_agents.extraction.cache import ExtractionCache
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.ocr import OCRExtractor
from dd_agents.extraction.quality import ExtractionQualityTracker
from dd_agents.models.inventory import ExtractionQualityEntry

if TYPE_CHECKING:
    from dd_agents.extraction.glm_ocr import GlmOcrExtractor

logger = logging.getLogger(__name__)

# MuPDF (pymupdf) is NOT thread-safe.  Concurrent fitz.open() calls from
# the ThreadPoolExecutor can race on internal C state and cause segfaults.
# This lock serialises all pymupdf operations across worker threads.
_FITZ_LOCK = threading.Lock()

# Minimum characters for an extraction to be considered "successful".
_MIN_TEXT_LEN = 20

# Minimum ratio of printable characters for text to be considered readable
# (not binary garbage).  Scanned-PDF markitdown output is raw PDF binary
# (%PDF-1.x headers, stream objects, etc.) which has < 50 % printable chars.
_MIN_PRINTABLE_RATIO = 0.85

# Scanned-PDF detection threshold (per spec section 1).
_SCANNED_PDF_THRESHOLD = 100

# Minimum chars per page for a PDF to be considered text-based (not scanned).
_MIN_CHARS_PER_PAGE = 50

# Minimum characters for a "meaningful" extraction from primary methods
# (pymupdf, pdftotext).  Below this threshold the extraction falls through
# to the next method in the chain.  Addresses Bug H: near-empty PDFs
# that pass the per-page density check but contain too little text.
_MIN_EXTRACTION_CHARS = 500

# PDF magic bytes — cached outputs starting with this are raw binary, not text.
_PDF_MAGIC = b"%PDF-"

# Image magic bytes — binary image data decoded as UTF-8 fools isprintable()
# because U+FFFD (replacement char) is "printable".
_PNG_MAGIC = b"\x89PNG"
_JPEG_MAGIC_MARKERS = (b"\xff\xd8", b"\xff\xe0", b"\xff\xe1")

# Replacement character U+FFFD — indicates decoded binary, not real text.
_REPLACEMENT_CHAR = "\ufffd"
_MAX_REPLACEMENT_RATIO = 0.01  # >1% replacement chars → reject

# Confidence score for Claude vision descriptions.
_CONFIDENCE_CLAUDE_VISION = 0.65

# Timeout for Claude vision calls (seconds).
_CLAUDE_VISION_TIMEOUT = 120

# Threshold for control-character corruption detection (Issue #27 Phase 1).
# ASCII 0x00-0x1F excluding whitespace (\n\r\t\x0c).
_CONTROL_CHAR_THRESHOLD = 0.01

# Expected text-to-file-size ratios per format for confidence scaling
# (Issue #27 Phase 3).  Used by _scale_confidence() to penalize sparse
# extractions that technically pass quality gates but contain far less
# text than expected for the file size.
_EXPECTED_TEXT_RATIOS: dict[str, float] = {
    ".pdf": 0.09,  # pymupdf median from production audit (was 0.5)
    ".docx": 0.15,  # was 0.3
    ".doc": 0.15,  # was 0.3
    ".xlsx": 0.05,  # was 0.2
    ".xls": 0.05,  # was 0.2
    ".pptx": 0.05,  # was 0.2
    ".ppt": 0.05,  # was 0.2
    ".rtf": 0.25,  # was 0.4
    ".html": 0.35,  # was 0.6
    ".htm": 0.35,  # was 0.6
}

# Extensions that trigger the PDF branch of the fallback chain.
_PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

# Default number of parallel extraction workers (Issue #36).
_DEFAULT_WORKERS: int = min(8, os.cpu_count() or 4)


@dataclass
class _FileResult:
    """Result of processing a single file in a worker thread."""

    filepath_str: str
    current_hash: str | None = None
    entry: ExtractionQualityEntry | None = None
    is_missing: bool = False
    is_cache_hit: bool = False
    is_plaintext: bool = False


class ExtractionPipelineError(Exception):
    """Raised when >50 % of non-plaintext files fail extraction."""


class ExtractionPipeline:
    """Orchestrates extraction for an entire data room.

    Parameters
    ----------
    markitdown:
        Injected :class:`MarkitdownExtractor` (defaults to a new
        instance).
    ocr:
        Injected :class:`OCRExtractor` (defaults to a new instance).
    glm_ocr:
        Optional :class:`GlmOcrExtractor` for high-quality OCR.
    """

    def __init__(
        self,
        markitdown: MarkitdownExtractor | None = None,
        ocr: OCRExtractor | None = None,
        glm_ocr: GlmOcrExtractor | None = None,
    ) -> None:
        self._markitdown = markitdown or MarkitdownExtractor()
        self._ocr = ocr or OCRExtractor()
        self._glm_ocr = glm_ocr

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_all(
        self,
        files: list[str],
        output_dir: Path,
        cache_path: Path,
        *,
        max_workers: int | None = None,
    ) -> list[ExtractionQualityEntry]:
        """Extract all *files*, writing markdown output to *output_dir*.

        Parameters
        ----------
        files:
            List of source file paths (absolute or relative).
        output_dir:
            Directory for extracted ``.md`` files.
        cache_path:
            Path to ``checksums.sha256`` for caching.
        max_workers:
            Number of parallel extraction threads.  Defaults to
            ``min(8, os.cpu_count())``.

        Returns
        -------
        list[ExtractionQualityEntry]
            Quality record for every processed file.

        Raises
        ------
        ExtractionPipelineError
            If more than 50 % of non-plaintext files fail.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Suppress MuPDF C-level stderr globally for the entire extraction
        # run.  Without this, the per-method toggle (False/True) races across
        # threads: Thread A restores True in its finally block while Thread B
        # is still mid-extraction, causing MuPDF to dump raw warnings to stderr.
        # Warnings are still captured via fitz.TOOLS.mupdf_warnings() in each
        # method and logged at debug level.
        try:
            import fitz

            fitz.TOOLS.mupdf_display_errors(False)
        except ImportError:
            pass

        # --- cache ---
        # Thread-safety note: cache.is_cached() (read) is called from
        # worker threads, while cache.update() (write) is called only
        # in the main thread's as_completed() loop below.  Python's GIL
        # guarantees dict reads are atomic, so no lock is needed.
        cache = ExtractionCache(cache_path)
        cache.load()
        # Snapshot empty-state before workers start: if the cache file was
        # wiped/missing we trust existing readable output on disk.  Captured
        # once so that main-thread cache.update() calls don't invalidate the
        # flag mid-run (race between main thread writes and worker reads).
        cache_was_empty = len(cache) == 0
        if cache_was_empty:
            logger.info("Checksum cache is empty — will skip extraction for files with existing readable output")

        # --- quality tracker (protected by lock for thread safety) ---
        tracker = ExtractionQualityTracker()
        quality_json_path = output_dir / "extraction_quality.json"
        tracker.load(quality_json_path)
        tracker_lock = threading.Lock()

        primary_failures = 0
        total_non_plaintext = 0
        cache_hits = 0
        fresh_extractions = 0

        workers = max_workers if max_workers is not None else _DEFAULT_WORKERS
        total_files = len(files)
        # Progress logging interval: every 10 files or 10%, whichever is larger.
        progress_interval = max(10, total_files // 10) if total_files > 0 else 10
        completed = 0

        def _process_file(filepath_str: str) -> _FileResult:
            """Process a single file in a worker thread."""
            filepath = Path(filepath_str)
            if not filepath.exists():
                return _FileResult(
                    filepath_str=filepath_str,
                    is_missing=True,
                )

            # Check cache
            current_hash = ExtractionCache.compute_checksum(filepath)
            out_file = output_dir / self._safe_text_name(filepath_str)

            if (
                out_file.exists()
                and out_file.stat().st_size >= _SCANNED_PDF_THRESHOLD
                and self._is_cached_output_readable(out_file)
                and (cache.is_cached(filepath_str, current_hash) or cache_was_empty)
            ):
                # Cache hit, or cache is empty but readable output exists
                # from a prior run (e.g. checksums file was wiped).
                return _FileResult(
                    filepath_str=filepath_str,
                    current_hash=current_hash,
                    is_cache_hit=True,
                )

            # Not cached -- run extraction
            is_plaintext = filepath.suffix.lower() in PLAINTEXT_EXTENSIONS
            entry = self.extract_single(filepath, output_dir)
            return _FileResult(
                filepath_str=filepath_str,
                current_hash=current_hash,
                entry=entry,
                is_plaintext=is_plaintext,
            )

        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_filepath = {executor.submit(_process_file, fp): fp for fp in files}

        try:
            for future in as_completed(future_to_filepath):
                try:
                    result = future.result()
                except Exception:
                    fp = future_to_filepath[future]
                    logger.exception("Worker thread crashed processing %s", fp)
                    result = _FileResult(
                        filepath_str=fp,
                        is_missing=False,
                        is_cache_hit=False,
                        is_plaintext=Path(fp).suffix.lower() in PLAINTEXT_EXTENSIONS,
                        current_hash=None,
                        entry=ExtractionQualityEntry(
                            file_path=fp,
                            method="failed",
                            bytes_extracted=0,
                            confidence=0.0,
                            fallback_chain=["crashed"],
                            failure_reasons=["Worker thread crashed"],
                        ),
                    )

                if result.is_missing:
                    with tracker_lock:
                        tracker.record(
                            filepath=result.filepath_str,
                            method="failed",
                            bytes_extracted=0,
                            confidence=0.0,
                            fallback_chain=["missing"],
                        )
                elif result.is_cache_hit:
                    cache_hits += 1
                    cache.update(result.filepath_str, result.current_hash or "")
                elif result.entry is not None:
                    fresh_extractions += 1
                    if not result.is_plaintext:
                        total_non_plaintext += 1

                    with tracker_lock:
                        tracker.record(
                            filepath=result.filepath_str,
                            method=result.entry.method,
                            bytes_extracted=result.entry.bytes_extracted,
                            confidence=result.entry.confidence,
                            fallback_chain=result.entry.fallback_chain,
                            failure_reasons=result.entry.failure_reasons,
                        )

                    if result.entry.confidence == 0.0 and not result.is_plaintext:
                        primary_failures += 1

                    cache.update(result.filepath_str, result.current_hash or "")

                completed += 1
                if completed % progress_interval == 0 or completed == total_files:
                    pct = (completed / total_files * 100) if total_files > 0 else 100
                    logger.info(
                        "Extraction progress: %d/%d files (%.0f%%)",
                        completed,
                        total_files,
                        pct,
                    )
        except KeyboardInterrupt:
            logger.warning("Extraction interrupted — cancelling pending files")
            for f in future_to_filepath:
                f.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=False)

        # Remove stale cache entries for deleted files.
        cache.remove_stale(files)
        cache.save()

        # Persist quality.
        tracker.save(quality_json_path)

        # Log extraction summary.
        if cache_hits > 0:
            logger.info(
                "Extraction: %d/%d files cached (skipped), %d extracted",
                cache_hits,
                total_files,
                fresh_extractions,
            )
        summary = self.get_extraction_summary(tracker.entries)
        logger.info(
            "Extraction complete: %d/%d files succeeded (%.0f%%), methods: %s",
            summary["succeeded"],
            summary["total"],
            (1.0 - summary["failure_rate"]) * 100 if summary["total"] > 0 else 100,
            ", ".join(f"{m}={c}" for m, c in sorted(summary["by_method"].items())),
        )

        # Systemic failure gate.
        if total_non_plaintext > 0:
            failure_rate = primary_failures / total_non_plaintext
            if failure_rate > 0.50:
                raise ExtractionPipelineError(
                    f"Systemic extraction failure: {primary_failures}/"
                    f"{total_non_plaintext} files ({failure_rate:.0%}) failed.  "
                    f"Check markitdown installation and file access permissions."
                )

        return tracker.entries

    @staticmethod
    def get_extraction_summary(
        entries: list[ExtractionQualityEntry],
    ) -> dict[str, Any]:
        """Return a summary dict with method counts and failure rate.

        Parameters
        ----------
        entries:
            Quality entries from an extraction run.

        Returns
        -------
        dict
            Keys: ``total``, ``succeeded``, ``failed``,
            ``failure_rate``, ``by_method``.
        """
        total = len(entries)
        by_method: dict[str, int] = {}
        failed = 0
        total_non_plaintext = 0

        for entry in entries:
            by_method[entry.method] = by_method.get(entry.method, 0) + 1
            # Count non-plaintext failures: method == "failed" or confidence < 0.1
            # Plaintext files (direct_read with confidence > 0) are excluded.
            is_failure = entry.method == "failed" or entry.confidence < 0.1
            # Heuristic: direct_read with decent confidence are plaintext files.
            is_likely_plaintext = entry.method == "direct_read" and entry.confidence >= 0.1
            if not is_likely_plaintext:
                total_non_plaintext += 1
                if is_failure:
                    failed += 1

        failure_rate = (failed / total_non_plaintext) if total_non_plaintext > 0 else 0.0

        return {
            "total": total,
            "succeeded": total - by_method.get("failed", 0),
            "failed": failed,
            "failure_rate": round(failure_rate, 4),
            "by_method": by_method,
        }

    def extract_single(
        self,
        filepath: Path,
        output_dir: Path,
    ) -> ExtractionQualityEntry:
        """Extract a single file using the appropriate fallback chain.

        The extracted markdown is written to
        ``output_dir / <safe_name>.md``.

        Returns
        -------
        ExtractionQualityEntry
            Quality record for the file.
        """
        out_file = output_dir / self._safe_text_name(str(filepath))
        out_file.parent.mkdir(parents=True, exist_ok=True)

        suffix = filepath.suffix.lower()

        if suffix in PLAINTEXT_EXTENSIONS:
            return self._extract_plaintext(filepath, out_file)

        if suffix in SPREADSHEET_EXTENSIONS:
            return self._extract_spreadsheet(filepath, out_file)

        if suffix in _PDF_EXTENSIONS:
            return self._extract_pdf(filepath, out_file)

        if suffix in IMAGE_EXTENSIONS:
            return self._extract_image(filepath, out_file)

        # Office / other formats -- markitdown then direct read.
        return self._extract_generic(filepath, out_file)

    # ------------------------------------------------------------------
    # PDF pre-inspection (Issue #27 Phase 1)
    # ------------------------------------------------------------------

    @staticmethod
    def _inspect_pdf(filepath: Path) -> Literal["normal", "missing_tounicode", "scanned", "encrypted"]:
        """Classify a PDF before extraction to route the fallback chain.

        Returns one of:
        - ``"encrypted"`` — document is password-protected.
        - ``"scanned"`` — first page has < 100 text characters.
        - ``"missing_tounicode"`` — fonts use Identity-H encoding without
          a /ToUnicode CMap, producing garbled control bytes.
        - ``"normal"`` — text-based PDF suitable for pymupdf/pdftotext.

        All pymupdf calls are wrapped in try/except; returns ``"normal"``
        on any error (graceful degradation).
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            return "normal"

        with _FITZ_LOCK:
            try:
                doc = fitz.open(str(filepath))
            except Exception:
                return "normal"

            try:
                if doc.is_encrypted:
                    return "encrypted"

                if len(doc) == 0:
                    return "scanned"

                page = doc[0]
                page_text = page.get_text()
                text_len = len(page_text.strip()) if page_text else 0

                if text_len < _SCANNED_PDF_THRESHOLD:
                    return "scanned"

                # Check for Identity-H fonts — only flag as missing_tounicode
                # if the extracted text also has control-char corruption.
                # 25/26 Identity-H PDFs in production data rooms extract cleanly.
                has_identity_h = False
                fonts = page.get_fonts(full=True)
                for font in fonts:
                    # font tuple: (xref, ext, type, basefont, name, encoding, ...)
                    encoding = font[5] if len(font) > 5 else ""
                    if isinstance(encoding, str) and "Identity-H" in encoding:
                        has_identity_h = True
                        break

                if has_identity_h and ExtractionPipeline._has_control_char_corruption(page_text):
                    return "missing_tounicode"

                return "normal"
            except Exception:
                return "normal"
            finally:
                # Drain MuPDF C-level warnings buffer (stderr is already
                # suppressed globally).  These are internal PDF library
                # diagnostics (e.g. "repaired broken tree structure",
                # "bogus font ascent") that don't affect extraction.
                fitz.TOOLS.mupdf_warnings()
                doc.close()

    @staticmethod
    def _has_control_char_corruption(text: str, threshold: float = _CONTROL_CHAR_THRESHOLD) -> bool:
        """Return *True* if *text* has excessive ASCII control characters.

        Counts bytes 0x00-0x1F excluding whitespace (``\\n\\r\\t\\x0c``).
        A ratio above *threshold* (default 1%) indicates garbled output
        from PDFs with missing /ToUnicode CMap entries.
        """
        if not text:
            return False
        allowed = frozenset("\n\r\t\x0c")
        control = sum(1 for ch in text if "\x00" <= ch <= "\x1f" and ch not in allowed)
        return control / len(text) > threshold

    # ------------------------------------------------------------------
    # Unified try-method helper (Issue #27 Phase 2)
    # ------------------------------------------------------------------

    def _try_method(
        self,
        name: str,
        text: str | None,
        confidence: float,
        out_file: Path,
        filepath: Path,
        chain: list[str],
        failure_reasons: list[str],
        method_label: str,
        *,
        min_chars: int = _MIN_TEXT_LEN,
        check_density: bool = False,
        check_readability: bool = False,
        check_watermark: bool = False,
        check_control_chars: bool = False,
    ) -> ExtractionQualityEntry | None:
        """Try an extraction method, applying quality gates uniformly.

        Appends *name* to *chain* BEFORE gate checks so failed methods
        appear in ``fallback_chain``.  Appends diagnostic strings to
        *failure_reasons* on gate failure.

        Returns an :class:`ExtractionQualityEntry` on success, *None* on
        gate failure.
        """
        chain.append(name)

        if not text or len(text.strip()) < min_chars:
            failure_reasons.append(f"{name}: too short ({len(text.strip()) if text else 0} < {min_chars})")
            return None

        stripped_len = len(text.strip())

        if check_density:
            page_count = self._count_pages_in_text(text)
            is_dense = stripped_len >= _MIN_EXTRACTION_CHARS and (
                page_count <= 1 or stripped_len / page_count >= _MIN_CHARS_PER_PAGE
            )
            if not is_dense:
                failure_reasons.append(f"{name}: low density ({stripped_len} chars, {page_count} pages)")
                return None

        if check_readability and not self._is_readable_text(text):
            failure_reasons.append(f"{name}: failed readability check")
            return None

        if check_watermark and self._is_watermark_only(text):
            failure_reasons.append(f"{name}: watermark-only content")
            return None

        if check_control_chars and self._has_control_char_corruption(text):
            failure_reasons.append(f"{name}: control-char corruption detected")
            return None

        # All gates passed — write output and return entry.
        out_file.write_text(text, encoding="utf-8")
        scaled = self._scale_confidence(confidence, stripped_len, filepath)
        return ExtractionQualityEntry(
            file_path=str(filepath),
            method=method_label,
            bytes_extracted=len(text.encode("utf-8")),
            confidence=scaled,
            fallback_chain=list(chain),
            failure_reasons=list(failure_reasons),
        )

    # ------------------------------------------------------------------
    # Confidence scaling (Issue #27 Phase 3)
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_confidence(base: float, actual_chars: int, filepath: Path) -> float:
        """Scale *base* confidence by how much text was extracted vs expected.

        Uses file-size-to-text ratios per format.  Returns *base* unchanged
        if the file does not exist, has unknown extension, or actual text
        meets or exceeds expectations.
        """
        suffix = filepath.suffix.lower()
        ratio = _EXPECTED_TEXT_RATIOS.get(suffix)
        if ratio is None:
            return base

        try:
            file_size = filepath.stat().st_size
        except OSError:
            return base

        if file_size == 0:
            return base

        expected_chars = int(file_size * ratio)
        if expected_chars == 0:
            return base

        scale = min(1.0, actual_chars / expected_chars)
        return round(base * scale, 4)

    # ------------------------------------------------------------------
    # Extraction strategies
    # ------------------------------------------------------------------

    def _extract_plaintext(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Read plain-text files directly."""
        chain: list[str] = ["direct_read"]
        text, confidence = self._read_text(filepath)
        if text:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="direct_read",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=confidence,
                fallback_chain=chain,
            )
        return self._failed_entry(filepath, chain)

    def _extract_spreadsheet(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Extract spreadsheet files using native Python libraries.

        Uses openpyxl for .xlsx, csv/tsv module for delimited files,
        and falls back to markitdown → direct read for .xls (legacy format).
        """
        suffix = filepath.suffix.lower()
        chain: list[str] = []
        failure_reasons: list[str] = []

        text: str | None = None
        conf = 0.0

        if suffix == ".xlsx":
            text, conf = self._read_xlsx(filepath)
            chain.append("openpyxl")
            if text:
                entry = self._try_method(
                    "openpyxl",
                    text,
                    conf,
                    out_file,
                    filepath,
                    chain,
                    failure_reasons,
                    method_label="primary",
                )
                if entry is not None:
                    return entry

        elif suffix in (".csv", ".tsv"):
            text, conf = self._read_delimited(filepath, suffix)
            chain.append("csv_reader")
            if text:
                entry = self._try_method(
                    "csv_reader",
                    text,
                    conf,
                    out_file,
                    filepath,
                    chain,
                    failure_reasons,
                    method_label="primary",
                )
                if entry is not None:
                    return entry

        # .xls or fallback for failed xlsx/csv: try markitdown then direct read.
        md_text, md_conf = self._markitdown.extract(filepath)
        entry = self._try_method(
            "markitdown",
            md_text,
            md_conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_read" if chain else "primary",
        )
        if entry is not None:
            return entry

        # Last resort: direct text read.
        raw_text, raw_conf = self._read_text(filepath)
        entry = self._try_method(
            "direct_read",
            raw_text,
            raw_conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_read",
        )
        if entry is not None:
            return entry

        return self._failed_entry(filepath, chain, failure_reasons=failure_reasons)

    @staticmethod
    def _read_xlsx(filepath: Path) -> tuple[str | None, float]:
        """Read .xlsx using the read_office tool's openpyxl-based reader.

        Reuses read_office._read_excel which handles date→ISO-8601,
        currency/percentage formatting, and sub-table detection.
        """
        try:
            from dd_agents.tools.read_office import _read_excel

            text = _read_excel(filepath, sheet_name=None)
            if not text or not text.strip():
                return None, 0.0
            return text, 0.9
        except Exception as exc:
            logger.debug("openpyxl failed for %s: %s", filepath.name, exc)
            return None, 0.0

    @staticmethod
    def _read_delimited(filepath: Path, suffix: str) -> tuple[str | None, float]:
        """Read CSV/TSV files with proper dialect handling."""
        import csv as csv_mod

        def _esc(val: str) -> str:
            """Escape pipe and newline for markdown table cells."""
            return val.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("|", "\\|")

        delimiter = "\t" if suffix == ".tsv" else ","
        try:
            with open(filepath, encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv_mod.reader(fh, delimiter=delimiter)
                rows: list[list[str]] = []
                for row in reader:
                    if any(cell.strip() for cell in row):
                        rows.append([_esc(c) for c in row])
                    if len(rows) >= 50_000:  # safety cap for huge files
                        break

            if not rows:
                return None, 0.0

            parts: list[str] = []
            header = rows[0]
            parts.append("| " + " | ".join(header) + " |")
            parts.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows[1:]:
                padded = row + [""] * (len(header) - len(row))
                parts.append("| " + " | ".join(padded[: len(header)]) + " |")

            text = "\n".join(parts).strip()
            return text, 0.85
        except Exception as exc:
            logger.debug("csv_reader failed for %s: %s", filepath.name, exc)
            return None, 0.0

    def _extract_pdf(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """PDF fallback chain with pre-inspection routing.

        Pre-inspection classifies the PDF; scanned/missing_tounicode PDFs
        skip pymupdf+pdftotext to avoid garbled output.
        """
        chain: list[str] = []
        failure_reasons: list[str] = []
        pdf_type = self._inspect_pdf(filepath)

        # Encrypted PDFs cannot be extracted by any method — short-circuit
        # immediately to avoid noisy tracebacks from every backend.
        if pdf_type == "encrypted":
            logger.info("Skipping password-protected PDF: %s", filepath.name)
            chain.append("encrypted")
            failure_reasons.append("Password-protected PDF")
            return self._failed_entry(filepath, chain, failure_reasons=failure_reasons)

        # Skip text extractors for PDFs that would produce garbage.
        skip_text_extractors = pdf_type in ("scanned", "missing_tounicode")

        # 1. pymupdf — per-page extraction with explicit page markers.
        if not skip_text_extractors:
            pymupdf_result = self._run_pymupdf(filepath)
            text = pymupdf_result if isinstance(pymupdf_result, str) else pymupdf_result[0]
            entry = self._try_method(
                "pymupdf",
                text,
                0.9,
                out_file,
                filepath,
                chain,
                failure_reasons,
                method_label="primary",
                min_chars=_MIN_EXTRACTION_CHARS,
                check_density=True,
                check_watermark=True,
                check_control_chars=True,
            )
            if entry is not None:
                return entry

            # 2. pdftotext (poppler CLI).
            text = self._run_pdftotext(filepath)
            entry = self._try_method(
                "pdftotext",
                text,
                0.7,
                out_file,
                filepath,
                chain,
                failure_reasons,
                method_label="fallback_pdftotext",
                min_chars=_MIN_EXTRACTION_CHARS,
                check_density=True,
                check_watermark=True,
                check_control_chars=True,
            )
            if entry is not None:
                return entry

            # 3. markitdown — only for "normal" PDFs where pymupdf/pdftotext
            #    failed.  markitdown uses pdfminer internally and cannot
            #    extract text from images any better than pymupdf.
            text, conf = self._markitdown.extract(filepath)
            entry = self._try_method(
                "markitdown",
                text,
                conf,
                out_file,
                filepath,
                chain,
                failure_reasons,
                method_label="fallback_markitdown",
                min_chars=_SCANNED_PDF_THRESHOLD,
                check_readability=True,
                check_control_chars=True,
            )
            if entry is not None:
                return entry

        # 4. GLM-OCR (optional, higher quality than pytesseract).
        if self._glm_ocr is not None:
            text, conf = self._glm_ocr.extract(filepath)
            entry = self._try_method(
                "glm_ocr",
                text,
                conf,
                out_file,
                filepath,
                chain,
                failure_reasons,
                method_label="fallback_glm_ocr",
            )
            if entry is not None:
                return entry

        # 5. pytesseract OCR.
        text, conf = self._ocr.extract(filepath)
        entry = self._try_method(
            "ocr",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_ocr",
        )
        if entry is not None:
            return entry

        # 6. Claude vision (last resort for unreadable PDFs).
        text, conf = self._try_claude_vision(filepath)
        entry = self._try_method(
            "claude_vision",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_claude_vision",
        )
        if entry is not None:
            return entry

        # 7. Raw read (final fallback).
        text, conf = self._read_text(filepath)
        entry = self._try_method(
            "direct_read",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_read",
        )
        if entry is not None:
            return entry

        return self._failed_entry(filepath, chain, failure_reasons=failure_reasons)

    def _extract_image(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Image fallback chain: markitdown -> GLM-OCR -> pytesseract -> Claude vision -> diagram placeholder."""
        chain: list[str] = []
        failure_reasons: list[str] = []

        # 1. markitdown — readability gate rejects binary image data.
        text, conf = self._markitdown.extract(filepath)
        entry = self._try_method(
            "markitdown",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
            check_readability=True,
        )
        if entry is not None:
            return entry

        # 2. GLM-OCR (optional).
        if self._glm_ocr is not None:
            text, conf = self._glm_ocr.extract(filepath)
            entry = self._try_method(
                "glm_ocr",
                text,
                conf,
                out_file,
                filepath,
                chain,
                failure_reasons,
                method_label="fallback_glm_ocr",
            )
            if entry is not None:
                return entry

        # 3. pytesseract.
        text, conf = self._ocr.extract(filepath)
        entry = self._try_method(
            "ocr",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_ocr",
        )
        if entry is not None:
            return entry

        # 4. Claude vision (last resort for unreadable images).
        text, conf = self._try_claude_vision(filepath)
        entry = self._try_method(
            "claude_vision",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_claude_vision",
        )
        if entry is not None:
            return entry

        # Write a diagram placeholder.
        placeholder = (
            f"[DIAGRAM/IMAGE: {filepath}]\n"
            f"This image could not be OCR-extracted.  "
            f"Use the Read tool to visually examine this file.\n"
        )
        out_file.write_text(placeholder, encoding="utf-8")
        chain.append("diagram_placeholder")
        return ExtractionQualityEntry(
            file_path=str(filepath),
            method="fallback_read",
            bytes_extracted=len(placeholder.encode("utf-8")),
            confidence=0.3,
            fallback_chain=chain,
            failure_reasons=failure_reasons,
        )

    def _extract_generic(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Generic (Office/other) fallback chain: markitdown -> direct read."""
        chain: list[str] = []
        failure_reasons: list[str] = []

        # 1. markitdown.
        text, conf = self._markitdown.extract(filepath)
        entry = self._try_method(
            "markitdown",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="primary",
        )
        if entry is not None:
            return entry

        # 2. Direct text read.
        text, conf = self._read_text(filepath)
        entry = self._try_method(
            "direct_read",
            text,
            conf,
            out_file,
            filepath,
            chain,
            failure_reasons,
            method_label="fallback_read",
        )
        if entry is not None:
            return entry

        return self._failed_entry(filepath, chain, failure_reasons=failure_reasons)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_text_name(source_path: str) -> str:
        """Convert a source file path to a safe extracted-text filename.

        Convention: strip leading ``./``, replace ``/`` with ``__``,
        append ``.md``.  If the resulting name exceeds 200 characters
        it is truncated and a short hash suffix is appended to
        guarantee uniqueness (macOS enforces a 255-byte filename limit).
        """
        name = source_path.removeprefix("./")
        name = name.replace("/", "__")
        full = f"{name}.md"

        # macOS HFS+/APFS limit is 255 bytes; keep well under.
        max_len = 200
        if len(full.encode("utf-8")) <= max_len:
            return full

        digest = hashlib.sha256(source_path.encode()).hexdigest()[:12]
        # Truncate the name portion, keep .md suffix
        truncated = name.encode("utf-8")[: max_len - len(digest) - 4].decode("utf-8", errors="ignore")
        return f"{truncated}_{digest}.md"

    @staticmethod
    def _run_pymupdf(
        filepath: Path,
        *,
        capture_blocks: bool = False,
    ) -> str | tuple[str, list[dict[str, Any]]]:
        """Extract text page-by-page using ``pymupdf`` with explicit page markers.

        Injects ``--- Page N ---`` headers so that downstream LLM analysis
        can cite page numbers accurately.

        Parameters
        ----------
        capture_blocks:
            When *True*, also capture block-level coordinate data for
            visual grounding (Issue #7).  Returns ``(text, blocks)``
            instead of just ``text``.

        Returns empty string (or ``("", [])``) if pymupdf is not installed
        or extraction fails.
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            return ("", []) if capture_blocks else ""

        parts: list[str] = []
        blocks: list[dict[str, Any]] = []
        with _FITZ_LOCK:
            try:
                doc = fitz.open(str(filepath))
            except Exception as exc:
                logger.debug("pymupdf failed to open %s: %s", filepath, exc)
                return ("", []) if capture_blocks else ""

            try:
                for page_num, page in enumerate(doc, start=1):
                    page_text = page.get_text()
                    if page_text and page_text.strip():
                        parts.append(f"\n--- Page {page_num} ---\n\n{page_text}")
                    if capture_blocks:
                        for block in page.get_text("blocks"):
                            # block: (x0, y0, x1, y1, text, block_no, type)
                            if len(block) >= 7 and block[6] == 0:  # type 0 = text
                                text_content = str(block[4]).strip()
                                if text_content:
                                    blocks.append(
                                        {
                                            "page": page_num,
                                            "x0": float(block[0]),
                                            "y0": float(block[1]),
                                            "x1": float(block[2]),
                                            "y1": float(block[3]),
                                            "text": text_content,
                                        }
                                    )
            except Exception as exc:
                logger.debug("pymupdf extraction error for %s: %s", filepath, exc)
            finally:
                # Drain MuPDF C-level warnings buffer (stderr is already
                # suppressed globally).  These are internal PDF library
                # diagnostics (e.g. "repaired broken tree structure",
                # "bogus font ascent") that don't affect extraction.
                fitz.TOOLS.mupdf_warnings()
                doc.close()

        text = "\n".join(parts)
        if capture_blocks:
            return text, blocks
        return text

    @staticmethod
    def _run_pdftotext(filepath: Path) -> str:
        """Run ``pdftotext`` (poppler) on a PDF, returning extracted text.

        Converts form-feed characters (``\\f``) to ``--- Page N ---``
        markers for citation accuracy.
        """
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(filepath), "-"],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0:
                raw = result.stdout.decode("utf-8", errors="replace")
                # Convert form-feed page separators to explicit markers.
                pages = raw.split("\f")
                parts: list[str] = []
                for i, page_text in enumerate(pages, start=1):
                    if page_text.strip():
                        parts.append(f"\n--- Page {i} ---\n\n{page_text}")
                return "\n".join(parts)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return ""

    @staticmethod
    def _count_pages_in_text(text: str) -> int:
        """Count ``--- Page N ---`` markers in extracted text."""
        markers = re.findall(r"\n--- Page \d+ ---\n", text)
        return len(markers) if markers else 1

    @staticmethod
    def _check_text_quality(sample: str) -> bool:
        """Return *True* if *sample* passes U+FFFD and printable-ratio checks."""
        replacement_count = sample.count(_REPLACEMENT_CHAR)
        if replacement_count / max(len(sample), 1) > _MAX_REPLACEMENT_RATIO:
            return False
        printable = sum(1 for ch in sample if ch != _REPLACEMENT_CHAR and (ch.isprintable() or ch in "\n\r\t"))
        return printable / max(len(sample), 1) >= _MIN_PRINTABLE_RATIO

    @staticmethod
    def _is_cached_output_readable(out_file: Path) -> bool:
        """Check if a cached ``.md`` output file contains readable text.

        Reads a small sample from disk to avoid loading multi-MB binary
        garbage into memory.  Returns *False* for binary PDF dumps so
        they get re-extracted through the improved fallback chain.

        Three-layer check:
        1. Magic-byte signatures — PDF, PNG, JPEG raw binary.
        2. Replacement-character gate — >1 % U+FFFD indicates decoded binary.
        3. Printable ratio (excluding U+FFFD) — catches other binary garbage.
        """
        try:
            raw = out_file.read_bytes()[:10_000]
            stripped_raw = raw.lstrip()
            if stripped_raw[:5] == _PDF_MAGIC:
                return False
            if stripped_raw[:4] == _PNG_MAGIC:
                return False
            if any(stripped_raw[:2] == m for m in _JPEG_MAGIC_MARKERS):
                return False
            sample = raw.decode("utf-8", errors="replace")
            return ExtractionPipeline._check_text_quality(sample)
        except OSError:
            return False

    @staticmethod
    def _is_watermark_only(text: str) -> bool:
        """Return *True* if extracted PDF text is dominated by repeated watermarks.

        Detects scanned PDFs where pymupdf/pdftotext can only read a
        transparent overlay (e.g. DocuSign envelope IDs) but not the
        actual page content underneath.  Heuristic: if >50 % of
        non-blank, non-marker lines are identical repeated strings the
        extraction is almost certainly a watermark artifact.
        """
        if not text:
            return False
        lines = [
            ln.strip() for ln in text.split("\n") if ln.strip() and not re.match(r"^--- Page \d+ ---$", ln.strip())
        ]
        if len(lines) < 4:
            return False

        counts = Counter(lines)
        _line, most_common_count = counts.most_common(1)[0]
        # If a single line accounts for >50% of content lines, it's a watermark
        return most_common_count / len(lines) > 0.5

    @staticmethod
    def _is_readable_text(text: str, *, sample_size: int = 10_000) -> bool:
        """Return *True* if *text* looks like human-readable content.

        Five-layer check:
        1. PDF signature — rejects raw PDF binary that some extractors
           dump verbatim (linearized PDFs can fool the ratio check).
        2. PNG magic — rejects binary PNG decoded as latin-1 text.
        3. JPEG magic — rejects binary JPEG decoded as latin-1 text.
        4. Replacement-character gate — >1 % U+FFFD indicates binary
           decoded as UTF-8 with ``errors='replace'``.
        5. Printable ratio (excluding U+FFFD) — catches other binary garbage.
        """
        if not text:
            return False
        stripped = text.lstrip()
        if stripped[:5] == "%PDF-":
            return False
        # Image magic: when binary is decoded with latin-1 (the _read_text
        # fallback encoding), bytes map 1:1 to Unicode codepoints, so the
        # magic survives as string characters.  E.g. b"\x89PNG" → "\x89PNG".
        if stripped[:4] == "\x89PNG":
            return False
        if stripped[:2] in ("\xff\xd8", "\xff\xe0", "\xff\xe1"):
            return False
        sample = text[:sample_size]
        return ExtractionPipeline._check_text_quality(sample)

    # ------------------------------------------------------------------
    # Claude vision last-resort (Issue #27)
    # ------------------------------------------------------------------

    @staticmethod
    async def _describe_image_async(filepath: Path) -> str:
        """Use Claude Agent SDK to visually describe an image or PDF.

        Returns a text description or empty string on failure.
        """
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            query,
        )

        system_prompt = (
            "You are a document-analysis assistant.  The user will ask you "
            "to read an image file.  Respond with:\n"
            "1. ALL text visible in the image, transcribed verbatim.\n"
            "2. A description of any tables, charts, or diagrams with their data.\n"
            "3. A note about any signatures, logos, or stamps.\n"
            "If no text is visible, describe the visual content in detail."
        )

        user_prompt = f"Use the Read tool to visually examine this file and describe everything you see: {filepath}"

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            max_turns=1,
            permission_mode="bypassPermissions",
            disallowed_tools=["Edit", "Write", "Bash", "Glob", "Grep", "WebFetch", "Task", "NotebookEdit"],
        )

        text_parts: list[str] = []
        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                elif isinstance(message, ResultMessage) and message.is_error:
                    logger.debug("Claude vision error for %s: %s", filepath, message.result)
                    return ""
        except Exception as exc:
            logger.debug("Claude vision failed for %s: %s", filepath, exc)
            return ""

        return "\n".join(text_parts)

    @staticmethod
    def _try_claude_vision(filepath: Path) -> tuple[str, float]:
        """Synchronous wrapper for :meth:`_describe_image_async`.

        The pipeline is synchronous but may be called from within a
        running asyncio event loop.  Uses a separate thread to run the
        async query safely.

        Returns ``(text, confidence)`` on success, ``("", 0.0)`` on failure.
        """
        import asyncio as _asyncio
        from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor

        def _run() -> str:
            return _asyncio.run(ExtractionPipeline._describe_image_async(filepath))

        try:
            with _ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run)
                result = future.result(timeout=_CLAUDE_VISION_TIMEOUT)
        except Exception as exc:
            logger.debug("Claude vision timed out or failed for %s: %s", filepath, exc)
            return "", 0.0

        if result and result.strip():
            return result, _CONFIDENCE_CLAUDE_VISION
        return "", 0.0

    @staticmethod
    def _read_text(filepath: Path) -> tuple[str, float]:
        """Read *filepath* as plain text (UTF-8, then latin-1)."""
        return read_text(filepath)

    @staticmethod
    def _failed_entry(
        filepath: Path,
        chain: list[str],
        *,
        failure_reasons: list[str] | None = None,
    ) -> ExtractionQualityEntry:
        """Return a failed quality entry."""
        return ExtractionQualityEntry(
            file_path=str(filepath),
            method="failed",
            bytes_extracted=0,
            confidence=0.0,
            fallback_chain=chain,
            failure_reasons=failure_reasons or [],
        )
