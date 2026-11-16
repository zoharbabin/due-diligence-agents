"""Read a run's merged findings from disk. Read-only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dd_agents.api.security import PathConfinementError, confine_path

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


@dataclass
class RunSummaryData:
    subjects: int = 0
    total: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    risk_score: float = 0.0


def resolve_run_dir(skill_dir: Path, run_id: str | None) -> Path | None:
    """Return the run directory, or None if it does not exist. Raises ValueError on a bad id."""
    runs = skill_dir / "runs"
    name = run_id or "latest"
    if not RUN_ID_RE.match(name):
        raise ValueError(f"invalid run id {name!r}")
    try:
        path = confine_path(runs / name, [runs])
    except PathConfinementError:
        return None
    return path if path.is_dir() else None


def list_run_ids(skill_dir: Path) -> list[str]:
    runs = skill_dir / "runs"
    if not runs.is_dir():
        return []
    return sorted((p.name for p in runs.iterdir() if p.is_dir() and not p.is_symlink()), reverse=True)


def load_findings(run_dir: Path) -> list[dict[str, Any]]:
    """All findings of a run, each tagged with its subject. Unreadable files are skipped."""
    out: list[dict[str, Any]] = []
    merged = run_dir / "findings" / "merged"
    if not merged.is_dir():
        return out
    for path in sorted(merged.glob("*.json")):
        if path.stem.startswith("_"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        subject = str(doc.get("subject", path.stem))
        for f in doc.get("findings", []):
            if isinstance(f, dict):
                out.append({**f, "subject": subject, "subject_safe_name": doc.get("subject_safe_name", path.stem)})
    return out


def sort_key(finding: dict[str, Any]) -> tuple[int, str, str]:
    return (
        SEVERITY_ORDER.get(str(finding.get("severity")), 9),
        str(finding.get("subject", "")),
        str(finding.get("id", "")),
    )


def summarize_run(run_dir: Path) -> RunSummaryData:
    from dd_agents.reporting.computed_metrics import ReportDataComputer

    findings = load_findings(run_dir)
    counts: dict[str, int] = {}
    for f in findings:
        sev = str(f.get("severity"))
        counts[sev] = counts.get(sev, 0) + 1
    return RunSummaryData(
        subjects=len({f["subject_safe_name"] for f in findings}),
        total=len(findings),
        by_severity=counts,
        # Same formula the report uses, so the registry and the report agree.
        risk_score=ReportDataComputer._compute_risk_score(counts),
    )
