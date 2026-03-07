"""Review manager for finding annotations and review workflow (Issue #122).

Annotations are stored separately from findings (non-destructive).
Each run gets its own review state file at ``{run_dir}/review_state.json``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — used at runtime
from typing import Any

from dd_agents.models.review import (
    Annotation,
    ReviewAssignment,
    ReviewProgress,
    ReviewState,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _make_id(prefix: str, *parts: str) -> str:
    raw = ":".join(parts) + _now_iso()
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _finding_id(finding: dict[str, Any]) -> str:
    """Generate a stable ID for a finding based on its key fields."""
    title = finding.get("title", "")
    customer = finding.get("_customer", finding.get("customer_safe_name", ""))
    agent = finding.get("agent", "")
    raw = f"{customer}:{agent}:{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ReviewManager:
    """CRUD operations on review state for a pipeline run."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "review_state.json"

    def _load(self) -> ReviewState:
        if not self.state_path.exists():
            return ReviewState()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return ReviewState.model_validate(data)
        except Exception:
            logger.warning("Corrupt review state, starting fresh: %s", self.state_path)
            return ReviewState()

    def _save(self, state: ReviewState) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        state.last_updated = _now_iso()
        self.state_path.write_text(
            json.dumps(state.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )

    def add_annotation(
        self,
        finding: dict[str, Any],
        reviewer: str,
        comment: str = "",
        status: str = "reviewed",
        severity_override: str | None = None,
        severity_justification: str = "",
    ) -> Annotation:
        """Add an annotation to a finding."""
        state = self._load()
        fid = _finding_id(finding)
        annotation = Annotation(
            id=_make_id("ann", fid, reviewer),
            finding_id=fid,
            customer_safe_name=finding.get("_customer", ""),
            reviewer=reviewer,
            timestamp=_now_iso(),
            comment=comment,
            status=status,
            severity_override=severity_override,
            severity_justification=severity_justification,
        )
        state.annotations.append(annotation)
        self._save(state)
        return annotation

    def get_annotations(self, finding_id: str | None = None) -> list[Annotation]:
        """Get annotations, optionally filtered by finding ID."""
        state = self._load()
        if finding_id is None:
            return state.annotations
        return [a for a in state.annotations if a.finding_id == finding_id]

    def update_annotation_status(self, annotation_id: str, status: str) -> Annotation | None:
        """Update the status of an existing annotation."""
        state = self._load()
        for ann in state.annotations:
            if ann.id == annotation_id:
                ann.status = status
                self._save(state)
                return ann
        return None

    def assign_reviewer(
        self,
        reviewer: str,
        section: str = "",
        customer_safe_name: str = "",
    ) -> ReviewAssignment:
        """Assign a reviewer to a section or customer."""
        state = self._load()
        assignment = ReviewAssignment(
            id=_make_id("asgn", reviewer, section, customer_safe_name),
            reviewer=reviewer,
            section=section,
            customer_safe_name=customer_safe_name,
            assigned_at=_now_iso(),
        )
        state.assignments.append(assignment)
        self._save(state)
        return assignment

    def sign_off(self, assignment_id: str) -> ReviewAssignment | None:
        """Mark an assignment as signed off."""
        state = self._load()
        for asgn in state.assignments:
            if asgn.id == assignment_id:
                asgn.signed_off = True
                asgn.signed_off_at = _now_iso()
                self._save(state)
                return asgn
        return None

    def get_assignments(self, reviewer: str | None = None) -> list[ReviewAssignment]:
        """Get assignments, optionally filtered by reviewer."""
        state = self._load()
        if reviewer is None:
            return state.assignments
        return [a for a in state.assignments if a.reviewer == reviewer]

    def compute_progress(self, total_findings: int) -> ReviewProgress:
        """Compute review progress from current state."""
        state = self._load()
        status_counts: dict[str, int] = {"pending": 0, "reviewed": 0, "disputed": 0, "accepted": 0}

        # Count unique finding statuses (latest annotation per finding wins)
        latest_by_finding: dict[str, str] = {}
        for ann in state.annotations:
            latest_by_finding[ann.finding_id] = ann.status

        for status in latest_by_finding.values():
            if status in status_counts:
                status_counts[status] += 1

        reviewed_count = sum(v for k, v in status_counts.items() if k != "pending")
        pending = max(0, total_findings - reviewed_count)
        pct = (reviewed_count / total_findings * 100) if total_findings > 0 else 0.0

        # Progress by section
        by_section: dict[str, dict[str, int]] = {}
        for ann in state.annotations:
            section = ann.customer_safe_name or "general"
            if section not in by_section:
                by_section[section] = {"reviewed": 0, "disputed": 0, "accepted": 0}
            if ann.status in by_section[section]:
                by_section[section][ann.status] += 1

        # Progress by reviewer
        by_reviewer: dict[str, dict[str, int]] = {}
        for ann in state.annotations:
            if ann.reviewer not in by_reviewer:
                by_reviewer[ann.reviewer] = {"reviewed": 0, "disputed": 0, "accepted": 0}
            if ann.status in by_reviewer[ann.reviewer]:
                by_reviewer[ann.reviewer][ann.status] += 1

        return ReviewProgress(
            total_findings=total_findings,
            reviewed=reviewed_count,
            disputed=status_counts["disputed"],
            accepted=status_counts["accepted"],
            pending=pending,
            pct_complete=pct,
            by_section=by_section,
            by_reviewer=by_reviewer,
        )

    def export_annotations(self, format: str = "json") -> str:
        """Export annotations as structured data."""
        state = self._load()
        if format == "csv":
            lines = ["finding_id,reviewer,status,comment,severity_override,timestamp"]
            for ann in state.annotations:
                lines.append(
                    f"{ann.finding_id},{ann.reviewer},{ann.status},"
                    f'"{ann.comment}",{ann.severity_override or ""},{ann.timestamp}'
                )
            return "\n".join(lines)
        return json.dumps([a.model_dump() for a in state.annotations], indent=2, default=str)
