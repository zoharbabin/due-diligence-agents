"""Findings table and report downloads. All read-only."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from dd_agents.api.findings_io import load_findings, resolve_run_dir, sort_key
from dd_agents.api.projects_util import Project, skill_dir_of
from dd_agents.api.schemas import FindingsPage
from dd_agents.api.security import PathConfinementError, confine_path

router = APIRouter(tags=["findings"])

_REPORTS = {
    "html": ("dd_report.html", "text/html; charset=utf-8"),
    "xlsx": ("dd_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}


def _run_dir_or_error(skill: Path, run_id: str | None) -> Path:
    try:
        run_dir = resolve_run_dir(skill, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if run_dir is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run_dir


@router.get("/projects/{slug}/findings", summary="Read-only. Findings of a run, filtered and paged.")
def list_findings(
    project: Project,
    run_id: str | None = None,
    severity: Literal["P0", "P1", "P2", "P3"] | None = None,
    agent: Annotated[str | None, Query(max_length=60)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FindingsPage:
    run_dir = _run_dir_or_error(skill_dir_of(project), run_id)
    items = sorted(load_findings(run_dir), key=sort_key)
    facets: dict[str, dict[str, int]] = {"severity": {}, "agent": {}, "category": {}}
    for f in items:
        for key in facets:
            val = str(f.get(key))
            facets[key][val] = facets[key].get(val, 0) + 1
    needle = q.lower() if q else None
    items = [
        f
        for f in items
        if (severity is None or f.get("severity") == severity)
        and (agent is None or f.get("agent") == agent)
        and (
            needle is None
            or needle
            in f"{f.get('title', '')} {f.get('description', '')} {f.get('category', '')} {f.get('subject', '')}".lower()
        )
    ]
    return FindingsPage(run_id=run_dir.name, total=len(items), items=items[offset : offset + limit], facets=facets)


@router.get("/projects/{slug}/runs/{run_id}/report/{kind}", summary="Read-only. Download a generated report.")
def download_report(project: Project, run_id: str, kind: str) -> FileResponse:
    if kind not in _REPORTS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {sorted(_REPORTS)}")
    run_dir = _run_dir_or_error(skill_dir_of(project), run_id)
    name, media = _REPORTS[kind]
    try:
        path = confine_path(run_dir / "report" / name, [run_dir])
    except PathConfinementError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    headers = {"Content-Security-Policy": "sandbox allow-scripts"} if kind == "html" else None
    return FileResponse(path, media_type=media, headers=headers, filename=name if kind != "html" else None)
