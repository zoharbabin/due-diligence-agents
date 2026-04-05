"""MCP server builder for agent tool access.

Creates an in-process MCP server using ``create_sdk_mcp_server`` from
``claude_agent_sdk``, registering all custom DD tools as ``@tool``-decorated
async handlers.

Tools that need runtime context (file paths, inventory data) receive it
via closures bound at server-creation time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.tools.server import get_tools_for_agent

logger = logging.getLogger(__name__)


def build_mcp_server(
    agent_type: str = "specialist",
    *,
    text_dir: str | Path | None = None,
    files_list: list[str] | None = None,
    customers_csv: list[dict[str, Any]] | None = None,
    cache_path: str | Path | None = None,
    allowed_dir: str | Path | None = None,
) -> Any | None:
    """Build an in-process MCP server with DD tools for the given agent type.

    Parameters
    ----------
    agent_type:
        One of ``"specialist"`` or ``"judge"``.  Controls which tools are
        registered on the server.
    text_dir:
        Path to the extracted text directory (``index/text/``).
        Required by ``verify_citation`` and ``read_office``.
    files_list:
        List of known file paths from inventory.
        Required by ``verify_citation``.
    customers_csv:
        List of customer dicts from the inventory CSV.
        Required by ``get_customer_files``.
    cache_path:
        Path to ``entity_resolution_cache.json``.
        Required by ``resolve_entity``.
    allowed_dir:
        Base directory for path containment checks (prevents traversal).
        Used by ``verify_citation`` and ``read_office``.

    Returns
    -------
    An MCP server config dict suitable for
    ``ClaudeAgentOptions(mcp_servers={"dd_tools": ...})``, or ``None``
    if the SDK is not installed.
    """
    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool
    except ImportError:
        logger.debug("claude_agent_sdk not installed — MCP server unavailable")
        return None

    allowed_tool_names = set(get_tools_for_agent(agent_type))
    if not allowed_tool_names:
        logger.debug("No custom tools configured for agent_type=%r", agent_type)
        return None

    tools: list[Any] = []

    # ------------------------------------------------------------------
    # Context-free tools (no runtime paths needed)
    # ------------------------------------------------------------------

    if "validate_finding" in allowed_tool_names:
        from dd_agents.tools.validate_finding import validate_finding as _validate_finding

        @tool(
            "validate_finding",
            "Validate a finding JSON against the schema. Returns 'valid' or error details.",
            {
                "type": "object",
                "properties": {
                    "finding_json": {
                        "type": "object",
                        "description": "A single finding object to validate",
                    }
                },
                "required": ["finding_json"],
            },
        )
        async def validate_finding_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _validate_finding(input_data["finding_json"])

        tools.append(validate_finding_tool)

    if "validate_gap" in allowed_tool_names:
        from dd_agents.tools.validate_gap import validate_gap as _validate_gap

        @tool(
            "validate_gap",
            "Validate a gap JSON against the schema. Returns 'valid' or error details.",
            {
                "type": "object",
                "properties": {
                    "gap_json": {
                        "type": "object",
                        "description": "A single gap object to validate",
                    }
                },
                "required": ["gap_json"],
            },
        )
        async def validate_gap_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _validate_gap(input_data["gap_json"])

        tools.append(validate_gap_tool)

    if "validate_manifest" in allowed_tool_names:
        from dd_agents.tools.validate_manifest import validate_manifest as _validate_manifest

        @tool(
            "validate_manifest",
            "Validate a coverage_manifest.json. Returns 'valid' or error details.",
            {
                "type": "object",
                "properties": {
                    "manifest_json": {
                        "type": "object",
                        "description": "The coverage manifest object to validate",
                    }
                },
                "required": ["manifest_json"],
            },
        )
        async def validate_manifest_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _validate_manifest(input_data["manifest_json"])

        tools.append(validate_manifest_tool)

    if "report_progress" in allowed_tool_names:
        from dd_agents.tools.report_progress import report_progress as _report_progress

        @tool(
            "report_progress",
            "Report progress to the orchestrator. Returns a progress snapshot.",
            {
                "type": "object",
                "properties": {
                    "agent_name": {"type": "string", "description": "Name of the reporting agent"},
                    "customers_processed": {"type": "integer", "description": "Count of customers completed so far"},
                    "total_customers": {"type": "integer", "description": "Total customers assigned"},
                    "current_customer": {"type": "string", "description": "Customer currently being processed"},
                },
                "required": ["agent_name", "customers_processed", "total_customers", "current_customer"],
            },
        )
        async def report_progress_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _report_progress(
                agent_name=input_data["agent_name"],
                customers_processed=input_data["customers_processed"],
                total_customers=input_data["total_customers"],
                current_customer=input_data["current_customer"],
            )

        tools.append(report_progress_tool)

    if "search_similar" in allowed_tool_names:
        from dd_agents.tools.search_similar import search_similar as _search_similar

        @tool(
            "search_similar",
            "Search for semantically similar clauses or text across the document corpus. "
            "Returns matching text snippets with relevance scores.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query (e.g., 'change of control clause')",
                    },
                    "customer": {"type": "string", "description": "Optional customer_safe_name to filter results"},
                    "top_k": {"type": "integer", "description": "Maximum number of results (1-20, default 5)"},
                },
                "required": ["query"],
            },
        )
        async def search_similar_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _search_similar(
                query=input_data["query"],
                customer=input_data.get("customer"),
                top_k=input_data.get("top_k", 5),
            )

        tools.append(search_similar_tool)

    # ------------------------------------------------------------------
    # Context-dependent tools (bind runtime paths via closure)
    # ------------------------------------------------------------------

    if "verify_citation" in allowed_tool_names:
        from dd_agents.tools.verify_citation import verify_citation as _verify_citation

        # Bind runtime context
        _vc_files_list = files_list or []
        _vc_text_dir = str(text_dir) if text_dir else ""
        _vc_allowed_dir = str(allowed_dir) if allowed_dir else None

        @tool(
            "verify_citation",
            "Verify that exact_quote exists in the source document's extracted text. Returns verification result.",
            {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Original file path (e.g., './Above 200K/Acme/MSA.pdf')",
                    },
                    "exact_quote": {"type": "string", "description": "The exact quote to verify"},
                },
                "required": ["source_path", "exact_quote"],
            },
        )
        async def verify_citation_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            citation = {
                "source_path": input_data["source_path"],
                "exact_quote": input_data.get("exact_quote", ""),
            }
            return _verify_citation(
                citation=citation,
                files_list=_vc_files_list,
                text_dir=_vc_text_dir,
                allowed_dir=_vc_allowed_dir,
            )

        tools.append(verify_citation_tool)

    if "get_customer_files" in allowed_tool_names:
        from dd_agents.tools.get_customer_files import get_customer_files as _get_customer_files

        _gcf_customers_csv = customers_csv or []

        @tool(
            "get_customer_files",
            "Return the file list and count for a customer. Use customer_safe_name (e.g., 'acme_corp').",
            {
                "type": "object",
                "properties": {
                    "customer_safe_name": {
                        "type": "string",
                        "description": "The customer_safe_name from the assignment",
                    }
                },
                "required": ["customer_safe_name"],
            },
        )
        async def get_customer_files_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _get_customer_files(
                customer_safe_name=input_data["customer_safe_name"],
                customers_csv=_gcf_customers_csv,
            )

        tools.append(get_customer_files_tool)

    if "resolve_entity" in allowed_tool_names:
        from dd_agents.tools.resolve_entity import resolve_entity as _resolve_entity

        _re_cache_path = str(cache_path) if cache_path else ""

        @tool(
            "resolve_entity",
            "Look up a name in the entity resolution cache to find the canonical customer name. "
            "Returns the canonical name and match method, or 'unresolved'.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The entity name to look up"},
                },
                "required": ["name"],
            },
        )
        async def resolve_entity_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _resolve_entity(name=input_data["name"], cache_path=_re_cache_path)

        tools.append(resolve_entity_tool)

    if "read_office" in allowed_tool_names:
        from dd_agents.tools.read_office import read_office as _read_office

        _ro_text_dir = str(text_dir) if text_dir else None
        _ro_allowed_dir = str(allowed_dir) if allowed_dir else None

        @tool(
            "read_office",
            "Read the contents of a binary Office file (.xlsx, .xls, .docx, .doc, .pptx, .ppt). "
            "Returns structured text content. Use this instead of the Read tool for Office files.",
            {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the Office file to read"},
                    "sheet_name": {
                        "type": "string",
                        "description": "For Excel files: specific sheet name to read. Omit to read all sheets.",
                    },
                },
                "required": ["file_path"],
            },
        )
        async def read_office_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _read_office(
                file_path=input_data["file_path"],
                sheet_name=input_data.get("sheet_name"),
                text_dir=_ro_text_dir,
                allowed_dir=_ro_allowed_dir,
            )

        tools.append(read_office_tool)

    if not tools:
        logger.debug("No tools registered for agent_type=%r", agent_type)
        return None

    server = create_sdk_mcp_server(name="dd_tools", version="1.0.0", tools=tools)
    tool_names = [t.name for t in tools]
    logger.info("MCP server built for agent_type=%r with %d tools: %s", agent_type, len(tools), tool_names)
    return server


def _build_runtime_context(
    project_dir: Path,
    run_dir: Path,
    customers_csv: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Derive runtime context paths from project/run directories.

    This is a convenience helper for callers that have project_dir and
    run_dir but need to compute the individual paths for ``build_mcp_server``.

    Returns a dict of kwargs suitable for ``build_mcp_server(**ctx)``.
    """
    dd_dir = project_dir / "_dd" / "forensic-dd"
    text_dir = dd_dir / "index" / "text"
    cache_path = dd_dir / "entity_resolution" / "entity_resolution_cache.json"

    # Build files_list from inventory if available
    files_list: list[str] = []
    inventory_csv = dd_dir / "index" / "master_inventory.csv"
    if inventory_csv.exists():
        import csv

        try:
            with inventory_csv.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fp = row.get("file_path", "")
                    if fp:
                        files_list.append(fp)
        except (OSError, csv.Error):
            logger.warning("Could not read inventory CSV at %s", inventory_csv)

    return {
        "text_dir": text_dir if text_dir.is_dir() else None,
        "files_list": files_list or None,
        "customers_csv": customers_csv,
        "cache_path": cache_path if cache_path.exists() else None,
        "allowed_dir": dd_dir if dd_dir.is_dir() else None,
    }
