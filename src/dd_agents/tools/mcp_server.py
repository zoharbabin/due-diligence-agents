"""MCP server builder for agent tool access.

Creates an in-process MCP server using ``create_sdk_mcp_server`` from
``claude_agent_sdk``, registering all custom DD tools.  When the SDK is
not installed, returns ``None`` so callers can degrade gracefully.

NOTE: The existing tool definitions in ``server.py`` use dict-based schemas
with string handler paths.  The SDK's ``create_sdk_mcp_server`` requires
``SdkMcpTool`` objects created via the ``@tool`` decorator.  Until the tool
modules are migrated to the ``@tool`` decorator pattern, this builder returns
``None``.  Hooks (pre-tool, stop) are fully wired; MCP tools are the next
migration step.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_mcp_server(agent_type: str = "specialist") -> Any | None:
    """Build an in-process MCP server with DD tools for the given agent type.

    Parameters
    ----------
    agent_type:
        One of ``"specialist"`` or ``"judge"``.  Controls which tools are
        registered on the server.

    Returns
    -------
    An MCP server object suitable for ``ClaudeAgentOptions(mcp_servers=...)``,
    or ``None`` if tools have not been migrated to the ``@tool`` decorator yet.
    """
    # TODO: Migrate tool modules from dict-based definitions to @tool decorator
    # pattern, then wire them into create_sdk_mcp_server here.
    # See: src/dd_agents/tools/server.py for current tool definitions.
    logger.debug(
        "MCP server not yet available for agent_type=%r — tool modules need @tool decorator migration",
        agent_type,
    )
    return None
