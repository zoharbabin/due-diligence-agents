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

from datetime import UTC

from dd_agents.tools.server import get_tools_for_agent

logger = logging.getLogger(__name__)


def build_mcp_server(
    agent_type: str = "specialist",
    *,
    text_dir: str | Path | None = None,
    files_list: list[str] | None = None,
    subjects_csv: list[dict[str, Any]] | None = None,
    cache_path: str | Path | None = None,
    allowed_dir: str | Path | None = None,
    data_room_path: str | Path | None = None,
    file_precedence: dict[str, float] | None = None,
    memory_store: Any | None = None,
    session_id: str = "",
) -> Any | None:
    """Build an in-process MCP server with DD tools for the given agent type.

    Parameters
    ----------
    agent_type:
        One of ``"specialist"``, ``"judge"``, or ``"chat"``.  Controls
        which tools are registered on the server.
    text_dir:
        Path to the extracted text directory (``index/text/``).
        Required by ``verify_citation``, ``read_office``, ``search_in_file``,
        ``get_page_content``, and ``get_subject_files`` (extraction status).
    files_list:
        List of known file paths from inventory.
        Required by ``verify_citation`` and ``batch_verify_citations``.
    subjects_csv:
        List of subject dicts from the inventory CSV.
        Required by ``get_subject_files``.
    cache_path:
        Path to ``entity_resolution_cache.json``.
        Required by ``resolve_entity``.
    allowed_dir:
        Base directory for path containment checks (prevents traversal).
        Used by ``verify_citation``, ``read_office``, ``search_in_file``,
        and ``get_page_content``.
    data_room_path:
        Root of the data room (for resolving file sizes in ``get_subject_files``).
    file_precedence:
        Precedence scores keyed by file path (for ``get_subject_files``).

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
                    "subjects_processed": {"type": "integer", "description": "Count of subjects completed so far"},
                    "total_subjects": {"type": "integer", "description": "Total subjects assigned"},
                    "current_subject": {"type": "string", "description": "Subject currently being processed"},
                },
                "required": ["agent_name", "subjects_processed", "total_subjects", "current_subject"],
            },
        )
        async def report_progress_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _report_progress(
                agent_name=input_data["agent_name"],
                subjects_processed=input_data["subjects_processed"],
                total_subjects=input_data["total_subjects"],
                current_subject=input_data["current_subject"],
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
                    "subject": {"type": "string", "description": "Optional subject_safe_name to filter results"},
                    "top_k": {"type": "integer", "description": "Maximum number of results (1-20, default 5)"},
                },
                "required": ["query"],
            },
        )
        async def search_similar_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _search_similar(
                query=input_data["query"],
                subject=input_data.get("subject"),
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

    if "get_subject_files" in allowed_tool_names:
        from dd_agents.tools.get_subject_files import get_subject_files as _get_subject_files

        _gcf_subjects_csv = subjects_csv or []
        _gcf_data_room = str(data_room_path) if data_room_path else None
        _gcf_text_dir = str(text_dir) if text_dir else None
        _gcf_precedence = file_precedence

        @tool(
            "get_subject_files",
            "Return the file list with metadata for a subject. Includes file type, "
            "extraction status, size, and precedence score. Use subject_safe_name (e.g., 'acme_corp').",
            {
                "type": "object",
                "properties": {
                    "subject_safe_name": {
                        "type": "string",
                        "description": "The subject_safe_name from the assignment",
                    }
                },
                "required": ["subject_safe_name"],
            },
        )
        async def get_subject_files_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _get_subject_files(
                subject_safe_name=input_data["subject_safe_name"],
                subjects_csv=_gcf_subjects_csv,
                data_room_path=_gcf_data_room,
                text_dir=_gcf_text_dir,
                file_precedence=_gcf_precedence,
            )

        tools.append(get_subject_files_tool)

    if "resolve_entity" in allowed_tool_names:
        from dd_agents.tools.resolve_entity import resolve_entity as _resolve_entity

        _re_cache_path = str(cache_path) if cache_path else ""

        @tool(
            "resolve_entity",
            "Look up a name in the entity resolution cache to find the canonical subject name. "
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

    # ------------------------------------------------------------------
    # New document analysis tools (search, page extraction, batch verify)
    # ------------------------------------------------------------------

    if "search_in_file" in allowed_tool_names:
        from dd_agents.tools.search_in_file import search_in_file as _search_in_file

        _sif_text_dir = str(text_dir) if text_dir else ""
        _sif_allowed_dir = str(allowed_dir) if allowed_dir else None

        @tool(
            "search_in_file",
            "Search within a document's extracted text for a query string. "
            "Returns matches with page numbers, character offsets, and surrounding context.",
            {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Original file path (e.g., './Above 200K/Acme/MSA.pdf')",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search string to find in the document",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether to match case-sensitively (default: false)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return (1-20, default 20)",
                    },
                },
                "required": ["source_path", "query"],
            },
        )
        async def search_in_file_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _search_in_file(
                source_path=input_data["source_path"],
                query=input_data["query"],
                text_dir=_sif_text_dir,
                case_sensitive=input_data.get("case_sensitive", False),
                max_results=input_data.get("max_results", 20),
                allowed_dir=_sif_allowed_dir,
            )

        tools.append(search_in_file_tool)

    if "get_page_content" in allowed_tool_names:
        from dd_agents.tools.get_page_content import get_page_content as _get_page_content

        _gpc_text_dir = str(text_dir) if text_dir else ""
        _gpc_allowed_dir = str(allowed_dir) if allowed_dir else None

        @tool(
            "get_page_content",
            "Extract specific page ranges from a document's extracted text. "
            "Returns page content using '--- Page N ---' markers.",
            {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Original file path (e.g., './Above 200K/Acme/MSA.pdf')",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "First page to return (1-based, inclusive, default 1)",
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "Last page to return (inclusive). Omit for single page.",
                    },
                },
                "required": ["source_path"],
            },
        )
        async def get_page_content_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _get_page_content(
                source_path=input_data["source_path"],
                text_dir=_gpc_text_dir,
                start_page=input_data.get("start_page", 1),
                end_page=input_data.get("end_page"),
                allowed_dir=_gpc_allowed_dir,
            )

        tools.append(get_page_content_tool)

    if "batch_verify_citations" in allowed_tool_names:
        from dd_agents.tools.batch_verify_citations import batch_verify_citations as _batch_verify

        _bvc_files_list = files_list or []
        _bvc_text_dir = str(text_dir) if text_dir else ""
        _bvc_allowed_dir = str(allowed_dir) if allowed_dir else None

        @tool(
            "batch_verify_citations",
            "Verify multiple citations in a single call. Returns per-citation "
            "results with page numbers and context, plus an overall summary.",
            {
                "type": "object",
                "properties": {
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_path": {"type": "string", "description": "Original file path"},
                                "exact_quote": {"type": "string", "description": "The exact quote to verify"},
                            },
                            "required": ["source_path", "exact_quote"],
                        },
                        "description": "List of citations to verify",
                    }
                },
                "required": ["citations"],
            },
        )
        async def batch_verify_citations_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            return _batch_verify(
                citations=input_data["citations"],
                files_list=_bvc_files_list,
                text_dir=_bvc_text_dir,
                allowed_dir=_bvc_allowed_dir,
            )

        tools.append(batch_verify_citations_tool)

    # ------------------------------------------------------------------
    # Chat memory tools (only for agent_type="chat")
    # ------------------------------------------------------------------

    if "save_memory" in allowed_tool_names and memory_store is not None:
        from dd_agents.chat.memory import ChatMemory, MemoryType, generate_memory_id

        _mem_store = memory_store
        _mem_session_id = session_id

        @tool(
            "save_memory",
            "Save an important insight or conclusion for future chat sessions.",
            {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The insight (1-3 concise sentences)",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Subject names, categories, or keywords",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["insight", "cross_reference", "user_note", "conclusion"],
                        "description": "Classification of the memory",
                    },
                },
                "required": ["content", "topics", "memory_type"],
            },
        )
        async def save_memory_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            from datetime import datetime

            mem = ChatMemory(
                id=generate_memory_id(),
                timestamp=datetime.now(tz=UTC).isoformat(),
                session_id=_mem_session_id,
                content=input_data["content"],
                topics=input_data.get("topics", []),
                memory_type=MemoryType(input_data.get("memory_type", "insight")),
                source_turn=0,
            )
            _mem_store.save_memory(mem)
            return {"status": "saved", "memory_id": mem.id}

        tools.append(save_memory_tool)

    if "search_chat_memory" in allowed_tool_names and memory_store is not None:
        _search_mem_store = memory_store

        @tool(
            "search_chat_memory",
            "Search memories from prior chat sessions about this deal.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        )
        async def search_chat_memory_tool(input_data: dict[str, Any]) -> dict[str, Any]:
            limit = input_data.get("limit", 10)
            results = _search_mem_store.search_memories(input_data["query"], limit=limit)
            return {
                "matches": [
                    {
                        "content": m.content,
                        "topics": m.topics,
                        "memory_type": m.memory_type,
                        "timestamp": m.timestamp,
                        "session_id": m.session_id,
                    }
                    for m in results
                ],
                "total_memories": _search_mem_store.memory_count,
            }

        tools.append(search_chat_memory_tool)

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
    subjects_csv: list[dict[str, Any]] | None = None,
    file_precedence: dict[str, float] | None = None,
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
        "subjects_csv": subjects_csv,
        "cache_path": cache_path if cache_path.exists() else None,
        # Always set allowed_dir to the project dir for path containment.
        # Even if _dd/ doesn't exist yet, agents should not read outside it.
        "allowed_dir": dd_dir if dd_dir.is_dir() else project_dir,
        "data_room_path": project_dir,
        "file_precedence": file_precedence,
    }
