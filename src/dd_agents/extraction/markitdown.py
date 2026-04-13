"""Wrapper around the ``markitdown`` library for document-to-markdown extraction.

``markitdown`` is the primary extraction method for PDFs, DOCX, XLSX,
PPTX, and images.  If the library is not installed, extraction falls
back to macOS ``textutil`` (for .doc/.docx/.rtf) or a plain-text file
read.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import TYPE_CHECKING

from dd_agents.extraction._constants import CONFIDENCE_FAILURE, CONFIDENCE_FALLBACK_READ, PLAINTEXT_EXTENSIONS
from dd_agents.extraction._constants import CONFIDENCE_MARKITDOWN as _CONFIDENCE_SUCCESS
from dd_agents.extraction._helpers import read_text

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# File extensions that markitdown is expected to handle.
MARKITDOWN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        ".rtf",
        ".html",
        ".htm",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".gif",
    }
)


class MarkitdownExtractor:
    """Extracts document text using the ``markitdown`` library.

    Usage::

        extractor = MarkitdownExtractor()
        text, confidence = extractor.extract(Path("contract.pdf"))
    """

    @property
    def name(self) -> str:
        return "markitdown"

    @property
    def supported_extensions(self) -> frozenset[str]:
        return MARKITDOWN_EXTENSIONS

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text from *filepath*.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence)``.  On failure returns
            ``("", 0.0)``.  On successful markitdown conversion returns
            confidence ``0.9``.
        """
        # For plain-text files, just read directly (no markitdown needed).
        if filepath.suffix.lower() in PLAINTEXT_EXTENSIONS:
            return self._read_text(filepath)

        # Attempt markitdown conversion.
        try:
            text, confidence = self._run_markitdown(filepath)
            if text:
                return text, confidence
        except Exception:
            logger.debug("markitdown failed for %s, trying fallbacks", filepath.name)

        # Fallback: macOS textutil handles .doc/.docx/.rtf/.html natively.
        text, confidence = self._run_textutil(filepath)
        if text:
            return text, confidence

        # Last resort: direct text read (works for plain-text-like formats).
        return self._read_text(filepath)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_markitdown(filepath: Path) -> tuple[str, float]:
        """Call the markitdown library and return ``(text, confidence)``.

        Raises ``ImportError`` if markitdown is not installed, which the
        caller catches and falls through to the text-read fallback.
        """
        try:
            from markitdown import MarkItDown
        except ImportError:
            logger.warning(
                "markitdown is not installed -- falling back to direct read.  Install with: pip install markitdown"
            )
            raise

        converter = MarkItDown()
        result = converter.convert(str(filepath))

        text = result.text_content if hasattr(result, "text_content") else ""
        if text and text.strip():
            return text, _CONFIDENCE_SUCCESS
        return "", CONFIDENCE_FAILURE

    @staticmethod
    def _run_textutil(filepath: Path) -> tuple[str, float]:
        """Use macOS ``textutil`` to convert rich documents to plain text.

        ``textutil`` is a built-in macOS command that handles ``.doc``,
        ``.docx``, ``.rtf``, ``.html``, and other formats natively.
        Returns ``("", 0.0)`` on non-macOS systems or on failure.
        """
        if platform.system() != "Darwin":
            return "", CONFIDENCE_FAILURE

        textutil_extensions = {".doc", ".docx", ".rtf", ".html", ".htm", ".odt", ".webarchive"}
        if filepath.suffix.lower() not in textutil_extensions:
            return "", CONFIDENCE_FAILURE

        try:
            result = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", str(filepath)],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                text = result.stdout.decode("utf-8", errors="replace")
                if text.strip():
                    logger.debug("textutil extracted %d chars from %s", len(text), filepath.name)
                    return text, CONFIDENCE_FALLBACK_READ
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("textutil failed for %s: %s", filepath, exc)

        return "", CONFIDENCE_FAILURE

    @staticmethod
    def _read_text(filepath: Path) -> tuple[str, float]:
        """Read a file as plain text (UTF-8, falling back to latin-1)."""
        return read_text(filepath)
