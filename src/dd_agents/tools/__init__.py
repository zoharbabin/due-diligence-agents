"""dd_agents.tools subpackage -- MCP tool exports."""

from __future__ import annotations

from dd_agents.tools.get_customer_files import get_customer_files
from dd_agents.tools.mcp_server import build_mcp_server
from dd_agents.tools.read_office import read_office
from dd_agents.tools.report_progress import report_progress
from dd_agents.tools.resolve_entity import resolve_entity
from dd_agents.tools.server import (
    JUDGE_CUSTOM_TOOLS,
    SPECIALIST_CUSTOM_TOOLS,
    create_tool_definitions,
    get_tools_for_agent,
)
from dd_agents.tools.validate_finding import validate_finding
from dd_agents.tools.validate_gap import validate_gap
from dd_agents.tools.validate_manifest import validate_manifest
from dd_agents.tools.verify_citation import verify_citation

__all__ = [
    # Server
    "build_mcp_server",
    "create_tool_definitions",
    "get_tools_for_agent",
    "SPECIALIST_CUSTOM_TOOLS",
    "JUDGE_CUSTOM_TOOLS",
    # Tool functions
    "validate_finding",
    "validate_gap",
    "validate_manifest",
    "verify_citation",
    "get_customer_files",
    "resolve_entity",
    "read_office",
    "report_progress",
]
