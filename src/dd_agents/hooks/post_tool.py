"""PostToolUse hook functions.

Validation callbacks that fire after a tool completes. They inspect the
tool output and return a list of error strings (empty == valid).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from dd_agents.models.finding import AgentFinding
from dd_agents.models.manifest import CoverageManifest

# ---------------------------------------------------------------------------
# validate_subject_json
# ---------------------------------------------------------------------------


def validate_subject_json(file_path: str, content: str) -> list[str]:
    """Validate a subject output JSON against the Finding model.

    Checks:
    - Valid JSON
    - Has required top-level keys (``subject``, ``findings``, ``file_headers``,
      ``subject_safe_name``)
    - Each finding validates against :class:`AgentFinding`

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # Parse JSON
    try:
        data: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return ["Top-level value must be a JSON object"]

    # Required top-level keys
    for key in ("subject", "findings", "file_headers"):
        if key not in data:
            errors.append(f"Missing required key: '{key}'")
    if "subject_safe_name" not in data:
        errors.append("Missing required key: 'subject_safe_name'")

    # Validate findings array
    findings_raw = data.get("findings")
    if findings_raw is not None:
        if not isinstance(findings_raw, list):
            errors.append("'findings' must be an array")
        else:
            for idx, finding_dict in enumerate(findings_raw):
                try:
                    AgentFinding.model_validate(finding_dict)
                except ValidationError as exc:
                    for err in exc.errors():
                        loc = ".".join(str(part) for part in err["loc"])
                        errors.append(f"findings[{idx}].{loc}: {err['msg']}")

    # Validate file_headers array
    file_headers = data.get("file_headers")
    if file_headers is not None and not isinstance(file_headers, list):
        errors.append("'file_headers' must be an array")

    return errors


# ---------------------------------------------------------------------------
# validate_manifest_json
# ---------------------------------------------------------------------------


def validate_manifest_json(file_path: str, content: str) -> list[str]:
    """Validate ``coverage_manifest.json`` against the CoverageManifest model.

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    try:
        CoverageManifest.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            errors.append(f"{loc}: {err['msg']}")

    return errors


# ---------------------------------------------------------------------------
# validate_audit_entry
# ---------------------------------------------------------------------------

_REQUIRED_AUDIT_FIELDS: set[str] = {
    "timestamp",
    "action",
    "agent",
}


def validate_audit_entry(entry_line: str) -> list[str]:
    """Spot-check a single JSONL audit entry for required fields.

    Returns:
        List of error strings. Empty list means valid.
    """
    errors: list[str] = []

    entry_line = entry_line.strip()
    if not entry_line:
        return ["Empty audit entry line"]

    try:
        data = json.loads(entry_line)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON in audit entry: {exc}"]

    if not isinstance(data, dict):
        return ["Audit entry must be a JSON object"]

    missing = _REQUIRED_AUDIT_FIELDS - set(data.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    return errors
