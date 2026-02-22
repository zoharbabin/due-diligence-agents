"""PreToolUse hook functions.

Guards that fire before a tool executes. They return (allowed, reason) tuples
for the simplified function-level API, or flat dicts for the SDK hook API.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bash guard
# ---------------------------------------------------------------------------

BASH_BLOCKLIST: list[str] = [
    "rm -rf",
    "rm -r ",
    "git push",
    "git reset",
    "git checkout .",
    "git restore .",
    "git clean",
    "chmod",
    "chown",
    "kill ",
    "killall",
    "pkill",
    "sudo ",
    "mkfs",
    "dd if=",
    "> /dev/",
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    "| sh",
    "| bash",
]

SCOPE_CHECKED_PREFIXES: list[str] = ["mv ", "cp ", "ln ", "mkdir "]


def bash_guard(tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
    """Block destructive bash commands.

    Returns:
        (allowed, reason) -- ``True`` if allowed, ``False`` with explanation if blocked.
    """
    if tool_name != "Bash":
        return True, ""

    command = tool_input.get("command", "")
    cmd_lower = command.lower().strip()

    for dangerous in BASH_BLOCKLIST:
        if dangerous in cmd_lower:
            return False, (f"Blocked dangerous command pattern: '{dangerous}' in: {command[:100]}")

    return True, ""


# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------


def path_guard(
    tool_name: str,
    tool_input: dict[str, Any],
    project_dir: str | Path,
) -> tuple[bool, str]:
    """Block Write/Edit operations outside the ``_dd/`` directory.

    Only writes under ``{project_dir}/_dd/`` are allowed.

    Returns:
        (allowed, reason)
    """
    if tool_name not in ("Write", "Edit"):
        return True, ""

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return True, ""

    project_dir = Path(project_dir)
    dd_dir = project_dir / "_dd"

    # Resolve symlinks to prevent escape
    resolved = Path(os.path.realpath(file_path))
    dd_resolved = Path(os.path.realpath(dd_dir))

    if str(resolved).startswith(str(dd_resolved)):
        return True, ""

    return False, (
        f"Write/Edit blocked: path '{file_path}' is outside the _dd/ directory ({dd_dir}). All writes must target _dd/."
    )


# ---------------------------------------------------------------------------
# File size guard
# ---------------------------------------------------------------------------

DEFAULT_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB


def file_size_guard(
    tool_name: str,
    tool_input: dict[str, Any],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[bool, str]:
    """Warn when a write payload exceeds *max_bytes*.

    Returns:
        (allowed, reason) -- always allowed (warning only), but reason is
        non-empty when the limit is exceeded.
    """
    if tool_name not in ("Write", "Edit"):
        return True, ""

    content = tool_input.get("content", "")
    content_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0

    if content_bytes > max_bytes:
        return True, (
            f"WARNING: Write payload is {content_bytes:,} bytes "
            f"(limit {max_bytes:,} bytes). Consider splitting the output."
        )

    return True, ""


# ---------------------------------------------------------------------------
# Aggregate file guard blocklist (used by write_guard in hooks/factory)
# ---------------------------------------------------------------------------

BLOCKED_FILENAMES: list[str] = [
    "_global.json",
    "batch_summary.json",
    "other_customers.json",
    "pipeline_items.json",
    "remaining_customers.json",
    "all_customers.json",
    "combined.json",
    "summary.json",
    "batch_1.json",
    "batch_2.json",
    "batch_3.json",
    "miscellaneous.json",
    "misc.json",
    "overflow.json",
]

ALLOWED_SPECIAL_FILES: list[str] = [
    "coverage_manifest.json",
    "audit_log.jsonl",
]
