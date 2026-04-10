"""get_subject_files MCP tool.

Returns the file list and count for a given subject name from the
subjects CSV inventory.
"""

from __future__ import annotations

from typing import Any


def get_subject_files(
    subject_safe_name: str,
    subjects_csv: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return file list and count for *subject_safe_name*.

    Looks up the subject by ``subject_safe_name`` in *subjects_csv*.

    Args:
        subject_safe_name: The subject safe name to look up.
        subjects_csv: List of subject dicts, each with at least
            ``subject_safe_name`` and ``file_list`` keys.

    Returns:
        ``{"subject": str, "file_count": int, "files": list[str]}`` or
        ``{"error": "unknown_subject", "name": str}``.
    """
    for row in subjects_csv:
        safe_name = row.get("subject_safe_name", "")
        if safe_name == subject_safe_name:
            file_list = row.get("file_list", [])
            if isinstance(file_list, str):
                # Handle comma-separated string
                file_list = [f.strip() for f in file_list.split(",") if f.strip()]
            return {
                "subject": safe_name,
                "file_count": len(file_list),
                "files": file_list,
            }

    return {
        "error": "unknown_subject",
        "name": subject_safe_name,
    }
