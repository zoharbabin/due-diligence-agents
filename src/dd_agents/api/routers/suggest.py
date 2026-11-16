"""Suggest a deal config for a project. The draft is returned, never saved."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.api.projects_util import Project, room_of
from dd_agents.api.suggest import SuggestBusyError

router = APIRouter(tags=["config"])


@router.post(
    "/projects/{slug}/config/suggest",
    status_code=202,
    summary="Uses the model and costs money. Starts a draft of the deal config. Writes nothing to disk.",
)
async def start(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, str]:
    if not project.buyer.strip() or not project.target.strip():
        raise HTTPException(status_code=409, detail="Save the buyer and target names in the config first")
    try:
        ctx.suggest.start(project.slug, room_of(project), project.buyer, project.target)
    except SuggestBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"state": "running"}


@router.get(
    "/projects/{slug}/config/suggest",
    summary="Read-only. State of the draft: idle, running, done (with the config) or error.",
)
async def status(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    return ctx.suggest.status(project.slug)
