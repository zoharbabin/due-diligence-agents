"""verify_citation MCP tool.

Verifies that a source_path exists and that the exact_quote can be found in
the extracted text directory.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


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


def verify_citation(
    citation: dict[str, Any],
    files_list: list[str],
    text_dir: str | Path,
) -> dict[str, Any]:
    """Verify that a citation's source exists and quote can be found.

    Args:
        citation: Dict with ``source_path`` and ``exact_quote`` keys.
        files_list: List of known file paths from inventory.
        text_dir: Path to directory containing extracted text files.

    Returns:
        ``{"found": True, "location": "...", "method": "..."}`` or
        ``{"found": False, "reason": "..."}``.
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
        }

    # Locate extracted text file
    text_path = _get_text_path(source_path, text_dir)
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
    if norm_quote in norm_text:
        return {
            "found": True,
            "location": source_path,
            "method": "exact",
        }

    # Fuzzy match using simple ratio (avoid hard dependency on rapidfuzz)
    try:
        from rapidfuzz import fuzz

        quote_len = len(norm_quote)
        if quote_len > 20:
            best_ratio = fuzz.partial_ratio(norm_quote, norm_text) / 100.0
        else:
            best_ratio = 0.0
            window_size = min(quote_len * 2, len(norm_text))
            step = max(1, quote_len // 4)
            for i in range(0, len(norm_text) - quote_len + 1, step):
                window = norm_text[i : i + window_size]
                ratio = fuzz.ratio(norm_quote, window) / 100.0
                best_ratio = max(best_ratio, ratio)
                if best_ratio > 0.85:
                    break

        if best_ratio > 0.85:
            return {
                "found": True,
                "location": source_path,
                "method": f"fuzzy (score={best_ratio:.2f})",
            }
    except ImportError:
        pass  # rapidfuzz not available; skip fuzzy matching

    return {
        "found": False,
        "reason": (f"exact_quote not found in extracted text for '{source_path}'"),
    }
