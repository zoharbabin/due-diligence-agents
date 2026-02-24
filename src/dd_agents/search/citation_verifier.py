"""Post-analysis citation verification against source documents.

Verifies that LLM-generated citations (``exact_quote``, ``page``,
``section_ref``) actually exist in the extracted source text.  Uses
``rapidfuzz`` for fuzzy matching to tolerate OCR artefacts.

Verification uses a **progressive search scope** (Issue #24):
1. Page-scoped: search within the cited page only.
2. Adjacent pages: expand to ±1 page (catches cross-page quotes
   and off-by-one page citations).
3. Full document: search the entire source file.
4. Cross-file: search ALL files in the customer's text set
   (catches file misattributions from the LLM merge phase).

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

# Regex to collapse whitespace for normalization.
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    """Collapse all whitespace (newlines, tabs, multiple spaces) to single space.

    This handles line breaks from PDF column layout, OCR, and markitdown
    reformatting that cause false-negative fuzzy matches.  Issue #24.
    """
    return _WHITESPACE_RE.sub(" ", text.strip())


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


def _get_adjacent_pages_text(pages: dict[str, str], page_num: str) -> str:
    """Return concatenated text for a page and its immediate neighbors (±1).

    Handles cross-page quotes and off-by-one page citations.  Issue #24.
    """
    try:
        num = int(page_num)
    except (ValueError, TypeError):
        return ""

    parts: list[str] = []
    for p in (num - 1, num, num + 1):
        text = pages.get(str(p), "")
        if text:
            parts.append(text)
    return "\n".join(parts)


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
        # Cache split pages per file to avoid re-splitting.  Issue #27 Phase 4.
        self._page_cache: dict[str, dict[str, str]] = {}
        # Cache normalized text to avoid re-normalizing.  Issue #27 Phase 4.
        self._norm_cache: dict[str, str] = {}

    def _get_pages(self, file_path: str, text: str) -> dict[str, str]:
        """Return page-split dict, using cache if available.  Issue #27 Phase 4."""
        if file_path in self._page_cache:
            return self._page_cache[file_path]
        pages = split_by_pages(text)
        self._page_cache[file_path] = pages
        return pages

    def _get_normalized(self, key: str, text: str) -> str:
        """Return normalized text, using cache if available.  Issue #27 Phase 4."""
        if key in self._norm_cache:
            return self._norm_cache[key]
        normalized = _normalize_whitespace(text)
        self._norm_cache[key] = normalized
        return normalized

    def _match_score(self, norm_quote: str, norm_text: str) -> float:
        """Return match score, short-circuiting on exact substring.  Issue #27 Phase 4."""
        if norm_quote in norm_text:
            return 100.0
        return float(fuzz.partial_ratio(norm_quote, norm_text))

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
        """Verify a single citation and populate its verification fields.

        Uses progressive search scope (Issue #24):
        1. Cited page → 2. Adjacent pages (±1) → 3. Full document → 4. Other files.

        Uses cached helpers for pages, normalized text, and match scoring
        to avoid redundant computation across citations.  Issue #27 Phase 4.
        """
        source_text = text_lookup.get(citation.file_path, "")

        # Verify section_ref against the full source text (any file that has it).
        if citation.section_ref:
            if source_text:
                citation.section_verified = citation.section_ref in source_text
            else:
                # Try all files — the section might be in a different file.
                citation.section_verified = any(citation.section_ref in txt for txt in text_lookup.values())
        else:
            citation.section_verified = None  # Nothing to verify.

        # Verify exact_quote.
        if not citation.exact_quote:
            citation.quote_verified = None  # Nothing to verify.
            citation.quote_match_score = 0.0
            return

        # Normalize the quote once for all comparisons.
        norm_quote = _normalize_whitespace(citation.exact_quote)

        # --- Progressive search scope ---

        # Scope 1: Cited page only.
        if source_text and citation.page and citation.page.strip():
            pages = self._get_pages(citation.file_path, source_text)
            page_text = pages.get(citation.page.strip())
            if page_text:
                page_num = citation.page.strip()
                norm_page = self._get_normalized(f"{citation.file_path}:page:{page_num}", page_text)
                score = self._match_score(norm_quote, norm_page)
                if score >= self._threshold:
                    citation.quote_match_score = float(score)
                    citation.quote_verified = True
                    return

                # Scope 2: Adjacent pages (±1).
                adj_text = _get_adjacent_pages_text(pages, page_num)
                if adj_text and adj_text != page_text:
                    norm_adj = self._get_normalized(f"{citation.file_path}:adj:{page_num}", adj_text)
                    score = self._match_score(norm_quote, norm_adj)
                    if score >= self._threshold:
                        citation.quote_match_score = float(score)
                        citation.quote_verified = True
                        return

        # Scope 3: Full document.
        if source_text:
            norm_full = self._get_normalized(f"{citation.file_path}:full", source_text)
            score = self._match_score(norm_quote, norm_full)
            if score >= self._threshold:
                citation.quote_match_score = float(score)
                citation.quote_verified = True
                return

        # Scope 4: Cross-file search — the quote may be misattributed.
        # Search ALL other files in the customer's text set.  Issue #24.
        best_score = 0.0
        best_file = ""
        for file_path, text in text_lookup.items():
            if file_path == citation.file_path:
                continue  # Already checked.
            if not text:
                continue
            norm_cross = self._get_normalized(f"{file_path}:full", text)
            score = self._match_score(norm_quote, norm_cross)
            if score > best_score:
                best_score = score
                best_file = file_path

        if best_score >= self._threshold and best_file:
            # Quote found in a different file — correct the attribution.
            src_score: float = 0.0
            if source_text:
                norm_src = self._get_normalized(f"{citation.file_path}:full", source_text)
                src_score = self._match_score(norm_quote, norm_src)
            logger.info(
                "Citation file_path corrected: %r → %r (score %.0f → %.0f)",
                citation.file_path,
                best_file,
                src_score,
                best_score,
            )
            citation.file_path = best_file
            citation.quote_match_score = float(best_score)
            citation.quote_verified = True
            # Try to find the correct page in the new file.
            new_text = text_lookup[best_file]
            new_pages = self._get_pages(best_file, new_text)
            if new_pages:
                for page_num, page_text in new_pages.items():
                    norm_pg = self._get_normalized(f"{best_file}:page:{page_num}", page_text)
                    pg_score = self._match_score(norm_quote, norm_pg)
                    if pg_score >= self._threshold:
                        citation.page = page_num
                        break
            return

        # All scopes exhausted — quote not found anywhere.
        # Use the best score we found (full document or cross-file).
        final_score = 0.0
        if source_text:
            norm_final = self._get_normalized(f"{citation.file_path}:full", source_text)
            final_score = self._match_score(norm_quote, norm_final)
        if best_score > final_score:
            final_score = best_score
        citation.quote_match_score = float(final_score)
        citation.quote_verified = False

        if not source_text and not best_file:
            citation.quote_verified = False
            citation.quote_match_score = 0.0

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

            # Fallback: LLM may cite colons (`:`) that the filesystem
            # stores as HTML entities (`&#x3a_`).  Try the encoded variant.
            if not text_path.exists() and ":" in file_path:
                encoded_path = file_path.replace(":", "&#x3a_")
                alt_absolute = str(self._data_room / encoded_path)
                alt_safe = ExtractionPipeline._safe_text_name(alt_absolute)
                alt_text_path = self._text_dir / alt_safe
                if alt_text_path.exists():
                    text_path = alt_text_path

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
