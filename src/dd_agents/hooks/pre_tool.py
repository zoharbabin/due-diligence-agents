"""PreToolUse hook functions.

Guards that fire before a tool executes. They return flat dicts with
``{"decision": "allow"|"block", "reason": "..."}`` for the SDK hook API.
"""

from __future__ import annotations

import json
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

    # Scope-check prefixes: block if path is outside current working directory.
    # Split on compound-command separators so "echo x && mv /etc/foo ." is caught.
    sub_commands = re.split(r"\s*(?:&&|\|\||;)\s*", cmd_lower)
    for sub_cmd in sub_commands:
        for prefix in SCOPE_CHECKED_PREFIXES:
            if sub_cmd.startswith(prefix):
                parts = sub_cmd.split()
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
    resolved = Path(file_path).resolve()
    dd_resolved = dd_dir.resolve()

    if resolved.is_relative_to(dd_resolved):
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
    "other_subjects.json",
    "pipeline_items.json",
    "remaining_subjects.json",
    "all_subjects.json",
    "combined.json",
    "summary.json",
    "miscellaneous.json",
    "misc.json",
    "overflow.json",
]

# Matches batch_1.json, batch_2.json, ..., batch_99.json — any numbered batch file.
BATCH_FILE_PATTERN: re.Pattern[str] = re.compile(r"^batch_\d+\.json$")


# ---------------------------------------------------------------------------
# Finding schema guard — validates JSON structure before write
# ---------------------------------------------------------------------------

# Field aliases that agents commonly invent.  Keys are wrong names, values are
# the correct canonical names the agent should use instead.
_FINDING_FIELD_ALIASES: dict[str, str] = {
    "evidence": "citations",
}

_CITATION_FIELD_ALIASES: dict[str, str] = {
    "file": "source_path",
    "file_path": "source_path",
    "filepath": "source_path",
    "path": "source_path",
    "document": "source_path",
    "doc": "source_path",
    "quote": "exact_quote",
    "text": "exact_quote",
    "excerpt": "exact_quote",
    "verbatim": "exact_quote",
}

# Files in findings dirs that are NOT subject output (skip validation).
_FINDINGS_SKIP_FILES: set[str] = {
    "coverage_manifest.json",
    "audit_log.jsonl",
}


def finding_schema_guard(
    tool_name: str,
    tool_input: dict[str, Any],
    run_dir: str | Path,
) -> dict[str, str]:
    """Block writes of malformed finding JSON to ``findings/{agent}/*.json``.

    Only fires on ``Write`` calls whose target path is inside the run's
    ``findings/`` directory and ends in ``.json``.  Parses the JSON content
    and checks each finding for field-name violations (e.g. ``"evidence"``
    instead of ``"citations"``, ``"file"`` instead of ``"source_path"``).

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    if tool_name != "Write":
        return {"decision": "allow", "reason": ""}

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return {"decision": "allow", "reason": ""}

    fp = Path(file_path)

    # Only validate *.json writes inside {run_dir}/findings/
    findings_dir = Path(run_dir) / "findings"
    try:
        if not fp.resolve().is_relative_to(findings_dir.resolve()):
            return {"decision": "allow", "reason": ""}
    except (ValueError, OSError):
        return {"decision": "allow", "reason": ""}

    if fp.suffix != ".json":
        return {"decision": "allow", "reason": ""}

    if fp.name in _FINDINGS_SKIP_FILES:
        return {"decision": "allow", "reason": ""}

    content = tool_input.get("content", "")
    if not content:
        return {"decision": "allow", "reason": ""}

    # Parse JSON — if it fails, let the write proceed (other guards handle this).
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"decision": "allow", "reason": ""}

    if not isinstance(data, dict):
        return {"decision": "allow", "reason": ""}

    # Validate each finding in the "findings" array.
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        return {"decision": "allow", "reason": ""}

    violations: list[str] = []
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        violations.extend(_check_finding_schema(finding, idx))

    if not violations:
        return {"decision": "allow", "reason": ""}

    nl = "\n"
    return {
        "decision": "block",
        "reason": (
            f"Finding schema violations in {fp.name} — fix these before writing:\n"
            f"{nl.join(violations)}\n\n"
            "Required finding structure:\n"
            '  "citations": [{"source_type": "file", "source_path": "path/to/doc.pdf", '
            '"location": "Section X", "exact_quote": "verbatim text"}]\n'
            "Do NOT use 'evidence', 'file', or other aliases. "
            "Use exactly 'citations' with 'source_path' and 'exact_quote'."
        ),
    }


def _check_finding_schema(finding: dict[str, Any], idx: int) -> list[str]:
    """Return a list of schema violation messages for a single finding."""
    violations: list[str] = []
    prefix = f"findings[{idx}]"

    # Check for wrong top-level field names.
    for wrong, correct in _FINDING_FIELD_ALIASES.items():
        if wrong in finding and correct not in finding:
            violations.append(f"  {prefix}: rename '{wrong}' → '{correct}'")

    # Check citations structure.
    citations = finding.get("citations")
    if citations is None:
        # Only flag if there's also no alias — a finding with neither is
        # genuinely missing citations.
        has_alias = any(alias in finding for alias in _FINDING_FIELD_ALIASES)
        if not has_alias:
            violations.append(f"  {prefix}: missing 'citations' array — every finding needs at least one citation")
        return violations

    if not isinstance(citations, list):
        violations.append(f"  {prefix}: 'citations' must be an array, got {type(citations).__name__}")
        return violations

    if not citations:
        violations.append(f"  {prefix}: 'citations' array is empty — add at least one citation")
        return violations

    # Check each citation for field-name violations.
    for cit_idx, cit in enumerate(citations):
        if not isinstance(cit, dict):
            continue
        cit_prefix = f"{prefix}.citations[{cit_idx}]"
        for wrong, correct in _CITATION_FIELD_ALIASES.items():
            if wrong in cit and correct not in cit:
                violations.append(f"  {cit_prefix}: rename '{wrong}' → '{correct}'")
        if "source_path" not in cit and not any(alias in cit for alias in _CITATION_FIELD_ALIASES):
            violations.append(f"  {cit_prefix}: missing 'source_path'")

    return violations
