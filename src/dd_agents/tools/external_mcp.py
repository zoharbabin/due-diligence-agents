"""External verification MCP wiring (Issue #274).

Turns the ``external_verification`` deal-config block into what an agent run
needs: the MCP server spec, the tool names to allow, and the data the
pre-tool guard uses. Pure functions, no I/O beyond reading the environment
mapping passed in.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dd_agents.models.config import DealConfig, ExternalVerificationConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalAccess:
    """What one agent run may use from the external server."""

    server_name: str
    servers: dict[str, Any] = field(default_factory=dict)
    tool_names: list[str] = field(default_factory=list)


def external_tool_names(cfg: ExternalVerificationConfig) -> list[str]:
    """Return fully qualified tool names (``mcp__<server>__<tool>``). Empty when disabled."""
    if not cfg.enabled:
        return []
    return [f"mcp__{cfg.server.name}__{tool}" for tool in cfg.allowed_tools]


def build_external_mcp_servers(cfg: ExternalVerificationConfig, environ: Mapping[str, str]) -> dict[str, Any]:
    """Return the ``mcp_servers`` entry for the external server. Empty when disabled.

    Only variables named in ``env_passthrough`` are copied from *environ*.
    A named variable that is not set is skipped with a log line.
    """
    if not cfg.enabled:
        return {}
    env: dict[str, str] = {}
    for name in cfg.server.env_passthrough:
        if name in environ:
            env[name] = environ[name]
        else:
            logger.info("external_verification: %s is not set, starting the server without it", name)
    spec = {"type": "stdio", "command": cfg.server.command, "args": list(cfg.server.args), "env": env}
    return {cfg.server.name: spec}


def resolve_external_access(
    deal_config: DealConfig | None,
    environ: Mapping[str, str] | None = None,
) -> ExternalAccess | None:
    """Return the access an agent gets, or ``None`` when verification is off or unconfigured."""
    if deal_config is None:
        return None
    cfg = deal_config.external_verification
    if not cfg.enabled:
        return None
    env = os.environ if environ is None else environ
    return ExternalAccess(
        server_name=cfg.server.name,
        servers=build_external_mcp_servers(cfg, env),
        tool_names=external_tool_names(cfg),
    )
