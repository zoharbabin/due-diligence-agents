"""Finding indexer for the query engine (Issue #124).

Reads merged findings from a pipeline run directory and builds
in-memory indices for fast filtering and retrieval.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, Field

from dd_agents.utils.constants import ALL_SEVERITIES

logger = logging.getLogger(__name__)


class FindingIndex(BaseModel):
    """In-memory index over merged DD findings."""

    findings: list[dict[str, Any]] = Field(default_factory=list, description="All indexed findings")
    by_subject: dict[str, list[int]] = Field(default_factory=dict, description="Subject safe name → finding indices")
    by_category: dict[str, list[int]] = Field(default_factory=dict, description="Category → finding indices")
    by_severity: dict[str, list[int]] = Field(default_factory=dict, description="Severity → finding indices")
    by_domain: dict[str, list[int]] = Field(default_factory=dict, description="Domain → finding indices")
    total_findings: int = 0
    summary: str = ""


class FindingIndexer:
    """Index merged findings from a pipeline run directory.

    Usage::

        indexer = FindingIndexer()
        index = indexer.index_report(Path("_dd/forensic-dd/runs/latest"))
    """

    def index_report(self, run_dir: Path) -> FindingIndex:
        """Load and index all merged findings from *run_dir*.

        Searches for JSON files in ``findings/merged/`` under the run
        directory.  Each file should contain a list of finding dicts.
        """
        merged_dir = run_dir / "findings" / "merged"
        if not merged_dir.is_dir():
            # Try direct path if run_dir itself contains findings
            merged_dir = run_dir
            if not any(merged_dir.glob("*.json")):
                logger.warning("No merged findings found in %s", run_dir)
                return FindingIndex(summary="No findings found.")

        all_findings: list[dict[str, Any]] = []
        for json_file in sorted(merged_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    all_findings.extend(data)
                elif isinstance(data, dict) and "findings" in data:
                    all_findings.extend(data["findings"])
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read %s: %s", json_file, exc)

        return self.index_findings(all_findings)

    def index_findings(self, findings: list[dict[str, Any]]) -> FindingIndex:
        """Build an index from a list of finding dicts."""
        by_subject: dict[str, list[int]] = defaultdict(list)
        by_category: dict[str, list[int]] = defaultdict(list)
        by_severity: dict[str, list[int]] = defaultdict(list)
        by_domain: dict[str, list[int]] = defaultdict(list)

        for idx, f in enumerate(findings):
            csn = str(f.get("_subject_safe_name", f.get("subject", "")))
            if csn:
                by_subject[csn].append(idx)

            cat = str(f.get("category", ""))
            if cat:
                by_category[cat].append(idx)

            sev = str(f.get("severity", ""))
            if sev:
                by_severity[sev].append(idx)

            domain = str(f.get("agent", f.get("domain", "")))
            if domain:
                by_domain[domain].append(idx)

        summary = self._build_summary(findings, by_severity, by_domain)

        return FindingIndex(
            findings=findings,
            by_subject=dict(by_subject),
            by_category=dict(by_category),
            by_severity=dict(by_severity),
            by_domain=dict(by_domain),
            total_findings=len(findings),
            summary=summary,
        )

    @staticmethod
    def _build_summary(
        findings: list[dict[str, Any]],
        by_severity: dict[str, list[int]],
        by_domain: dict[str, list[int]],
    ) -> str:
        """Build a concise text summary of the indexed findings."""
        total = len(findings)
        if total == 0:
            return "No findings indexed."

        parts = [f"{total} findings indexed."]

        sev_parts: list[str] = []
        for sev in [*ALL_SEVERITIES, "P4"]:
            count = len(by_severity.get(sev, []))
            if count:
                sev_parts.append(f"{count} {sev}")
        if sev_parts:
            parts.append(f"Severity: {', '.join(sev_parts)}.")

        domain_parts = [f"{d}: {len(idxs)}" for d, idxs in sorted(by_domain.items()) if idxs]
        if domain_parts:
            parts.append(f"Domains: {', '.join(domain_parts)}.")

        return " ".join(parts)
