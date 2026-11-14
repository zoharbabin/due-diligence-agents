"""Shared text-file lookup for MCP document tools.

The extraction pipeline names output files using ``_safe_text_name(str(filepath))``
where ``filepath`` is the **absolute** path.  Chat tools receive a **relative**
``source_path`` from the agent.  When the absolute path exceeds 200 UTF-8 bytes
(common with OneDrive / deep directory trees), the filename includes a SHA-256
hash suffix that the relative path alone cannot reproduce.

This module provides ``resolve_text_path`` which tries multiple path forms so
that document tools work regardless of how the agent references the file.
"""

from __future__ import annotations

import glob
from pathlib import Path


def resolve_text_path(
    source_path: str,
    text_dir: str | Path,
    data_room_path: str | Path | None = None,
) -> Path | None:
    """Locate the extracted text file for *source_path*.

    Tries, in order:
    1. ``_safe_text_name(source_path)``  — works when agent uses the same
       path form as extraction (e.g. both relative, or both absolute).
    2. ``_safe_text_name(absolute_path)`` — where *absolute_path* is
       ``data_room_path / source_path`` resolved.  Matches files produced
       by the pipeline (which always passes absolute paths).
    3. Glob fallback — scans ``text_dir`` for any ``.md`` file whose name
       contains the source file's stem.  Handles edge cases where neither
       form matches exactly (e.g. the file was extracted with a slightly
       different relative prefix).

    Returns the first matching ``Path``, or ``None`` if nothing found.
    """
    from dd_agents.extraction.pipeline import ExtractionPipeline

    td = Path(text_dir)
    if not td.is_dir():
        return None

    # 1. Try the source_path as given
    candidate = td / ExtractionPipeline._safe_text_name(source_path)
    if candidate.exists():
        return candidate

    # 2. Try the absolute-path form (matches pipeline extraction)
    if data_room_path:
        dr = Path(data_room_path)
        stripped = source_path.lstrip("./")
        abs_path = (dr / stripped).resolve()
        abs_name = ExtractionPipeline._safe_text_name(str(abs_path))
        abs_candidate = td / abs_name
        if abs_candidate.exists():
            return abs_candidate

    # 3. Try with ./ prefix stripped (common variant)
    stripped_path = source_path.removeprefix("./")
    if stripped_path != source_path:
        candidate2 = td / ExtractionPipeline._safe_text_name(stripped_path)
        if candidate2.exists():
            return candidate2

    # 4. Glob fallback — match on the filename stem
    stem = Path(source_path).stem
    if stem:
        for md_file in td.glob(f"*{glob.escape(stem)}*.md"):
            if md_file.is_file():
                return md_file

    return None
