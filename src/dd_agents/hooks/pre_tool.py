"""PreToolUse hook functions.

Guards that fire before a tool executes. They return flat dicts with
``{"decision": "allow"|"block", "reason": "..."}`` for the SDK hook API.
"""

from __future__ import annotations

import os
import re
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
    "dd of=",
    "> /dev/",
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    "| sh",
    "| bash",
    "| python",
    "| perl",
    "| ruby",
    "| node",
    "python -c",
    "python3 -c",
    "python -m",
    "python3 -m",
    "perl -e",
    "ruby -e",
    "node -e",
    "eval ",
    "exec ",
    "nohup ",
    "xargs ",
    "truncate ",
    "shred ",
    "pip install",
    "pip3 install",
    "nc ",
    "ncat ",
    "netcat ",
]

# Patterns that catch shell invocation via absolute/relative paths or env dispatch.
# Checked via regex after whitespace normalization.
_SHELL_INVOKE_PATTERNS: list[re.Pattern[str]] = [
    # Absolute / relative path to any shell: /bin/bash, /usr/bin/env sh, ./sh, etc.
    re.compile(r"(?:^|&&|\|\||;)\s*(?:/\S*/)?(?:ba)?sh\s+-c\b"),
    # /usr/bin/env dispatch to shell or interpreter
    re.compile(r"(?:^|&&|\|\||;)\s*(?:/\S*/)?env\s+(?:ba)?sh\b"),
    # Versioned python invocation: python3.12 -c, python3.11 -c, etc.
    re.compile(r"\bpython\d[\d.]*\s+-c\b"),
    # Heredoc into shell: bash<<, sh<<
    re.compile(r"\b(?:ba)?sh\s*<<"),
    # $SHELL or ${SHELL} invocation
    re.compile(r"\$\{?shell\}?\s"),
]

SCOPE_CHECKED_PREFIXES: list[str] = ["mv ", "cp ", "ln ", "mkdir "]


def _normalize_whitespace(cmd: str) -> str:
    """Collapse runs of whitespace to single spaces for consistent matching."""
    return re.sub(r"\s+", " ", cmd)


def bash_guard(tool_name: str, tool_input: dict[str, Any]) -> dict[str, str]:
    """Block destructive bash commands.

    Applies whitespace normalization before checking the blocklist to prevent
    evasion via extra spaces or tabs. Also applies regex patterns to catch
    shell/interpreter invocation via absolute paths, env dispatch, heredocs,
    and versioned interpreters.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    if tool_name != "Bash":
        return {"decision": "allow", "reason": ""}

    command = tool_input.get("command", "")
    cmd_lower = _normalize_whitespace(command.lower().strip())

    for dangerous in BASH_BLOCKLIST:
        if dangerous in cmd_lower:
            return {
                "decision": "block",
                "reason": f"Blocked dangerous command pattern: '{dangerous}' in: {command[:100]}",
            }

    # Scope-check prefixes: block if path is outside current working directory
    for prefix in SCOPE_CHECKED_PREFIXES:
        if cmd_lower.startswith(prefix):
            # Block if any argument starts with / and isn't under cwd
            parts = cmd_lower.split()
            for part in parts[1:]:
                if part.startswith("/") or part.startswith(".."):
                    return {
                        "decision": "block",
                        "reason": f"Blocked: '{prefix.strip()}' with absolute/parent path in: {command[:100]}",
                    }

    # Regex patterns for shell invocation bypasses
    for pattern in _SHELL_INVOKE_PATTERNS:
        if pattern.search(cmd_lower):
            return {"decision": "block", "reason": f"Blocked shell/interpreter invocation pattern in: {command[:100]}"}

    return {"decision": "allow", "reason": ""}


# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------


def path_guard(
    tool_name: str,
    tool_input: dict[str, Any],
    project_dir: str | Path,
) -> dict[str, str]:
    """Block Write/Edit operations outside the ``_dd/`` directory.

    Only writes under ``{project_dir}/_dd/`` are allowed.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    if tool_name not in ("Write", "Edit"):
        return {"decision": "allow", "reason": ""}

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return {"decision": "allow", "reason": ""}

    project_dir = Path(project_dir)
    dd_dir = project_dir / "_dd"

    # Resolve symlinks to prevent escape
    resolved = Path(os.path.realpath(file_path))
    dd_resolved = Path(os.path.realpath(dd_dir))

    if resolved == dd_resolved or str(resolved).startswith(str(dd_resolved) + os.sep):
        return {"decision": "allow", "reason": ""}

    return {
        "decision": "block",
        "reason": (
            f"Write/Edit blocked: path '{file_path}' is outside "
            f"the _dd/ directory ({dd_dir}). All writes must target _dd/."
        ),
    }


# ---------------------------------------------------------------------------
# File size guard
# ---------------------------------------------------------------------------

DEFAULT_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB


def file_size_guard(
    tool_name: str,
    tool_input: dict[str, Any],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, str]:
    """Warn when a write payload exceeds *max_bytes*.

    Returns:
        ``{"decision": "allow", "reason": "..."}`` -- always allows (warning only),
        but reason is non-empty when the limit is exceeded.
    """
    if tool_name not in ("Write", "Edit"):
        return {"decision": "allow", "reason": ""}

    content = tool_input.get("content", "")
    content_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0

    if content_bytes > max_bytes:
        return {
            "decision": "allow",
            "reason": f"WARNING: Write payload is {content_bytes:,} bytes "
            f"(limit {max_bytes:,} bytes). Consider splitting the output.",
        }

    return {"decision": "allow", "reason": ""}


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
