"""Shared server state, injected into routes with ``Depends(get_ctx)``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from dd_agents.api.runs import RunManager
    from dd_agents.llm.cli_provision import CliInstaller
    from dd_agents.persistence.project_registry import ProjectRegistryManager


@dataclass
class AppContext:
    registry: ProjectRegistryManager
    runs: RunManager
    cli_installer: CliInstaller


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx
