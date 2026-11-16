"""Sanctions screening: list coverage, list update, and a one-name check."""

from __future__ import annotations

import threading
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dd_agents.api.projects_util import Project, room_of
from dd_agents.screening import store
from dd_agents.screening.service import ScreeningService, ScreenTarget
from dd_agents.screening.sources import SOURCES

router = APIRouter(tags=["screening"])

# One download at a time. A second request gets 409 instead of racing the first on the same files.
_update_lock = threading.Lock()


class UpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str] | None = Field(default=None, description="List ids to download. Default: all.")

    @field_validator("sources")
    @classmethod
    def _known(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - set(SOURCES))
        if unknown:
            raise ValueError(f"Unknown list: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=300)]
    kind: Literal["person", "organization"]
    birth_year: Annotated[int, Field(ge=1800, le=2200)] | None = None
    country: Annotated[str, Field(max_length=100)] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a name")
        return value


@router.get("/screening", summary="Read-only. Which sanctions lists are stored and how fresh they are.")
def coverage() -> dict[str, Any]:
    rows = store.coverage(list(SOURCES))
    return {"max_age_days": store.LIST_MAX_AGE_DAYS, "sources": [r.model_dump() for r in rows]}


@router.post(
    "/screening/update",
    summary="Uses the network and writes to local storage. Downloads official sanctions lists. Safe to repeat.",
)
def update(body: UpdateRequest) -> dict[str, Any]:
    if not _update_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A list update is already running")
    try:
        results: list[dict[str, Any]] = []
        for source_id in body.sources or list(SOURCES):
            try:
                snapshot = store.update(source_id)
            except store.StoreError as exc:
                results.append({"source": source_id, "ok": False, "error": str(exc)})
            else:
                results.append(
                    {
                        "source": source_id,
                        "ok": True,
                        "entries": len(snapshot.entries),
                        "published": snapshot.published,
                    }
                )
        return {"results": results}
    finally:
        _update_lock.release()


@router.post(
    "/projects/{slug}/screening/check",
    summary="Read-only, no network. Screens one name against the stored lists and the project's own lists.",
)
def check(project: Project, body: CheckRequest) -> dict[str, Any]:
    target = ScreenTarget(name=body.name, kind=body.kind, birth_year=body.birth_year, country=body.country)
    report = ScreeningService.load(room_of(project)).screen([target])
    return {"complete": report.complete, **report.model_dump(mode="json")}
