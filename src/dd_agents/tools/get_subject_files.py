"""get_subject_files MCP tool.

Returns the file list with rich metadata for a given subject name from the
subjects CSV inventory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Extension → human-readable type mapping.
_EXT_TYPE_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "word",
    ".doc": "word",
    ".xlsx": "excel",
    ".xls": "excel",
    ".pptx": "powerpoint",
    ".ppt": "powerpoint",
    ".csv": "csv",
    ".txt": "text",
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".json": "json",
    ".rtf": "rtf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".tiff": "image",
    ".tif": "image",
    ".bmp": "image",
    ".webp": "image",
    ".mp4": "video",
    ".avi": "video",
    ".mov": "video",
    ".mkv": "video",
    ".wmv": "video",
    ".webm": "video",
    ".m4v": "video",
    ".flv": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
    ".aac": "audio",
    ".ogg": "audio",
    ".wma": "audio",
    ".m4a": "audio",
    ".opus": "audio",
}


def _file_metadata(
    file_path: str,
    *,
    data_room_path: str | Path | None = None,
    text_dir: str | Path | None = None,
    file_precedence: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build metadata dict for a single file path."""
    ext = Path(file_path).suffix.lower()
    file_type = _EXT_TYPE_MAP.get(ext, ext.lstrip(".") if ext else "unknown")

    meta: dict[str, Any] = {
        "path": file_path,
        "file_type": file_type,
        "extension": ext,
    }

    # File size — resolve against data room if available.
    if data_room_path:
        import contextlib

        abs_path = Path(data_room_path) / file_path.lstrip("./")
        if abs_path.is_file():
            with contextlib.suppress(OSError):
                meta["size_bytes"] = abs_path.stat().st_size

    # Extraction status — check if .md text exists.
    if text_dir:
        from dd_agents.extraction.pipeline import ExtractionPipeline

        safe_name = ExtractionPipeline._safe_text_name(file_path)
        text_path = Path(text_dir) / safe_name
        meta["extracted"] = text_path.exists()

    # Precedence score if available.
    if file_precedence:
        normalized = file_path.lstrip("./")
        score = file_precedence.get(normalized) or file_precedence.get(file_path)
        if score is not None:
            meta["precedence_score"] = score

    return meta


def get_subject_files(
    subject_safe_name: str,
    subjects_csv: list[dict[str, Any]],
    *,
    data_room_path: str | Path | None = None,
    text_dir: str | Path | None = None,
    file_precedence: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return file list with metadata for *subject_safe_name*.

    Looks up the subject by ``subject_safe_name`` in *subjects_csv*.

    Args:
        subject_safe_name: The subject safe name to look up.
        subjects_csv: List of subject dicts, each with at least
            ``subject_safe_name`` and ``file_list`` keys.
        data_room_path: Root of the data room (for resolving file sizes).
        text_dir: Path to extracted text directory (for extraction status).
        file_precedence: Precedence scores keyed by file path.

    Returns:
        ``{"subject": str, "file_count": int, "files": list[dict]}`` or
        ``{"error": "unknown_subject", "name": str}``.
    """
    for row in subjects_csv:
        safe_name = row.get("subject_safe_name", "")
        if safe_name == subject_safe_name:
            file_list = row.get("file_list", [])
            if isinstance(file_list, str):
                # Handle comma-separated string
                file_list = [f.strip() for f in file_list.split(",") if f.strip()]

            files_meta = [
                _file_metadata(
                    fp,
                    data_room_path=data_room_path,
                    text_dir=text_dir,
                    file_precedence=file_precedence,
                )
                for fp in file_list
            ]
            return {
                "subject": safe_name,
                "display_name": row.get("subject_display_name", safe_name),
                "file_count": len(file_list),
                "files": files_meta,
            }

    return {
        "error": "unknown_subject",
        "name": subject_safe_name,
    }
