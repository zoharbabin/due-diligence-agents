"""Post-analysis citation verification against source documents.

Verifies that LLM-generated citations (``exact_quote``, ``page``,
``section_ref``) actually exist in the extracted source text.  Uses
``rapidfuzz`` for fuzzy matching to tolerate OCR artefacts.

This module runs locally — no API calls, no LLM usage.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.models.search import SearchCitation, SearchCustomerResult
    from dd_agents.search.chunker import FileText

logger = logging.getLogger(__name__)

# Minimum fuzzy match score (0-100) to consider a quote verified.
# 80 % tolerates OCR character errors while still catching hallucinations.
QUOTE_MATCH_THRESHOLD = 80

# Regex to split extracted text into pages by ``--- Page N ---`` markers.
_PAGE_MARKER_RE = re.compile(r"\n--- Page (\d+) ---\n")


def split_by_pages(text: str) -> dict[str, str]:
    """Split extracted text into page-number → page-text mapping.

    Uses ``--- Page N ---`` markers injected by the extraction pipeline.
    The key is the string page number (e.g. ``"5"``).  Text before the
    first marker is stored under key ``"0"`` (preamble).
    """
    parts = _PAGE_MARKER_RE.split(text)
    pages: dict[str, str] = {}

    if not parts:
        return pages

    # parts alternates between text-before-marker and page-number.
    # Example: ["preamble", "1", "page1text", "2", "page2text"]
    if parts[0].strip():
        pages["0"] = parts[0]

    for i in range(1, len(parts) - 1, 2):
        page_num = parts[i]
        page_text = parts[i + 1] if i + 1 < len(parts) else ""
        pages[page_num] = page_text

    return pages


class CitationVerifier:
    """Verify citations against extracted source text.

    Parameters
    ----------
    text_dir:
        Directory containing extracted ``.md`` text files.
    data_room_path:
        Root of the data room (for resolving relative file paths).
    threshold:
        Minimum fuzzy match score (0-100) for quote verification.
    """

    def __init__(
        self,
        text_dir: Path,
        data_room_path: Path,
        threshold: int = QUOTE_MATCH_THRESHOLD,
    ) -> None:
        self._text_dir = text_dir
        self._data_room = data_room_path
        self._threshold = threshold
        # Cache loaded file texts to avoid repeated I/O.
        self._file_cache: dict[str, str] = {}

    def verify_result(
        self,
        result: SearchCustomerResult,
        file_texts: list[FileText] | None = None,
    ) -> SearchCustomerResult:
        """Verify all citations in a customer result in-place.

        If *file_texts* is provided, uses those directly (avoids disk I/O).
        Otherwise loads from ``text_dir``.

        Returns the same result object with verification fields populated.
        """
        # Build lookup from file_path → full text.
        text_lookup: dict[str, str] = {}
        if file_texts:
            for ft in file_texts:
                text_lookup[ft.file_path] = ft.text
        else:
            text_lookup = self._load_customer_texts(result)

        for col_result in result.columns.values():
            for citation in col_result.citations:
                self._verify_citation(citation, text_lookup)

        return result

    def _verify_citation(
        self,
        citation: SearchCitation,
        text_lookup: dict[str, str],
    ) -> None:
        """Verify a single citation and populate its verification fields."""
        source_text = text_lookup.get(citation.file_path, "")
        if not source_text:
            # File not found in extracted texts — can't verify.
            citation.quote_verified = False
            citation.quote_match_score = 0.0
            citation.section_verified = False
            return

        # Verify section_ref.
        if citation.section_ref:
            citation.section_verified = citation.section_ref in source_text
        else:
            citation.section_verified = None  # Nothing to verify.

        # Verify exact_quote.
        if not citation.exact_quote:
            citation.quote_verified = None  # Nothing to verify.
            citation.quote_match_score = 0.0
            return

        # Determine search scope: page-scoped if page is specified.
        search_text = source_text
        if citation.page and citation.page.strip():
            pages = split_by_pages(source_text)
            page_text = pages.get(citation.page.strip())
            if page_text:
                search_text = page_text

        # Fuzzy match the quote against the source text.
        score = fuzz.partial_ratio(citation.exact_quote, search_text)
        citation.quote_match_score = float(score)
        citation.quote_verified = score >= self._threshold

    def _load_customer_texts(self, result: SearchCustomerResult) -> dict[str, str]:
        """Load extracted .md files for all cited file paths."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        text_lookup: dict[str, str] = {}
        cited_paths: set[str] = set()

        for col_result in result.columns.values():
            for citation in col_result.citations:
                if citation.file_path:
                    cited_paths.add(citation.file_path)

        for file_path in cited_paths:
            if file_path in self._file_cache:
                text_lookup[file_path] = self._file_cache[file_path]
                continue

            absolute = str(self._data_room / file_path)
            safe_name = ExtractionPipeline._safe_text_name(absolute)
            text_path = self._text_dir / safe_name

            if text_path.exists():
                text = text_path.read_text(encoding="utf-8", errors="replace")
                self._file_cache[file_path] = text
                text_lookup[file_path] = text
            else:
                logger.debug("Citation verifier: no extracted text for %s", file_path)

        return text_lookup


def compute_verification_summary(result: SearchCustomerResult) -> dict[str, int]:
    """Compute verification counts for a customer result.

    Returns a dict with keys: ``verified``, ``failed``, ``unverifiable``.
    """
    verified = 0
    failed = 0
    unverifiable = 0

    for col_result in result.columns.values():
        for citation in col_result.citations:
            if citation.quote_verified is True:
                verified += 1
            elif citation.quote_verified is False:
                failed += 1
            else:
                unverifiable += 1

    return {"verified": verified, "failed": failed, "unverifiable": unverifiable}
