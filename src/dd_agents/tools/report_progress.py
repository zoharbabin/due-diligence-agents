"""report_progress MCP tool.

Allows agents to report progress back to the orchestrator for liveness
monitoring and progress tracking.
"""

from __future__ import annotations

from typing import Any


def report_progress(
    agent_name: str,
    subjects_processed: int,
    total_subjects: int,
    current_subject: str,
) -> dict[str, Any]:
    """Return a progress snapshot.

    Args:
        agent_name: Name of the reporting agent.
        subjects_processed: Count of subjects completed so far.
        total_subjects: Total subjects assigned to this agent.
        current_subject: Subject currently being processed.

    Returns:
        Progress dict with percentage, counts, and status.
    """
    pct = (subjects_processed / total_subjects * 100.0) if total_subjects > 0 else 0.0

    status = "in_progress"
    if subjects_processed >= total_subjects:
        status = "complete"
    elif subjects_processed == 0:
        status = "starting"

    return {
        "agent": agent_name,
        "subjects_processed": subjects_processed,
        "total_subjects": total_subjects,
        "current_subject": current_subject,
        "progress_pct": round(pct, 1),
        "status": status,
    }
