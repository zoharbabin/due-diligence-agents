"""Ask: questions about a project's latest review, answered from its findings."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from dd_agents.api.chat import ChatBusyError
from dd_agents.api.context import AppContext, get_ctx
from dd_agents.api.findings_io import resolve_run_dir
from dd_agents.api.projects_util import Project, room_of, skill_dir_of
from dd_agents.chat.engine import ChatError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

MAX_QUESTION_CHARS = 4000


class Question(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Type a question")
        return value.strip()


def _latest_with_findings(project: Project) -> Any:
    run_dir = resolve_run_dir(skill_dir_of(project), None)
    if run_dir is None or not (run_dir / "findings" / "merged").is_dir():
        return None
    return run_dir


@router.get("/projects/{slug}/chat", summary="Read-only. Whether Ask is ready, and the current session's usage.")
def chat_status(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    return {"ready": _latest_with_findings(project) is not None, **ctx.chat.status(project.slug)}


@router.post(
    "/projects/{slug}/chat",
    summary="Asks one question about the latest review (calls the LLM provider, costs money, "
    "may write notes under the data room's _dd/forensic-dd/chat). Streams server-sent events.",
)
async def ask(project: Project, body: Question, ctx: Annotated[AppContext, Depends(get_ctx)]) -> StreamingResponse:
    run_dir = _latest_with_findings(project)
    if run_dir is None:
        raise HTTPException(status_code=409, detail="Ask needs a finished review. Run one first")
    try:
        frames: AsyncIterator[str] = await ctx.chat.begin(project.slug, run_dir, room_of(project), body.question)
    except ChatBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("could not start chat")
        raise HTTPException(status_code=500, detail="Could not start the chat session") from exc
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.delete(
    "/projects/{slug}/chat",
    status_code=204,
    summary="Ends the chat session and saves its notes. Safe to repeat.",
)
async def reset_chat(project: Project, ctx: Annotated[AppContext, Depends(get_ctx)]) -> Response:
    try:
        await ctx.chat.reset(project.slug)
    except ChatBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)
