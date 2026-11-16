"""Run control and progress events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.api.findings_io import list_run_ids, resolve_run_dir
from dd_agents.api.projects_util import Project, config_path_of, skill_dir_of
from dd_agents.api.runs import EVENTS_NAME, RunConfigError, RunConflictError, RunOptions
from dd_agents.api.schemas import RunSummary
from dd_agents.config import ConfigError, ConfigFileNotFoundError, ConfigValidationError
from dd_agents.models.events import RunEvent, RunEventType
from dd_agents.orchestrator.events import read_events

router = APIRouter(tags=["runs"])

_TERMINAL = {RunEventType.RUN_COMPLETED, RunEventType.RUN_FAILED}
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0


@router.post(
    "/projects/{slug}/run",
    status_code=202,
    summary="Starts a pipeline run (spawns a process, writes the data room's _dd folder and calls the LLM provider).",
)
def start_run(project: Project, options: RunOptions, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, object]:
    try:
        ctx.runs.start(project, config_path_of(project), options)
    except RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RunConfigError as exc:
        raise HTTPException(status_code=409 if exc.missing else 422, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        errors = [
            {"loc": " -> ".join(str(p) for p in e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.validation_error.errors()
        ]
        raise HTTPException(status_code=422, detail={"message": "Config is not valid", "errors": errors}) from exc
    except ConfigFileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    fresh = ctx.registry.get_project(project.slug)
    assert fresh is not None
    return ctx.runs.state(fresh)


@router.get("/projects/{slug}/run", summary="Read-only. Current or last run state.")
def run_state(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, object]:
    fresh = ctx.registry.get_project(project.slug) or project
    return ctx.runs.state(fresh)


@router.post(
    "/projects/{slug}/run/cancel",
    summary="Stops the running pipeline process and its children. Finished work stays on disk.",
)
def cancel_run(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, str]:
    try:
        ctx.runs.cancel(project.slug)
    except RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "cancelling"}


@router.get("/projects/{slug}/runs", summary="Read-only. Past runs, newest first.")
def list_runs(project: Project) -> list[RunSummary]:
    skill = skill_dir_of(project)
    latest = resolve_run_dir(skill, None)
    out: list[RunSummary] = []
    for rid in list_run_ids(skill):
        run_dir = skill / "runs" / rid
        report_dir = run_dir / "report"
        reports = [
            k for k, name in (("html", "dd_report.html"), ("xlsx", "dd_report.xlsx")) if (report_dir / name).is_file()
        ]
        out.append(
            RunSummary(
                run_id=rid,
                is_latest=latest is not None and latest.name == rid,
                has_findings=(run_dir / "findings" / "merged").is_dir(),
                reports=reports,
            )
        )
    return out


@router.get("/projects/{slug}/events", summary="Read-only. Run events after a sequence number.")
def get_events(project: Project, after: Annotated[int, Query(ge=0)] = 0) -> list[dict[str, Any]]:
    events = read_events(skill_dir_of(project) / EVENTS_NAME, after)
    return [e.model_dump(mode="json") for e in events]


def _frame(event: RunEvent) -> str:
    return f"id: {event.seq}\nevent: {event.type.value}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"


@router.get("/projects/{slug}/events/stream", summary="Read-only. Server-sent stream of run events.")
async def stream_events(
    request: Request,
    project: Project,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = max(cursor, int(last_event_id))
    path = skill_dir_of(project) / EVENTS_NAME
    slug = project.slug

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        last_sent = asyncio.get_running_loop().time()
        while True:
            events = await asyncio.to_thread(read_events, path, cursor)
            if events and events[0].seq <= cursor:  # file was reset by a new run
                cursor = 0
            for event in events:
                cursor = event.seq
                last_sent = asyncio.get_running_loop().time()
                yield _frame(event)
            handle = ctx.runs.handle(slug)
            active = handle is not None and handle.status == "running"
            terminal = any(e.type in _TERMINAL and (handle is None or e.seq > handle.base_seq) for e in events)
            if terminal or (not active and not events):
                return
            if await request.is_disconnected():
                return
            now = asyncio.get_running_loop().time()
            if now - last_sent >= KEEPALIVE_SECONDS:
                last_sent = now
                yield ": keepalive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
