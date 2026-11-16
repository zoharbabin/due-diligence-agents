"""FastAPI application factory for ``dd-agents serve``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import dd_agents
from dd_agents.api.context import AppContext
from dd_agents.api.routers import config, findings, health, projects, runs
from dd_agents.api.runs import RunManager
from dd_agents.api.security import MIN_TOKEN_LENGTH, SecurityMiddleware
from dd_agents.persistence.project_registry import ProjectRegistryManager


def create_app(
    *,
    token: str,
    registry_dir: Path | None = None,
    ui_dir: Path | None = None,
    run_manager: RunManager | None = None,
) -> FastAPI:
    """Build the API app.

    ``ui_dir`` is the built web UI. Serving it from the same origin means the
    browser never makes a cross-origin call, so no CORS is needed.
    """
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"token must be at least {MIN_TOKEN_LENGTH} characters")
    registry = ProjectRegistryManager(registry_dir)
    manager = run_manager or RunManager(registry)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        manager.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title="Due Diligence Agents local API",
        version=dd_agents.__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.ctx = AppContext(registry=registry, runs=manager)
    app.add_middleware(SecurityMiddleware, token=token)
    for module in (health, projects, config, runs, findings):
        app.include_router(module.router, prefix="/api")
    if ui_dir is not None and ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")
    return app
