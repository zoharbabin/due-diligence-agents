"""Run-vs-run compare. Read-only. Uses the same engine as ``dd-agents diff``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from dd_agents.api.findings_io import list_run_ids, resolve_run_dir
from dd_agents.api.projects_util import Project, skill_dir_of
from dd_agents.reporting.diff import ReportDiffBuilder

router = APIRouter(tags=["compare"])


def _findings_dir(skill_dir: Any, run_id: str) -> Any:
    try:
        run_dir = resolve_run_dir(skill_dir, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if run_dir is None:
        raise HTTPException(status_code=404, detail=f"No run '{run_id}'")
    return run_dir / "findings"


@router.get(
    "/projects/{slug}/compare",
    summary="Read-only. What is new, resolved or changed between two runs. Defaults to the two newest runs.",
)
def compare_runs(project: Project, current: str | None = None, prior: str | None = None) -> dict[str, Any]:
    skill = skill_dir_of(project)
    if current is None or prior is None:
        newest = [r for r in list_run_ids(skill) if (skill / "runs" / r / "findings" / "merged").is_dir()]
        if len(newest) < 2:
            raise HTTPException(status_code=404, detail="Comparing needs two runs with findings")
        current, prior = current or newest[0], prior or newest[1]
    diff = ReportDiffBuilder().build_diff(
        _findings_dir(skill, current), _findings_dir(skill, prior), current_run_id=current, prior_run_id=prior
    )
    return diff.model_dump()
