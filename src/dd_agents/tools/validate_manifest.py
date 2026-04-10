"""validate_manifest MCP tool.

Validates a coverage manifest dict against the CoverageManifest Pydantic model
and enforces business rules (coverage_pct >= 0.90, etc.).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from dd_agents.models.manifest import CoverageManifest


def validate_manifest(manifest_json: dict[str, Any]) -> dict[str, Any]:
    """Validate a coverage manifest dict.

    Checks:
    - Pydantic model validation
    - ``coverage_pct >= 0.90``
    - ``analysis_units_completed >= analysis_units_assigned``
    - No duplicate subjects
    - ``files_failed`` entries have ``fallback_attempted=True``

    Returns:
        ``{"valid": True}`` on success, or
        ``{"valid": False, "errors": [...]}`` on failure.
    """
    errors: list[str] = []

    try:
        manifest = CoverageManifest.model_validate(manifest_json)
    except ValidationError as exc:
        return {
            "valid": False,
            "errors": [f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()],
        }

    # Coverage percentage gate
    if manifest.coverage_pct < 0.90:
        errors.append(f"coverage_pct is {manifest.coverage_pct:.2f}, must be >= 0.90")

    # Completion check
    if manifest.analysis_units_completed < manifest.analysis_units_assigned:
        errors.append(
            f"analysis_units_completed ({manifest.analysis_units_completed}) < "
            f"analysis_units_assigned ({manifest.analysis_units_assigned})"
        )

    # No duplicate subjects
    subject_names: set[str] = set()
    for cust in manifest.subjects:
        if cust.name in subject_names:
            errors.append(f"Duplicate subject entry: '{cust.name}'")
        subject_names.add(cust.name)

        # Valid status
        if cust.status not in ("complete", "partial"):
            errors.append(f"Subject '{cust.name}' has invalid status '{cust.status}'")

    # files_failed must have fallback_attempted=True
    for ff in manifest.files_failed:
        if not ff.fallback_attempted:
            errors.append(f"files_failed entry '{ff.path}' has fallback_attempted=False (must try fallback chain)")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True}
