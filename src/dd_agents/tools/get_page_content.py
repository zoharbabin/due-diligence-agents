"""get_page_content MCP tool.

Extracts specific page ranges from extracted text using ``--- Page N ---``
markers.  Enables agents to read targeted sections without loading entire
documents into context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dd_agents.search.chunker import PAGE_MARKER_RE


def _get_text_path(source_path: str, text_dir: str | Path) -> Path:
    """Convert original file path to extracted text path."""
    from dd_agents.extraction.pipeline import ExtractionPipeline

    safe_name = ExtractionPipeline._safe_text_name(source_path)
    return Path(text_dir) / safe_name


def _split_pages(text: str) -> dict[int, str]:
    """Split text into page-number → content mapping.

    Text before the first marker is stored under page 0.
    """
    parts = PAGE_MARKER_RE.split(text)
    pages: dict[int, str] = {}

    if not parts:
        return pages

    # parts alternates: [preamble, "1", page1text, "2", page2text, ...]
    if parts[0].strip():
        pages[0] = parts[0]

    for i in range(1, len(parts) - 1, 2):
        page_num = int(parts[i])
        page_text = parts[i + 1] if i + 1 < len(parts) else ""
        pages[page_num] = page_text

    return pages


def get_page_content(
    source_path: str,
    text_dir: str | Path,
    *,
    start_page: int = 1,
    end_page: int | None = None,
    allowed_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Extract page content from the extracted text of *source_path*.

    Args:
        source_path: Original file path from inventory.
        text_dir: Path to directory containing extracted text files.
        start_page: First page to return (1-based, inclusive).
        end_page: Last page to return (inclusive). ``None`` = same as start_page.
        allowed_dir: If set, restrict reads to this directory tree.

    Returns:
        ``{"pages": {page_num: text, ...}, "total_pages": int}`` or
        ``{"error": str, "reason": str}``.
    """
    if not source_path:
        return {"error": "invalid_input", "reason": "Empty source_path"}

    text_path = _get_text_path(source_path, text_dir)

    # Path containment check.
    if allowed_dir:
        try:
            resolved = text_path.resolve()
            allowed_resolved = Path(allowed_dir).resolve()
            if not resolved.is_relative_to(allowed_resolved):
                return {"error": "blocked", "reason": "Path traversal blocked"}
        except (OSError, ValueError):
            return {"error": "blocked", "reason": "Invalid text path"}

    if not text_path.exists():
        return {
            "error": "not_found",
            "reason": f"No extracted text for '{source_path}'",
        }

    text = text_path.read_text(encoding="utf-8")
    all_pages = _split_pages(text)

    # Check for actual page markers (keys > 0; key 0 is just preamble).
    has_page_markers = any(k > 0 for k in all_pages)

    # Hard cap: never return more than ~100 KB to avoid blowing up the
    # SDK message buffer.  Callers should use search_in_file first to
    # identify the right pages, then request small ranges.
    max_result_chars = 100_000

    if not has_page_markers:
        # No page markers — return a truncated version as page 1.
        page_text = text[:max_result_chars]
        truncated = len(text) > max_result_chars
        result: dict[str, Any] = {
            "source_path": source_path,
            "pages": {"1": page_text},
            "total_pages": 1,
            "has_page_markers": False,
        }
        if truncated:
            result["truncated"] = True
            result["hint"] = (
                f"Document is {len(text):,} chars — only first {max_result_chars:,} returned. "
                "Use search_in_file to locate specific sections."
            )
        return result

    total_pages = max(all_pages.keys()) if all_pages else 0
    if end_page is None:
        end_page = start_page

    # Clamp range to valid pages.  Cap at 5 pages per call.
    start_page = max(0, start_page)
    end_page = min(end_page, total_pages)
    if end_page - start_page > 4:
        end_page = start_page + 4

    result_pages: dict[str, str] = {}
    chars_used = 0
    for p in range(start_page, end_page + 1):
        if p in all_pages:
            page_text = all_pages[p]
            if chars_used + len(page_text) > max_result_chars:
                break
            result_pages[str(p)] = page_text
            chars_used += len(page_text)

    return {
        "source_path": source_path,
        "pages": result_pages,
        "total_pages": total_pages,
        "has_page_markers": True,
        "requested_range": f"{start_page}-{end_page}",
    }
