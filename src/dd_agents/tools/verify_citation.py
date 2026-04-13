"""verify_citation MCP tool.

Verifies that a source_path exists and that the exact_quote can be found in
the extracted text directory.  Returns page number, character offset, and
surrounding context when a match is found.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from dd_agents.search.chunker import PAGE_MARKER_RE

# Characters of surrounding context to include in results.
_CONTEXT_CHARS = 80


def _normalize(text: str) -> str:
    """Normalize whitespace and Unicode for comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _get_text_path(source_path: str, text_dir: str | Path) -> Path:
    """Convert original file path to extracted text path.

    Uses the extraction pipeline's ``_safe_text_name`` helper so that
    long filenames are truncated with a hash suffix consistently.
    """
    from dd_agents.extraction.pipeline import ExtractionPipeline

    safe_name = ExtractionPipeline._safe_text_name(source_path)
    return Path(text_dir) / safe_name


def _find_page_number(text: str, char_offset: int) -> int | None:
    """Determine the page number for *char_offset* using ``--- Page N ---`` markers.

    Returns ``None`` if the text has no page markers.
    """
    page_num: int | None = None
    for m in PAGE_MARKER_RE.finditer(text):
        if m.start() > char_offset:
            break
        page_num = int(m.group(1))
    return page_num


def _extract_context(text: str, start: int, length: int) -> dict[str, str]:
    """Return context surrounding a match at *start* with *length* chars."""
    ctx_before_start = max(0, start - _CONTEXT_CHARS)
    ctx_after_end = min(len(text), start + length + _CONTEXT_CHARS)
    return {
        "context_before": text[ctx_before_start:start].strip(),
        "matched_text": text[start : start + length].strip(),
        "context_after": text[start + length : ctx_after_end].strip(),
    }


def _find_match_offset(norm_text: str, norm_quote: str) -> int | None:
    """Return the character offset of *norm_quote* in *norm_text*, or None."""
    idx = norm_text.find(norm_quote)
    return idx if idx >= 0 else None


def verify_citation(
    citation: dict[str, Any],
    files_list: list[str],
    text_dir: str | Path,
    allowed_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Verify that a citation's source exists and quote can be found.

    Args:
        citation: Dict with ``source_path`` and ``exact_quote`` keys.
        files_list: List of known file paths from inventory.
        text_dir: Path to directory containing extracted text files.
        allowed_dir: If set, restrict text reads to this directory tree
            (prevents path traversal when called by LLM agents).

    Returns:
        On success::

            {"found": True, "location": str, "method": str,
             "page_number": int | None, "char_offset": int,
             "context_before": str, "matched_text": str, "context_after": str}

        On failure::

            {"found": False, "reason": str}
    """
    source_path = citation.get("source_path", "")
    exact_quote = citation.get("exact_quote", "")

    if not source_path:
        return {"found": False, "reason": "Empty source_path"}

    # Check source_path existence in inventory
    source_in_inventory = False
    normalized_source = source_path.lstrip("./")
    for f in files_list:
        if f.lstrip("./") == normalized_source or f == source_path:
            source_in_inventory = True
            break

    if not source_in_inventory:
        return {
            "found": False,
            "reason": f"source_path '{source_path}' not found in file inventory",
        }

    if not exact_quote:
        # Source exists but no quote to verify
        return {
            "found": True,
            "location": source_path,
            "method": "source_only",
            "page_number": None,
            "char_offset": 0,
        }

    # Locate extracted text file
    text_path = _get_text_path(source_path, text_dir)

    # Path containment check — prevent agents from reading outside data room.
    # When called via MCP server, allowed_dir is always set by _build_runtime_context.
    if allowed_dir:
        try:
            resolved = text_path.resolve()
            allowed_resolved = Path(allowed_dir).resolve()
            if not resolved.is_relative_to(allowed_resolved):
                return {"found": False, "reason": "Path traversal blocked: text file is outside the allowed directory"}
        except (OSError, ValueError):
            return {"found": False, "reason": "Invalid text path"}

    if not text_path.exists():
        return {
            "found": False,
            "reason": (
                f"Extracted text not found at {text_path}. "
                f"Source file exists in inventory but no extracted text available."
            ),
        }

    text = text_path.read_text(encoding="utf-8")
    norm_text = _normalize(text)
    norm_quote = _normalize(exact_quote)

    # Exact substring match (after normalization)
    offset = _find_match_offset(norm_text, norm_quote)
    if offset is not None:
        page = _find_page_number(text, offset)
        ctx = _extract_context(text, offset, len(norm_quote))
        return {
            "found": True,
            "location": source_path,
            "method": "exact",
            "page_number": page,
            "char_offset": offset,
            **ctx,
        }

    # Fuzzy match using simple ratio (avoid hard dependency on rapidfuzz)
    try:
        from rapidfuzz import fuzz

        quote_len = len(norm_quote)
        best_ratio = 0.0
        best_offset = 0

        if quote_len > 20:
            best_ratio = fuzz.partial_ratio(norm_quote, norm_text) / 100.0
            # Approximate offset via sliding window for partial_ratio hit
            if best_ratio > 0.85:
                step = max(1, quote_len // 4)
                for i in range(0, len(norm_text) - quote_len + 1, step):
                    window = norm_text[i : i + quote_len + quote_len // 2]
                    ratio = fuzz.ratio(norm_quote, window) / 100.0
                    if ratio > 0.7:
                        best_offset = i
                        break
        else:
            window_size = min(quote_len * 2, len(norm_text))
            step = max(1, quote_len // 4)
            for i in range(0, len(norm_text) - quote_len + 1, step):
                window = norm_text[i : i + window_size]
                ratio = fuzz.ratio(norm_quote, window) / 100.0
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_offset = i
                if best_ratio > 0.85:
                    break

        if best_ratio > 0.85:
            page = _find_page_number(text, best_offset)
            ctx = _extract_context(text, best_offset, len(norm_quote))
            return {
                "found": True,
                "location": source_path,
                "method": f"fuzzy (score={best_ratio:.2f})",
                "page_number": page,
                "char_offset": best_offset,
                **ctx,
            }
    except ImportError:
        pass  # rapidfuzz not available; skip fuzzy matching

    return {
        "found": False,
        "reason": f"exact_quote not found in extracted text for '{source_path}'",
    }
