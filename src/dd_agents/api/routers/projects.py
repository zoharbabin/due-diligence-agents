"""Projects: list, create, read, remove, scan."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.api.projects_util import SKILL_DIR, Project, room_of
from dd_agents.api.schemas import ProjectCreate, ScanSummary
from dd_agents.models.project import ProjectEntry

router = APIRouter(tags=["projects"])

# Stops a scan of a huge folder from running forever. The UI shows "and more".
MAX_SCAN_FILES = 200_000


@router.get("/projects", summary="Read-only. List registered projects.")
def list_projects(ctx: Annotated[AppContext, Depends(get_ctx)]) -> list[ProjectEntry]:
    return ctx.registry.list_projects()


@router.post(
    "/projects",
    status_code=201,
    summary="Writes the project registry. Registers a data room folder as a project.",
)
def create_project(body: ProjectCreate, ctx: Annotated[AppContext, Depends(get_ctx)]) -> ProjectEntry:
    room = Path(body.data_room).expanduser()
    if not room.is_absolute() or not room.is_dir():
        raise HTTPException(status_code=422, detail="data_room must be an existing absolute folder path")
    try:
        return ctx.registry.add_project(body.name, room, deal_type=body.deal_type)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{slug}", summary="Read-only. One project.")
def get_project(project: Project) -> ProjectEntry:
    return project


@router.delete(
    "/projects/{slug}",
    status_code=204,
    summary="Writes the project registry. Unregisters a project. Never deletes the data room.",
)
def delete_project(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> Response:
    if ctx.runs.is_running(project.slug):
        raise HTTPException(status_code=409, detail="A run is in progress. Cancel it first.")
    ctx.registry.remove_project(project.slug)
    return Response(status_code=204)


@router.get("/projects/{slug}/scan", summary="Read-only. Count files in the data room by extension.")
def scan_project(project: Project) -> ScanSummary:
    room = room_of(project)
    skip = SKILL_DIR.parts[0]
    by_ext: dict[str, int] = {}
    total = size = 0
    truncated = False
    for root, dirs, files in os.walk(room, followlinks=False):
        if Path(root) == room:
            dirs[:] = [d for d in dirs if d != skip]
        for name in files:
            p = Path(root) / name
            if p.is_symlink():
                continue
            if total >= MAX_SCAN_FILES:
                truncated = True
                break
            total += 1
            with contextlib.suppress(OSError):
                size += p.stat().st_size
            ext = p.suffix.lower() or "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
        if truncated:
            break
    return ScanSummary(
        total_files=total, total_bytes=size, by_extension=dict(sorted(by_ext.items())), truncated=truncated
    )
