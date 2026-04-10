"""Stop hook functions.

Checks that fire when an agent signals it wants to stop. They return flat
dicts ``{"decision": "allow"|"block", "reason": "..."}`` for the SDK hook API.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# check_coverage
# ---------------------------------------------------------------------------


def check_coverage(
    agent_output_dir: str | Path,
    expected_subject_count: int,
) -> dict[str, str]:
    """Check whether the agent has produced one JSON per expected subject.

    Counts ``*.json`` files in *agent_output_dir*, excluding
    ``coverage_manifest.json``.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    output_dir = Path(agent_output_dir)

    if not output_dir.exists():
        return {
            "decision": "block",
            "reason": (
                f"Output directory does not exist: {output_dir}. Expected {expected_subject_count} subject JSONs."
            ),
        }

    subject_jsons = [f for f in output_dir.glob("*.json") if f.name != "coverage_manifest.json"]
    actual_count = len(subject_jsons)

    if actual_count < expected_subject_count:
        produced = sorted(f.stem for f in subject_jsons)
        return {
            "decision": "block",
            "reason": (
                f"Only {actual_count}/{expected_subject_count} subject JSONs "
                f"found. Produced so far: {produced[:10]}"
                f"{'...' if len(produced) > 10 else ''}. "
                f"Continue processing remaining subjects."
            ),
        }

    return {"decision": "allow", "reason": ""}


# ---------------------------------------------------------------------------
# check_manifest
# ---------------------------------------------------------------------------


def check_manifest(agent_output_dir: str | Path) -> dict[str, str]:
    """Check whether ``coverage_manifest.json`` exists in *agent_output_dir*.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    output_dir = Path(agent_output_dir)
    manifest_path = output_dir / "coverage_manifest.json"

    if not manifest_path.exists():
        return {
            "decision": "block",
            "reason": "coverage_manifest.json not found. Write the coverage manifest before stopping.",
        }

    return {"decision": "allow", "reason": ""}


# ---------------------------------------------------------------------------
# check_audit_log
# ---------------------------------------------------------------------------


def check_audit_log(agent_output_dir: str | Path) -> dict[str, str]:
    """Warn (but do not block) if ``audit_log.jsonl`` is missing.

    Looks for the file under a sibling ``audit/{agent_name}/`` directory,
    or directly under *agent_output_dir* as a fallback.

    Returns:
        ``{"decision": "allow", "reason": "..."}`` -- always allows (warning only).
    """
    output_dir = Path(agent_output_dir)

    # Convention: audit log lives in a sibling audit dir
    # e.g., if output_dir is run/findings/legal, audit is run/audit/legal
    agent_name = output_dir.name
    audit_dir = output_dir.parent.parent / "audit" / agent_name
    audit_log = audit_dir / "audit_log.jsonl"

    if not audit_log.exists():
        # Also check directly in output_dir
        alt_log = output_dir / "audit_log.jsonl"
        if not alt_log.exists():
            return {
                "decision": "allow",
                "reason": (
                    f"WARNING: audit_log.jsonl not found at {audit_log} or {alt_log}. Consider writing an audit log."
                ),
            }

    return {"decision": "allow", "reason": ""}
