"""FastAPI application factory for ``dd-agents serve``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import dd_agents
from dd_agents.api.chat import ChatFactory, ChatSessions
from dd_agents.api.context import AppContext
from dd_agents.api.routers import (
    agents,
    chat,
    compare,
    config,
    doctor,
    findings,
    health,
    history,
    projects,
    runs,
    settings,
)
from dd_agents.api.runs import RunManager
from dd_agents.api.security import MIN_TOKEN_LENGTH, SecurityMiddleware
from dd_agents.llm.cli_provision import CliInstaller
from dd_agents.persistence.project_registry import ProjectRegistryManager


def create_app(
    *,
    token: str,
    registry_dir: Path | None = None,
    ui_dir: Path | None = None,
    run_manager: RunManager | None = None,
    cli_installer: CliInstaller | None = None,
    chat_factory: ChatFactory | None = None,
) -> FastAPI:
    """Build the API app.

    ``ui_dir`` is the built web UI. Serving it from the same origin means the
    browser never makes a cross-origin call, so no CORS is needed.
    """
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"token must be at least {MIN_TOKEN_LENGTH} characters")
    registry = ProjectRegistryManager(registry_dir)
    manager = run_manager or RunManager(registry)
    sessions = ChatSessions(chat_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await sessions.close_all()
        manager.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title="Due Diligence Agents local API",
        version=dd_agents.__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.ctx = AppContext(
        registry=registry, runs=manager, cli_installer=cli_installer or CliInstaller(), chat=sessions
    )
    app.add_middleware(SecurityMiddleware, token=token)
    for module in (health, doctor, settings, projects, config, agents, compare, runs, findings, chat, history):
        app.include_router(module.router, prefix="/api")
    if ui_dir is not None and ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")
    return app
