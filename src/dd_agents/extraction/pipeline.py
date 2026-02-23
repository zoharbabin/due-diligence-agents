"""Extraction pipeline -- orchestrates the fallback chain for all files.

The pipeline converts every data-room file to a single canonical
markdown representation.  The fallback chain is:

    markitdown -> pdftotext (CLI) -> pytesseract -> direct text read

Extracted files are written as ``<safe_name>.md`` into the output
directory.  Unchanged files (SHA-256 match) are skipped.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from dd_agents.extraction.cache import ExtractionCache
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.ocr import OCRExtractor
from dd_agents.extraction.quality import ExtractionQualityTracker
from dd_agents.models.inventory import ExtractionQualityEntry

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

# Extensions read directly without extraction.
_PLAINTEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".csv",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".log",
        ".tsv",
        ".ini",
        ".cfg",
        ".conf",
    }
)

# Extensions that trigger the PDF branch of the fallback chain.
_PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

# Image extensions that go through the OCR branch.
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".gif",
    }
)


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
    """

    def __init__(
        self,
        markitdown: MarkitdownExtractor | None = None,
        ocr: OCRExtractor | None = None,
    ) -> None:
        self._markitdown = markitdown or MarkitdownExtractor()
        self._ocr = ocr or OCRExtractor()

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
            is_plaintext = filepath.suffix.lower() in _PLAINTEXT_EXTENSIONS
            if not is_plaintext:
                total_non_plaintext += 1

            entry = self.extract_single(filepath, output_dir)
            tracker.record(
                filepath=filepath_str,
                method=entry.method,
                bytes_extracted=entry.bytes_extracted,
                confidence=entry.confidence,
                fallback_chain=entry.fallback_chain,
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

        if suffix in _PLAINTEXT_EXTENSIONS:
            return self._extract_plaintext(filepath, out_file)

        if suffix in _PDF_EXTENSIONS:
            return self._extract_pdf(filepath, out_file)

        if suffix in _IMAGE_EXTENSIONS:
            return self._extract_image(filepath, out_file)

        # Office / other formats -- markitdown then direct read.
        return self._extract_generic(filepath, out_file)

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
        """PDF fallback chain: pymupdf (page-aware) -> pdftotext -> markitdown -> OCR -> read."""
        chain: list[str] = []

        # 1. pymupdf — per-page extraction with explicit page markers.
        chain.append("pymupdf")
        text = self._run_pymupdf(filepath)
        text_len = len(text.strip()) if text else 0
        page_count = self._count_pages_in_text(text) if text else 1
        is_dense_enough = text_len >= _SCANNED_PDF_THRESHOLD and (
            page_count <= 1 or text_len / page_count >= _MIN_CHARS_PER_PAGE
        )
        if text and is_dense_enough:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="primary",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=0.9,
                fallback_chain=chain,
            )

        # 2. pdftotext (poppler CLI) — convert form-feeds to page markers.
        chain.append("pdftotext")
        text = self._run_pdftotext(filepath)
        pdftotext_len = len(text.strip()) if text else 0
        pdftotext_pages = self._count_pages_in_text(text) if text else 1
        pdftotext_dense = pdftotext_len >= _SCANNED_PDF_THRESHOLD and (
            pdftotext_pages <= 1 or pdftotext_len / pdftotext_pages >= _MIN_CHARS_PER_PAGE
        )
        if text and pdftotext_dense:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_pdftotext",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=0.7,
                fallback_chain=chain,
            )

        # 3. markitdown (no page markers, but may handle edge cases).
        #    Readability check rejects raw PDF binary that markitdown
        #    dumps for image-only scanned PDFs (Bug G).
        chain.append("markitdown")
        text, conf = self._markitdown.extract(filepath)
        if text and len(text.strip()) >= _SCANNED_PDF_THRESHOLD and self._is_readable_text(text):
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_markitdown",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        # 4. pytesseract OCR
        chain.append("ocr")
        text, conf = self._ocr.extract(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_ocr",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        # 5. Raw read (last resort)
        chain.append("direct_read")
        text, conf = self._read_text(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_read",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        return self._failed_entry(filepath, chain)

    def _extract_image(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Image fallback chain: markitdown (OCR) -> pytesseract."""
        chain: list[str] = []

        # 1. markitdown
        chain.append("markitdown")
        text, conf = self._markitdown.extract(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="primary",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        # 2. pytesseract
        chain.append("ocr")
        text, conf = self._ocr.extract(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_ocr",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

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
        )

    def _extract_generic(self, filepath: Path, out_file: Path) -> ExtractionQualityEntry:
        """Generic (Office/other) fallback chain: markitdown -> direct read."""
        chain: list[str] = []

        # 1. markitdown
        chain.append("markitdown")
        text, conf = self._markitdown.extract(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="primary",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        # 2. Direct text read
        chain.append("direct_read")
        text, conf = self._read_text(filepath)
        if text and len(text.strip()) >= _MIN_TEXT_LEN:
            out_file.write_text(text, encoding="utf-8")
            return ExtractionQualityEntry(
                file_path=str(filepath),
                method="fallback_read",
                bytes_extracted=len(text.encode("utf-8")),
                confidence=conf,
                fallback_chain=chain,
            )

        return self._failed_entry(filepath, chain)

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
        import hashlib

        name = source_path.lstrip("./")
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

        try:
            doc = fitz.open(str(filepath))
        except Exception as exc:
            logger.debug("pymupdf failed to open %s: %s", filepath, exc)
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
        import re

        markers = re.findall(r"\n--- Page \d+ ---\n", text)
        return len(markers) if markers else 1

    @staticmethod
    def _is_cached_output_readable(out_file: Path) -> bool:
        """Check if a cached ``.md`` output file contains readable text.

        Reads a small sample from disk to avoid loading multi-MB binary
        garbage into memory.  Returns *False* for binary PDF dumps so
        they get re-extracted through the improved fallback chain.
        """
        try:
            sample = out_file.read_bytes()[:10_000].decode("utf-8", errors="replace")
            printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
            return printable / max(len(sample), 1) >= _MIN_PRINTABLE_RATIO
        except OSError:
            return False

    @staticmethod
    def _is_readable_text(text: str, *, sample_size: int = 10_000) -> bool:
        """Return *True* if *text* looks like human-readable content.

        Checks the ratio of printable characters (letters, digits,
        punctuation, whitespace) in a sample of the text.  Raw PDF
        binary dumped by markitdown has a very low printable ratio
        (< 50 %) because it contains stream objects, binary image
        data, and compressed content.

        A threshold of 85 % catches all observed binary-garbage cases
        while passing normal extracted text (typically > 95 % printable).
        """
        if not text:
            return False
        sample = text[:sample_size]
        printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
        return printable / len(sample) >= _MIN_PRINTABLE_RATIO

    @staticmethod
    def _read_text(filepath: Path) -> tuple[str, float]:
        """Read *filepath* as plain text (UTF-8, then latin-1)."""
        for encoding in ("utf-8", "latin-1"):
            try:
                text = filepath.read_text(encoding=encoding, errors="replace")
                if text.strip():
                    return text, 0.5
            except (OSError, UnicodeDecodeError):
                continue
        return "", 0.0

    @staticmethod
    def _failed_entry(filepath: Path, chain: list[str]) -> ExtractionQualityEntry:
        """Return a failed quality entry."""
        return ExtractionQualityEntry(
            file_path=str(filepath),
            method="failed",
            bytes_extracted=0,
            confidence=0.0,
            fallback_chain=chain,
        )
