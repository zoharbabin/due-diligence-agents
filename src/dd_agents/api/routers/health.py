"""Liveness and version."""

from __future__ import annotations

from fastapi import APIRouter

import dd_agents

router = APIRouter(tags=["health"])


@router.get("/health", summary="Read-only. Liveness and version.")
def health() -> dict[str, str]:
    return {"status": "ok", "version": dd_agents.__version__}
