"""Report diff builder -- compares findings between current and prior runs.

Produces a ``ReportDiff`` model that is written to ``report_diff.json``
and optionally rendered as the Run_Diff sheet in the Excel report.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.models.reporting import (
    ReportDiff,
    ReportDiffChange,
    ReportDiffSummary,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ReportDiffBuilder:
    """Compare current run findings against a prior run.

    Matching is done on ``subject + category + citation source_path``.
    Detected change types:
    - new_finding / resolved_finding
    - changed_severity
    - new_gap / resolved_gap
    - new_subject / removed_subject
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_diff(
        self,
        current_findings_dir: Path,
        prior_findings_dir: Path,
        current_run_id: str = "current",
        prior_run_id: str = "prior",
    ) -> ReportDiff:
        """Build a diff comparing two merged-findings directories.

        Each directory is expected to contain per-subject JSON files under
        ``merged/`` and gap JSON files under ``merged/gaps/``.
        """
        current_findings = self._load_findings(current_findings_dir / "merged")
        prior_findings = self._load_findings(prior_findings_dir / "merged")
        current_gaps = self._load_gaps(current_findings_dir / "merged" / "gaps")
        prior_gaps = self._load_gaps(prior_findings_dir / "merged" / "gaps")

        changes: list[ReportDiffChange] = []

        current_subjects = set(current_findings.keys())
        prior_subjects = set(prior_findings.keys())

        # Subject-level changes
        for c in sorted(current_subjects - prior_subjects):
            changes.append(
                ReportDiffChange(
                    change_type="new_subject",
                    subject=c,
                    details="New entity in current run",
                )
            )
        for c in sorted(prior_subjects - current_subjects):
            changes.append(
                ReportDiffChange(
                    change_type="removed_subject",
                    subject=c,
                    details="Entity removed from current run",
                )
            )

        # Finding + gap level changes for shared subjects
        for subj in sorted(current_subjects & prior_subjects):
            changes.extend(
                self._diff_findings(
                    subj,
                    current_findings[subj],
                    prior_findings[subj],
                )
            )
            changes.extend(
                self._diff_gaps(
                    subj,
                    current_gaps.get(subj, []),
                    prior_gaps.get(subj, []),
                )
            )

        summary = self._build_summary(changes)

        return ReportDiff(
            current_run_id=current_run_id,
            prior_run_id=prior_run_id,
            summary=summary,
            changes=changes,
        )

    def write_diff(self, diff: ReportDiff, output_path: Path) -> None:
        """Serialize the diff to JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(diff.model_dump_json(indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _finding_match_key(finding: dict[str, Any]) -> str:
        """Match key: category + citation source_path."""
        cit = (finding.get("citations") or [{}])[0]
        source_path = cit.get("source_path", "") if isinstance(cit, dict) else getattr(cit, "source_path", "")
        return f"{finding.get('category', '')}|{source_path}"

    @staticmethod
    def _gap_match_key(gap: dict[str, Any]) -> str:
        """Gap match key: gap_type + missing_item (normalised)."""
        missing = gap.get("missing_item", "").lower().rstrip(".,;:!?")
        return f"{gap.get('gap_type', '')}|{missing}"

    def _diff_findings(
        self,
        subject: str,
        current: list[dict[str, Any]],
        prior: list[dict[str, Any]],
    ) -> list[ReportDiffChange]:
        changes: list[ReportDiffChange] = []
        current_by_key = {self._finding_match_key(f): f for f in current}
        prior_by_key = {self._finding_match_key(f): f for f in prior}

        for key, finding in current_by_key.items():
            if key not in prior_by_key:
                changes.append(
                    ReportDiffChange(
                        change_type="new_finding",
                        subject=subject,
                        finding_summary=finding.get("title", ""),
                        current_severity=finding.get("severity"),
                        details="New finding in current run",
                    )
                )
            else:
                prior_f = prior_by_key[key]
                if finding.get("severity") != prior_f.get("severity"):
                    changes.append(
                        ReportDiffChange(
                            change_type="changed_severity",
                            subject=subject,
                            finding_summary=finding.get("title", ""),
                            prior_severity=prior_f.get("severity"),
                            current_severity=finding.get("severity"),
                        )
                    )

        for key, finding in prior_by_key.items():
            if key not in current_by_key:
                changes.append(
                    ReportDiffChange(
                        change_type="resolved_finding",
                        subject=subject,
                        finding_summary=finding.get("title", ""),
                        prior_severity=finding.get("severity"),
                    )
                )

        return changes

    def _diff_gaps(
        self,
        subject: str,
        current: list[dict[str, Any]],
        prior: list[dict[str, Any]],
    ) -> list[ReportDiffChange]:
        changes: list[ReportDiffChange] = []
        current_keys = {self._gap_match_key(g) for g in current}
        prior_keys = {self._gap_match_key(g) for g in prior}

        for g in current:
            if self._gap_match_key(g) not in prior_keys:
                changes.append(
                    ReportDiffChange(
                        change_type="new_gap",
                        subject=subject,
                        finding_summary=g.get("missing_item", ""),
                        details=f"gap_type={g.get('gap_type', '')}",
                    )
                )

        for g in prior:
            if self._gap_match_key(g) not in current_keys:
                changes.append(
                    ReportDiffChange(
                        change_type="resolved_gap",
                        subject=subject,
                        finding_summary=g.get("missing_item", ""),
                        details=f"gap_type={g.get('gap_type', '')}",
                    )
                )

        return changes

    @staticmethod
    def _build_summary(changes: list[ReportDiffChange]) -> ReportDiffSummary:
        counts: dict[str, int] = {
            "new_findings": 0,
            "resolved_findings": 0,
            "changed_severity": 0,
            "new_gaps": 0,
            "resolved_gaps": 0,
            "new_subjects": 0,
            "removed_subjects": 0,
        }
        mapping = {
            "new_finding": "new_findings",
            "resolved_finding": "resolved_findings",
            "changed_severity": "changed_severity",
            "new_gap": "new_gaps",
            "resolved_gap": "resolved_gaps",
            "new_subject": "new_subjects",
            "removed_subject": "removed_subjects",
        }
        for ch in changes:
            field = mapping.get(ch.change_type)
            if field:
                counts[field] += 1
        return ReportDiffSummary(**counts)

    # ------------------------------------------------------------------
    # File loaders
    # ------------------------------------------------------------------

    @staticmethod
    def _load_findings(merged_dir: Path) -> dict[str, list[dict[str, Any]]]:
        """Load per-subject findings from ``merged/*.json``."""
        result: dict[str, list[dict[str, Any]]] = {}
        if not merged_dir.is_dir():
            return result
        for fp in sorted(merged_dir.glob("*.json")):
            if fp.is_file():
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                    subj = data.get("subject", fp.stem)
                    findings_raw = data.get("findings", [])
                    # Normalise Finding models back to dicts if needed
                    findings: list[dict[str, Any]] = []
                    for f in findings_raw:
                        findings.append(f if isinstance(f, dict) else dict(f))
                    result[subj] = findings
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to load findings from %s", fp)
        return result

    @staticmethod
    def _load_gaps(gaps_dir: Path) -> dict[str, list[dict[str, Any]]]:
        """Load per-subject gaps from ``merged/gaps/*.json``."""
        result: dict[str, list[dict[str, Any]]] = {}
        if not gaps_dir.is_dir():
            return result
        for fp in sorted(gaps_dir.glob("*.json")):
            if fp.is_file():
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                    gaps = data if isinstance(data, list) else data.get("gaps", [])
                    subj = fp.stem
                    result[subj] = gaps
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to load gaps from %s", fp)
        return result


# ---------------------------------------------------------------------------
# Issue #126 enhancement: Multi-run trend tracking
# ---------------------------------------------------------------------------


class ReportTrendTracker:
    """Track risk trajectory across multiple pipeline runs.

    Computes whether the deal risk posture is improving, stable, or worsening
    based on weighted severity counts across snapshots.
    """

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def add_snapshot(
        self,
        run_id: str,
        severity_counts: dict[str, int],
        total_entities: int = 0,
    ) -> None:
        """Record a severity snapshot from a pipeline run."""
        self.snapshots.append(
            {
                "run_id": run_id,
                "severity_counts": dict(severity_counts),
                "total_entities": total_entities,
            }
        )

    def compute_trajectory(self) -> str:
        """Compute risk trajectory: 'improving', 'stable', or 'worsening'.

        Uses weighted severity scores (P0=10, P1=5, P2=2, P3=1).
        Compares first vs last snapshot.
        """
        if len(self.snapshots) < 2:
            return "stable"

        weights = {"P0": 10, "P1": 5, "P2": 2, "P3": 1}

        def _weighted(counts: dict[str, int]) -> float:
            return sum(counts.get(k, 0) * v for k, v in weights.items())

        first_score = _weighted(self.snapshots[0]["severity_counts"])
        last_score = _weighted(self.snapshots[-1]["severity_counts"])

        # 10% threshold for change detection
        if first_score == 0:
            return "worsening" if last_score > 0 else "stable"

        change_pct = (last_score - first_score) / first_score * 100
        if change_pct <= -10:
            return "improving"
        if change_pct >= 10:
            return "worsening"
        return "stable"

    def to_summary(self) -> dict[str, Any]:
        """Export trend data as a dict for JSON serialization."""
        return {
            "trajectory": self.compute_trajectory(),
            "snapshots": self.snapshots,
        }
