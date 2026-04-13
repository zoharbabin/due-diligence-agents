"""Stop hook functions.

Checks that fire when an agent signals it wants to stop. They return flat
dicts ``{"decision": "allow"|"block", "reason": "..."}`` for the SDK hook API.
"""

from __future__ import annotations

from pathlib import Path

from dd_agents.utils.constants import COVERAGE_MANIFEST_JSON

# ---------------------------------------------------------------------------
# Turn budget thresholds (fraction of soft max_turns limit)
# ---------------------------------------------------------------------------

# When current_turn / max_turns exceeds this, inject "wrap up" guidance.
_TURN_WARN_THRESHOLD = 0.75
# When exceeded, inject urgent prioritization guidance.
_TURN_URGENT_THRESHOLD = 0.90

# ---------------------------------------------------------------------------
# check_coverage
# ---------------------------------------------------------------------------


def check_coverage(
    agent_output_dir: str | Path,
    expected_subject_count: int,
    *,
    current_turn: int | None = None,
    max_turns: int | None = None,
) -> dict[str, str]:
    """Check whether the agent has produced one JSON per expected subject.

    Counts ``*.json`` files in *agent_output_dir*, excluding
    ``coverage_manifest.json``.

    When *current_turn* and *max_turns* are provided, injects turn-budget
    guidance into block reasons so agents prioritize remaining work.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    output_dir = Path(agent_output_dir)

    if not output_dir.exists():
        reason = f"Output directory does not exist: {output_dir}. Expected {expected_subject_count} subject JSONs."
        reason += _turn_budget_guidance(current_turn, max_turns, expected_subject_count, 0)
        return {"decision": "block", "reason": reason}

    subject_jsons = [f for f in output_dir.glob("*.json") if f.name != COVERAGE_MANIFEST_JSON]
    actual_count = len(subject_jsons)

    if actual_count < expected_subject_count:
        produced = sorted(f.stem for f in subject_jsons)
        reason = (
            f"Only {actual_count}/{expected_subject_count} subject JSONs "
            f"found. Produced so far: {produced[:10]}"
            f"{'...' if len(produced) > 10 else ''}. "
            f"Continue processing remaining subjects."
        )
        reason += _turn_budget_guidance(
            current_turn,
            max_turns,
            expected_subject_count,
            actual_count,
        )
        return {"decision": "block", "reason": reason}

    return {"decision": "allow", "reason": ""}


def _turn_budget_guidance(
    current_turn: int | None,
    max_turns: int | None,
    expected: int,
    completed: int,
) -> str:
    """Build turn-budget guidance string for block reasons.

    Returns empty string if turn info is unavailable or budget is ample.
    """
    if current_turn is None or max_turns is None or max_turns <= 0:
        return ""

    ratio = current_turn / max_turns
    remaining_subjects = expected - completed
    remaining_turns = max_turns - current_turn

    turns_per_subject = remaining_turns / remaining_subjects if remaining_subjects > 0 and remaining_turns > 0 else 0.0

    if ratio >= _TURN_URGENT_THRESHOLD:
        return (
            f" URGENT: {current_turn}/{max_turns} turns used ({ratio:.0%}). "
            f"Only {remaining_turns} turns left for {remaining_subjects} subjects "
            f"({turns_per_subject:.0f} turns/subject). "
            f"PRIORITIZE: skip low-value analysis, write minimal but complete "
            f"findings for each remaining subject, then write coverage_manifest.json."
        )
    if ratio >= _TURN_WARN_THRESHOLD:
        return (
            f" WARNING: {current_turn}/{max_turns} turns used ({ratio:.0%}). "
            f"{remaining_turns} turns left for {remaining_subjects} subjects "
            f"({turns_per_subject:.0f} turns/subject). "
            f"Be concise — focus on high-severity findings for remaining subjects."
        )
    return ""


# ---------------------------------------------------------------------------
# check_manifest
# ---------------------------------------------------------------------------


def check_manifest(
    agent_output_dir: str | Path,
    expected_subject_count: int = 0,
) -> dict[str, str]:
    """Check whether ``coverage_manifest.json`` exists in *agent_output_dir*.

    If *expected_subject_count* is provided and all subject JSONs are already
    written, the manifest check is relaxed — the orchestrator will backfill
    the manifest post-session.  This prevents agents from wasting turns in
    the grace period trying to write the manifest after all real work is done.

    Returns:
        ``{"decision": "allow"|"block", "reason": "..."}``
    """
    output_dir = Path(agent_output_dir)
    manifest_path = output_dir / COVERAGE_MANIFEST_JSON

    if manifest_path.exists():
        return {"decision": "allow", "reason": ""}

    # If all subject files are written, allow stop even without manifest.
    # The orchestrator backfills manifests in step 16 after agent completion.
    if expected_subject_count > 0:
        subject_jsons = [f for f in output_dir.glob("*.json") if f.name != COVERAGE_MANIFEST_JSON]
        if len(subject_jsons) >= expected_subject_count:
            return {"decision": "allow", "reason": ""}

    return {
        "decision": "block",
        "reason": "coverage_manifest.json not found. Write the coverage manifest before stopping.",
    }


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
