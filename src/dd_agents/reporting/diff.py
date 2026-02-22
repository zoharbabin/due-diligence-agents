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

    Matching is done on ``customer + category + citation source_path``.
    Detected change types:
    - new_finding / resolved_finding
    - changed_severity
    - new_gap / resolved_gap
    - new_customer / removed_customer
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

        Each directory is expected to contain per-customer JSON files under
        ``merged/`` and gap JSON files under ``merged/gaps/``.
        """
        current_findings = self._load_findings(current_findings_dir / "merged")
        prior_findings = self._load_findings(prior_findings_dir / "merged")
        current_gaps = self._load_gaps(current_findings_dir / "merged" / "gaps")
        prior_gaps = self._load_gaps(prior_findings_dir / "merged" / "gaps")

        changes: list[ReportDiffChange] = []

        current_customers = set(current_findings.keys())
        prior_customers = set(prior_findings.keys())

        # Customer-level changes
        for c in sorted(current_customers - prior_customers):
            changes.append(
                ReportDiffChange(
                    change_type="new_customer",
                    customer=c,
                    details="New customer in current run",
                )
            )
        for c in sorted(prior_customers - current_customers):
            changes.append(
                ReportDiffChange(
                    change_type="removed_customer",
                    customer=c,
                    details="Customer removed from current run",
                )
            )

        # Finding + gap level changes for shared customers
        for customer in sorted(current_customers & prior_customers):
            changes.extend(
                self._diff_findings(
                    customer,
                    current_findings[customer],
                    prior_findings[customer],
                )
            )
            changes.extend(
                self._diff_gaps(
                    customer,
                    current_gaps.get(customer, []),
                    prior_gaps.get(customer, []),
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
        output_path.write_text(diff.model_dump_json(indent=2))

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
        customer: str,
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
                        customer=customer,
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
                            customer=customer,
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
                        customer=customer,
                        finding_summary=finding.get("title", ""),
                        prior_severity=finding.get("severity"),
                    )
                )

        return changes

    def _diff_gaps(
        self,
        customer: str,
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
                        customer=customer,
                        finding_summary=g.get("missing_item", ""),
                        details=f"gap_type={g.get('gap_type', '')}",
                    )
                )

        for g in prior:
            if self._gap_match_key(g) not in current_keys:
                changes.append(
                    ReportDiffChange(
                        change_type="resolved_gap",
                        customer=customer,
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
            "new_customers": 0,
            "removed_customers": 0,
        }
        mapping = {
            "new_finding": "new_findings",
            "resolved_finding": "resolved_findings",
            "changed_severity": "changed_severity",
            "new_gap": "new_gaps",
            "resolved_gap": "resolved_gaps",
            "new_customer": "new_customers",
            "removed_customer": "removed_customers",
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
        """Load per-customer findings from ``merged/*.json``."""
        result: dict[str, list[dict[str, Any]]] = {}
        if not merged_dir.is_dir():
            return result
        for fp in sorted(merged_dir.glob("*.json")):
            if fp.is_file():
                try:
                    data = json.loads(fp.read_text())
                    customer = data.get("customer", fp.stem)
                    findings_raw = data.get("findings", [])
                    # Normalise Finding models back to dicts if needed
                    findings: list[dict[str, Any]] = []
                    for f in findings_raw:
                        findings.append(f if isinstance(f, dict) else dict(f))
                    result[customer] = findings
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to load findings from %s", fp)
        return result

    @staticmethod
    def _load_gaps(gaps_dir: Path) -> dict[str, list[dict[str, Any]]]:
        """Load per-customer gaps from ``merged/gaps/*.json``."""
        result: dict[str, list[dict[str, Any]]] = {}
        if not gaps_dir.is_dir():
            return result
        for fp in sorted(gaps_dir.glob("*.json")):
            if fp.is_file():
                try:
                    data = json.loads(fp.read_text())
                    gaps = data if isinstance(data, list) else data.get("gaps", [])
                    customer = fp.stem
                    result[customer] = gaps
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to load gaps from %s", fp)
        return result
