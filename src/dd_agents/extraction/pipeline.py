"""Extraction pipeline -- orchestrates the fallback chain for all files.

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
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dd_agents.extraction._constants import IMAGE_EXTENSIONS, PLAINTEXT_EXTENSIONS
from dd_agents.extraction._helpers import read_text
from dd_agents.extraction.cache import ExtractionCache
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.ocr import OCRExtractor
from dd_agents.extraction.quality import ExtractionQualityTracker
from dd_agents.models.inventory import ExtractionQualityEntry

if TYPE_CHECKING:
    from dd_agents.extraction.glm_ocr import GlmOcrExtractor

logger = logging.getLogger(__name__)

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
    ".pdf": 0.09,  # pymupdf median from PathFactory audit (was 0.5)
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

        # --- cache ---
        cache = ExtractionCache(cache_path)
        cache.load()

        # --- quality tracker ---
        tracker = ExtractionQualityTracker()
        quality_json_path = output_dir / "extraction_quality.json"
        tracker.load(quality_json_path)

        primary_failures = 0
        total_non_plaintext = 0

        for filepath_str in files:
            filepath = Path(filepath_str)
            if not filepath.exists():
                tracker.record(
                    filepath=filepath_str,
                    method="failed",
                    bytes_extracted=0,
                    confidence=0.0,
                    fallback_chain=["missing"],
                )
                continue

            # Check cache
            current_hash = ExtractionCache.compute_checksum(filepath)
            out_file = output_dir / self._safe_text_name(filepath_str)

            if (
                cache.is_cached(filepath_str, current_hash)
                and out_file.exists()
                and out_file.stat().st_size >= _SCANNED_PDF_THRESHOLD
                and self._is_cached_output_readable(out_file)
            ):
                # Cache hit -- keep existing quality entry.
                cache.update(filepath_str, current_hash)
                continue

            # Not cached -- run extraction
            is_plaintext = filepath.suffix.lower() in PLAINTEXT_EXTENSIONS
            if not is_plaintext:
                total_non_plaintext += 1

            entry = self.extract_single(filepath, output_dir)
            tracker.record(
                filepath=filepath_str,
                method=entry.method,
                bytes_extracted=entry.bytes_extracted,
                confidence=entry.confidence,
                fallback_chain=entry.fallback_chain,
                failure_reasons=entry.failure_reasons,
            )

            if entry.confidence == 0.0 and not is_plaintext:
                primary_failures += 1

            cache.update(filepath_str, current_hash)

        # Remove stale cache entries for deleted files.
        cache.remove_stale(files)
        cache.save()

        # Persist quality.
        tracker.save(quality_json_path)

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

        # Suppress MuPDF C-level stderr messages (e.g. "premature end in
        # aes filter") — capture them via mupdf_warnings() instead.
        fitz.TOOLS.mupdf_display_errors(False)
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
            # 25/26 Identity-H PDFs in PathFactory extract cleanly.
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
            # Log any MuPDF warnings at debug level, then restore display.
            warnings = fitz.TOOLS.mupdf_warnings()
            if warnings:
                logger.debug("MuPDF warnings for %s: %s", filepath, warnings)
            fitz.TOOLS.mupdf_display_errors(True)
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

    def _extract_pdf(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """PDF fallback chain with pre-inspection routing.

        Pre-inspection classifies the PDF; scanned/missing_tounicode PDFs
        skip pymupdf+pdftotext to avoid garbled output.
        """
        chain: list[str] = []
        failure_reasons: list[str] = []
        pdf_type = self._inspect_pdf(filepath)

        # Skip text extractors for PDFs that would produce garbage.
        skip_text_extractors = pdf_type in ("scanned", "missing_tounicode", "encrypted")

        # 1. pymupdf — per-page extraction with explicit page markers.
        if not skip_text_extractors:
            text = self._run_pymupdf(filepath)
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
    def _run_pymupdf(filepath: Path) -> str:
        """Extract text page-by-page using ``pymupdf`` with explicit page markers.

        Injects ``--- Page N ---`` headers so that downstream LLM analysis
        can cite page numbers accurately.

        Returns empty string if pymupdf is not installed or extraction fails.
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            return ""

        # Suppress MuPDF C-level stderr messages; capture via warnings API.
        fitz.TOOLS.mupdf_display_errors(False)
        try:
            doc = fitz.open(str(filepath))
        except Exception as exc:
            logger.debug("pymupdf failed to open %s: %s", filepath, exc)
            fitz.TOOLS.mupdf_display_errors(True)
            return ""

        parts: list[str] = []
        try:
            for page_num, page in enumerate(doc, start=1):
                page_text = page.get_text()
                if page_text and page_text.strip():
                    parts.append(f"\n--- Page {page_num} ---\n\n{page_text}")
        except Exception as exc:
            logger.debug("pymupdf extraction error for %s: %s", filepath, exc)
        finally:
            warnings = fitz.TOOLS.mupdf_warnings()
            if warnings:
                logger.debug("MuPDF warnings for %s: %s", filepath, warnings)
            fitz.TOOLS.mupdf_display_errors(True)
            doc.close()

        return "\n".join(parts)

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
