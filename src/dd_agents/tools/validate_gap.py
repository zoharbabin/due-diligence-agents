"""validate_gap MCP tool.

Validates a gap dict against the Gap Pydantic model.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from dd_agents.models.enums import DetectionMethod, GapType
from dd_agents.models.finding import Gap

VALID_GAP_TYPES: set[str] = {gt.value for gt in GapType}
VALID_DETECTION_METHODS: set[str] = {dm.value for dm in DetectionMethod}


def validate_gap(gap_json: dict[str, Any]) -> dict[str, Any]:
    """Validate a gap dict.

    Returns:
        ``{"valid": True}`` on success, or
        ``{"valid": False, "errors": [...]}`` on failure.

    Note: The Gap model coerces unknown detection_method values to
    ``"checklist"`` as a pipeline safety net.  This tool deliberately
    checks the *raw* input value BEFORE coercion so agents receive
    clear feedback and learn to produce canonical values.
    """
    errors: list[str] = []

    # Pre-coercion check: flag raw detection_method before the model
    # silently coerces it.  This keeps the agent feedback loop tight.
    raw_dm = gap_json.get("detection_method")
    if isinstance(raw_dm, str) and raw_dm.strip().lower() not in VALID_DETECTION_METHODS:
        errors.append(f"detection_method '{raw_dm}' not in {sorted(VALID_DETECTION_METHODS)}")

    try:
        gap = Gap.model_validate(gap_json)
    except ValidationError as exc:
        pydantic_errors = [f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return {
            "valid": False,
            "errors": errors + pydantic_errors,
        }

    # Enum validation (Pydantic already enforces this, but belt-and-suspenders)
    if gap.gap_type.value not in VALID_GAP_TYPES:
        errors.append(f"gap_type '{gap.gap_type}' not in {sorted(VALID_GAP_TYPES)}")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True}
