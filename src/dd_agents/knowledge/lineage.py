"""Cross-run finding evolution and lineage tracking (Issue #183).

Tracks how findings evolve across pipeline runs — detecting new findings,
updates to existing ones, resolutions, recurrences, and severity changes.
Each finding is identified by a stable fingerprint derived from its core
attributes (entity, agent, category, primary citation, normalized title).

Storage: ``lineage.json`` in the knowledge directory (PERMANENT tier).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from dd_agents.knowledge._utils import now_iso

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class FindingStatus(StrEnum):
    """Lifecycle status of a tracked finding."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    RECURRED = "recurred"


class SeverityEvent(BaseModel):
    """Records a severity change for a finding in a specific run."""

    run_id: str = Field(description="Pipeline run where the change occurred")
    timestamp: str = Field(description="ISO-8601 timestamp of the change")
    old_severity: str = Field(description="Previous severity level")
    new_severity: str = Field(description="New severity level")
    reason: str = Field(default="raw_finding", description="Reason for the change")


class FindingLineage(BaseModel):
    """Full lineage record for a single finding across runs.

    Tracks first/last appearance, severity history, resolution/recurrence,
    and the latest descriptive text for LLM-readable summaries.
    """

    fingerprint: str = Field(description="Stable SHA-256 prefix identifying this finding")
    first_seen_run_id: str = Field(description="Run ID where this finding first appeared")
    first_seen_timestamp: str = Field(description="ISO-8601 when first seen")
    last_seen_run_id: str = Field(description="Run ID where this finding was last observed")
    last_seen_timestamp: str = Field(description="ISO-8601 when last seen")
    run_count: int = Field(default=1, ge=1, description="Number of runs this finding appeared in")
    current_severity: str = Field(description="Current severity level")
    severity_history: list[SeverityEvent] = Field(
        default_factory=list,
        description="Chronological log of severity changes",
    )
    status: FindingStatus = Field(default=FindingStatus.ACTIVE, description="Current lifecycle status")
    resolution_run_id: str | None = Field(default=None, description="Run ID where finding was resolved")
    recurrence_run_id: str | None = Field(default=None, description="Run ID where finding recurred")
    latest_title: str = Field(description="Most recent title of the finding")
    latest_description: str = Field(description="Most recent description (may exceed 200 chars for old data)")
    entity_safe_name: str = Field(description="Entity safe name (lowercase, normalized)")
    agent: str = Field(description="Agent that produced this finding")
    category: str = Field(description="Finding category")


class LineageUpdateResult(BaseModel):
    """Summary of changes after processing a run's findings."""

    new_findings: int = Field(default=0, description="Findings seen for the first time")
    updated_findings: int = Field(default=0, description="Existing findings updated")
    resolved_findings: int = Field(default=0, description="Findings marked resolved (absent from run)")
    recurred_findings: int = Field(default=0, description="Previously resolved findings that reappeared")
    severity_changes: int = Field(default=0, description="Findings with severity level changes")


def _normalize_title(title: str) -> str:
    """Lowercase and strip punctuation for stable fingerprinting."""
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def compute_finding_fingerprint(finding: dict[str, Any]) -> str:
    """Compute a stable fingerprint for a finding.

    Components: analysis_unit, agent, category, primary citation
    (source_path + location), and normalized title. Joined with ``|``,
    SHA-256 hashed, first 16 hex chars returned.

    Parameters
    ----------
    finding:
        Dict with keys like ``analysis_unit``, ``agent``, ``category``,
        ``title``, and optionally ``citations`` list.
    """
    analysis_unit = finding.get("analysis_unit", finding.get("_customer", ""))
    agent = finding.get("agent", "")
    category = finding.get("category", "")

    # Primary citation: first citation's source_path + location
    citations = finding.get("citations", [])
    source_path = ""
    location = ""
    if citations and isinstance(citations, list) and len(citations) > 0:
        first_cite = citations[0]
        if isinstance(first_cite, dict):
            source_path = str(first_cite.get("source_path") or first_cite.get("file_path") or "")
            location = str(first_cite.get("location") or first_cite.get("page") or "")

    title_norm = _normalize_title(finding.get("title", ""))

    components = f"{analysis_unit}|{agent}|{category}|{source_path}|{location}|{title_norm}"
    return hashlib.sha256(components.encode("utf-8")).hexdigest()[:16]


class FindingLineageTracker:
    """Tracks finding evolution across pipeline runs.

    Persists lineage data to a JSON file with atomic writes. Handles
    missing or corrupt files gracefully by starting fresh.

    Parameters
    ----------
    lineage_path:
        Path to the ``lineage.json`` file.
    """

    def __init__(self, lineage_path: Path) -> None:
        from pathlib import Path as _Path

        self._path = _Path(lineage_path)
        self._findings: dict[str, FindingLineage] = {}

    def load(self) -> None:
        """Load lineage data from disk. Starts fresh on missing/corrupt file."""
        if not self._path.exists():
            self._findings = {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._findings = {}
            if isinstance(data, dict):
                for fp, entry in data.items():
                    self._findings[fp] = FindingLineage.model_validate(entry)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load lineage from %s: %s — starting fresh", self._path, exc)
            self._findings = {}

    def save(self) -> None:
        """Write lineage data atomically (temp + os.replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            serialized = {fp: entry.model_dump(mode="json") for fp, entry in self._findings.items()}
            tmp.write_text(
                json.dumps(serialized, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(self._path))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def update_from_run(
        self,
        run_id: str,
        findings: list[dict[str, Any]],
    ) -> LineageUpdateResult:
        """Process findings from a pipeline run, updating lineage records.

        Parameters
        ----------
        run_id:
            Unique identifier for this pipeline run.
        findings:
            List of finding dicts from the merged output.

        Returns
        -------
        LineageUpdateResult:
            Counts of new, updated, resolved, recurred, and severity-changed findings.
        """
        result = LineageUpdateResult()
        now = now_iso()
        seen_fingerprints: set[str] = set()

        for finding in findings:
            fp = compute_finding_fingerprint(finding)
            seen_fingerprints.add(fp)

            title = finding.get("title", "")
            description = finding.get("description", "")
            # Truncate description to 200 chars when updating
            if len(description) > 200:
                description = description[:200]
            severity = finding.get("severity", "medium")
            entity = finding.get("analysis_unit", finding.get("_customer", ""))
            agent = finding.get("agent", "")
            category = finding.get("category", "")

            existing = self._findings.get(fp)

            if existing is None:
                # New finding
                self._findings[fp] = FindingLineage(
                    fingerprint=fp,
                    first_seen_run_id=run_id,
                    first_seen_timestamp=now,
                    last_seen_run_id=run_id,
                    last_seen_timestamp=now,
                    run_count=1,
                    current_severity=severity,
                    status=FindingStatus.ACTIVE,
                    latest_title=title,
                    latest_description=description,
                    entity_safe_name=entity,
                    agent=agent,
                    category=category,
                )
                result.new_findings += 1
            else:
                # Existing finding — update
                existing.last_seen_run_id = run_id
                existing.last_seen_timestamp = now
                existing.run_count += 1
                existing.latest_title = title
                existing.latest_description = description

                # Severity change?
                if existing.current_severity != severity:
                    existing.severity_history.append(
                        SeverityEvent(
                            run_id=run_id,
                            timestamp=now,
                            old_severity=existing.current_severity,
                            new_severity=severity,
                        )
                    )
                    existing.current_severity = severity
                    result.severity_changes += 1

                # Recurrence?
                if existing.status == FindingStatus.RESOLVED:
                    existing.status = FindingStatus.RECURRED
                    existing.recurrence_run_id = run_id
                    existing.resolution_run_id = None
                    result.recurred_findings += 1
                else:
                    result.updated_findings += 1

        # Mark absent findings as resolved
        for fp, entry in self._findings.items():
            if fp not in seen_fingerprints and entry.status == FindingStatus.ACTIVE:
                entry.status = FindingStatus.RESOLVED
                entry.resolution_run_id = run_id
                result.resolved_findings += 1

        return result

    def get_lineage(self, fingerprint: str) -> FindingLineage | None:
        """Get lineage record by fingerprint. Returns None if not found."""
        return self._findings.get(fingerprint)

    def get_entity_lineage(self, entity_safe_name: str) -> list[FindingLineage]:
        """Get all lineage records for a specific entity."""
        return [e for e in self._findings.values() if e.entity_safe_name == entity_safe_name]

    def get_active(self) -> list[FindingLineage]:
        """Get all findings with ACTIVE status."""
        return [e for e in self._findings.values() if e.status == FindingStatus.ACTIVE]

    def get_resolved(self) -> list[FindingLineage]:
        """Get all findings with RESOLVED status."""
        return [e for e in self._findings.values() if e.status == FindingStatus.RESOLVED]

    def get_severity_changes(self, since_run_id: str | None = None) -> list[FindingLineage]:
        """Get findings that have had severity changes.

        Parameters
        ----------
        since_run_id:
            If provided, only return findings with changes in or after this run.
        """
        results: list[FindingLineage] = []
        for entry in self._findings.values():
            if not entry.severity_history:
                continue
            if since_run_id is None:
                results.append(entry)
            else:
                if any(ev.run_id == since_run_id for ev in entry.severity_history):
                    results.append(entry)
        return results

    def get_persistent_findings(self, min_runs: int = 3) -> list[FindingLineage]:
        """Get findings that have appeared in at least ``min_runs`` runs."""
        return [e for e in self._findings.values() if e.run_count >= min_runs]

    def generate_evolution_summary(self, max_chars: int = 5000) -> str:
        """Generate an LLM-readable summary of finding evolution.

        Parameters
        ----------
        max_chars:
            Maximum character length for the summary.
        """
        if not self._findings:
            return "No finding lineage data available."

        lines: list[str] = []
        lines.append(f"Finding Evolution Summary ({len(self._findings)} tracked findings)")
        lines.append("")

        active = self.get_active()
        resolved = self.get_resolved()
        recurred = [e for e in self._findings.values() if e.status == FindingStatus.RECURRED]
        persistent = self.get_persistent_findings(min_runs=3)

        lines.append(f"Active: {len(active)}, Resolved: {len(resolved)}, Recurred: {len(recurred)}")
        lines.append(f"Persistent (3+ runs): {len(persistent)}")
        lines.append("")

        if persistent:
            lines.append("Persistent findings:")
            for entry in persistent[:10]:
                lines.append(f"  - [{entry.current_severity}] {entry.latest_title} ({entry.run_count} runs)")

        sev_changes = self.get_severity_changes()
        if sev_changes:
            lines.append("")
            lines.append("Severity changes:")
            for entry in sev_changes[:10]:
                last_ev = entry.severity_history[-1]
                lines.append(f"  - {entry.latest_title}: {last_ev.old_severity} -> {last_ev.new_severity}")

        if recurred:
            lines.append("")
            lines.append("Recurred findings:")
            for entry in recurred[:10]:
                lines.append(f"  - [{entry.current_severity}] {entry.latest_title}")

        summary = "\n".join(lines)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3] + "..."
        return summary
