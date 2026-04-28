"""extract_document MCP tool.

Extracts text from a single document file and writes it to the text index,
making it available to search_in_file, get_page_content, and other document
tools.  Enables the chat agent to index new or updated files on the fly
without re-running the full pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Hard limits to prevent abuse
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


def extract_document(
    file_path: str,
    data_room_path: str | Path,
    text_dir: str | Path,
    *,
    allowed_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Extract text from a document and write it to the text index.

    Args:
        file_path: Path to the document (absolute or relative to data room).
        data_room_path: Root data room directory.
        text_dir: Directory for extracted ``.md`` text files.
        allowed_dir: If set, restrict operations to this directory tree.

    Returns:
        ``{"status": "extracted", "source_path": ..., "text_file": ...,
          "method": ..., "confidence": ..., "chars": ...}`` on success,
        or ``{"error": str, "reason": str}`` on failure.
    """
    if not file_path:
        return {"error": "invalid_input", "reason": "Empty file_path"}

    data_room = Path(data_room_path).resolve()
    text_out = Path(text_dir)

    # Resolve the file — try absolute first, then relative to data room
    resolved = Path(file_path)
    if not resolved.is_absolute():
        resolved = data_room / file_path
    resolved = resolved.resolve()

    # Path containment check
    if allowed_dir:
        try:
            allowed_resolved = Path(allowed_dir).resolve()
            if not resolved.is_relative_to(allowed_resolved) and not resolved.is_relative_to(data_room):
                return {"error": "blocked", "reason": "Path outside allowed directory"}
        except (OSError, ValueError):
            return {"error": "blocked", "reason": "Invalid path"}

    if not resolved.exists():
        return {"error": "not_found", "reason": f"File not found: {file_path}"}

    if not resolved.is_file():
        return {"error": "invalid_input", "reason": f"Not a file: {file_path}"}

    # Size check
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        return {"error": "io_error", "reason": str(exc)}

    if size > _MAX_FILE_SIZE_BYTES:
        return {
            "error": "too_large",
            "reason": f"File is {size:,} bytes (limit: {_MAX_FILE_SIZE_BYTES:,})",
        }

    if size == 0:
        return {"error": "empty_file", "reason": "File is empty (0 bytes)"}

    # Compute the relative path for safe_text_name (relative to data room)
    try:
        relative_path = str(resolved.relative_to(data_room))
    except ValueError:
        relative_path = resolved.name

    # extract_single names its output using _safe_text_name(str(filepath)).
    # Since we pass the absolute path (so the file can be opened), the
    # output filename encodes the full absolute path.  But search_in_file
    # and get_page_content look up files by whatever source_path the agent
    # passes — typically a relative or bare path.  To bridge the gap we
    # write the extracted text under every plausible lookup name.
    from dd_agents.extraction.pipeline import ExtractionPipeline

    try:
        pipeline = ExtractionPipeline()
        text_out.mkdir(parents=True, exist_ok=True)

        entry = pipeline.extract_single(filepath=resolved, output_dir=text_out)
    except Exception as exc:
        logger.warning("Extraction failed for %s: %s", file_path, exc)
        return {"error": "extraction_failed", "reason": str(exc)}

    # Read the extracted text from the absolute-path-named file.
    abs_text_name = ExtractionPipeline._safe_text_name(str(resolved))
    abs_text_file = text_out / abs_text_name

    chars = 0
    content = ""
    if abs_text_file.exists():
        import contextlib

        with contextlib.suppress(OSError):
            content = abs_text_file.read_text(encoding="utf-8")
            chars = len(content)

    if chars == 0:
        return {
            "error": "extraction_empty",
            "reason": f"Extraction produced no text for {resolved.name}",
            "method": entry.method,
            "confidence": entry.confidence,
        }

    # Write copies under every path variant the agent might use for lookup.
    seen_names: set[str] = {abs_text_name}
    for variant in (relative_path, file_path, f"./{relative_path}", str(resolved)):
        alt_name = ExtractionPipeline._safe_text_name(variant)
        if alt_name not in seen_names:
            seen_names.add(alt_name)
            alt_file = text_out / alt_name
            if not alt_file.exists():
                import contextlib

                with contextlib.suppress(OSError):
                    alt_file.write_text(content, encoding="utf-8")

    return {
        "status": "extracted",
        "source_path": relative_path,
        "text_file": str(abs_text_file.name),
        "method": entry.method,
        "confidence": round(entry.confidence, 2),
        "chars": chars,
        "hint": (
            f"Document indexed ({chars:,} chars). "
            "You can now use search_in_file and get_page_content with "
            f"source_path='{relative_path}' to read its contents."
        ),
    }
