"""MCP tool server setup.

Defines tool definitions for all custom DD tools and configures
tool availability per agent type.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _validate_finding_definition() -> dict[str, Any]:
    """Tool definition for validate_finding."""
    return {
        "name": "validate_finding",
        "description": ("Validate a finding JSON against the schema. Returns 'valid' or error details."),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_json": {
                    "type": "object",
                    "description": "A single finding object to validate",
                }
            },
            "required": ["finding_json"],
        },
        "handler": "dd_agents.tools.validate_finding.validate_finding",
    }


def _validate_gap_definition() -> dict[str, Any]:
    """Tool definition for validate_gap."""
    return {
        "name": "validate_gap",
        "description": ("Validate a gap JSON against the schema. Returns 'valid' or error details."),
        "input_schema": {
            "type": "object",
            "properties": {
                "gap_json": {
                    "type": "object",
                    "description": "A single gap object to validate",
                }
            },
            "required": ["gap_json"],
        },
        "handler": "dd_agents.tools.validate_gap.validate_gap",
    }


def _validate_manifest_definition() -> dict[str, Any]:
    """Tool definition for validate_manifest."""
    return {
        "name": "validate_manifest",
        "description": ("Validate a coverage_manifest.json. Returns 'valid' or error details."),
        "input_schema": {
            "type": "object",
            "properties": {
                "manifest_json": {
                    "type": "object",
                    "description": "The coverage manifest object to validate",
                }
            },
            "required": ["manifest_json"],
        },
        "handler": "dd_agents.tools.validate_manifest.validate_manifest",
    }


def _verify_citation_definition() -> dict[str, Any]:
    """Tool definition for verify_citation."""
    return {
        "name": "verify_citation",
        "description": (
            "Verify that exact_quote exists in the source document's extracted text. Returns verification result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Original file path (e.g., './Above 200K/Acme/MSA.pdf')",
                },
                "exact_quote": {
                    "type": "string",
                    "description": "The exact quote to verify",
                },
            },
            "required": ["source_path", "exact_quote"],
        },
        "handler": "dd_agents.tools.verify_citation.verify_citation",
    }


def _get_customer_files_definition() -> dict[str, Any]:
    """Tool definition for get_customer_files."""
    return {
        "name": "get_customer_files",
        "description": ("Return the file list and count for a customer. Use customer_safe_name (e.g., 'acme_corp')."),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_safe_name": {
                    "type": "string",
                    "description": "The customer_safe_name from the assignment",
                }
            },
            "required": ["customer_safe_name"],
        },
        "handler": "dd_agents.tools.get_customer_files.get_customer_files",
    }


def _resolve_entity_definition() -> dict[str, Any]:
    """Tool definition for resolve_entity."""
    return {
        "name": "resolve_entity",
        "description": (
            "Look up a name in the entity resolution cache to find the "
            "canonical customer name. Returns the canonical name and match "
            "method, or 'unresolved'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The entity name to look up",
                }
            },
            "required": ["name"],
        },
        "handler": "dd_agents.tools.resolve_entity.resolve_entity",
    }


def _search_similar_definition() -> dict[str, Any]:
    """Tool definition for search_similar (Issue #127)."""
    from dd_agents.tools.search_similar import search_similar_tool_schema

    return search_similar_tool_schema()


def _read_office_definition() -> dict[str, Any]:
    """Tool definition for read_office."""
    return {
        "name": "read_office",
        "description": (
            "Read the contents of a binary Office file (.xlsx, .xls, .docx, .doc, "
            ".pptx, .ppt). Returns structured text content. Use this instead of "
            "the Read tool for Office files — the Read tool returns garbled binary "
            "for these formats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Office file to read",
                },
                "sheet_name": {
                    "type": "string",
                    "description": ("For Excel files: specific sheet name to read. Omit to read all sheets."),
                },
            },
            "required": ["file_path"],
        },
        "handler": "dd_agents.tools.read_office.read_office",
    }


def _report_progress_definition() -> dict[str, Any]:
    """Tool definition for report_progress."""
    return {
        "name": "report_progress",
        "description": ("Report progress to the orchestrator. Returns a progress snapshot."),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of the reporting agent",
                },
                "customers_processed": {
                    "type": "integer",
                    "description": "Count of customers completed so far",
                },
                "total_customers": {
                    "type": "integer",
                    "description": "Total customers assigned",
                },
                "current_customer": {
                    "type": "string",
                    "description": "Customer currently being processed",
                },
            },
            "required": [
                "agent_name",
                "customers_processed",
                "total_customers",
                "current_customer",
            ],
        },
        "handler": "dd_agents.tools.report_progress.report_progress",
    }


# ---------------------------------------------------------------------------
# Full tool registry
# ---------------------------------------------------------------------------

_ALL_TOOL_DEFINITIONS: list[dict[str, Any]] | None = None


def create_tool_definitions() -> list[dict[str, Any]]:
    """Return tool definitions for all custom DD tools.

    Each tool definition has:
    - ``name``: tool name
    - ``description``: human-readable description
    - ``input_schema``: JSON Schema for the tool input
    - ``handler``: dotted path to the handler function

    Returns:
        List of tool definition dicts.
    """
    global _ALL_TOOL_DEFINITIONS

    if _ALL_TOOL_DEFINITIONS is None:
        _ALL_TOOL_DEFINITIONS = [
            _validate_finding_definition(),
            _validate_gap_definition(),
            _validate_manifest_definition(),
            _verify_citation_definition(),
            _get_customer_files_definition(),
            _resolve_entity_definition(),
            _search_similar_definition(),
            _read_office_definition(),
            _report_progress_definition(),
        ]

    return list(_ALL_TOOL_DEFINITIONS)


# ---------------------------------------------------------------------------
# Tool availability per agent type
#
# NOTE: These lists contain CUSTOM tools only.  Built-in SDK tools (Read,
# Write, Glob, Grep) are added by each agent class in specialists.py.
# The authoritative tool list per agent is defined in each agent's
# ``get_tools()`` method (see specialists.py, judge.py).
# ---------------------------------------------------------------------------

# Specialists: validation + lookup + progress (custom tools only)
SPECIALIST_CUSTOM_TOOLS: list[str] = [
    "validate_finding",
    "validate_gap",
    "validate_manifest",
    "verify_citation",
    "get_customer_files",
    "resolve_entity",
    "search_similar",
    "read_office",
    "report_progress",
]

# Judge: verification only (custom tools only)
JUDGE_CUSTOM_TOOLS: list[str] = [
    "verify_citation",
]


def get_tools_for_agent(agent_type: str) -> list[str]:
    """Return the list of allowed tool names for the given *agent_type*.

    Args:
        agent_type: One of ``"specialist"``, ``"judge"``.

    Returns:
        List of tool name strings.
    """
    mapping: dict[str, list[str]] = {
        "specialist": SPECIALIST_CUSTOM_TOOLS,
        "judge": JUDGE_CUSTOM_TOOLS,
    }
    return mapping.get(agent_type, [])
