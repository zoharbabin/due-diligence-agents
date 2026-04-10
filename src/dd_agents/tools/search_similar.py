"""Semantic search MCP tool for agents (Issue #127).

Provides a ``search_similar`` tool that agents can use to find
semantically similar clauses or findings across the document corpus.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level reference, set during pipeline initialization.
_VECTOR_STORE: Any = None


def set_vector_store(store: Any) -> None:
    """Register the pipeline's VectorStore instance for tool use."""
    global _VECTOR_STORE
    _VECTOR_STORE = store


def search_similar(
    query: str,
    subject: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Search the vector store for documents matching *query*.

    Parameters
    ----------
    query:
        Natural-language search query.
    subject:
        Optional subject_safe_name to filter results.
    top_k:
        Maximum results (capped at 20).

    Returns
    -------
    dict with ``results`` list and ``available`` boolean.
    """
    top_k = min(max(top_k, 1), 20)

    if _VECTOR_STORE is None or not getattr(_VECTOR_STORE, "is_available", False):
        return {"results": [], "available": False}

    try:
        raw_results: list[dict[str, Any]] = _VECTOR_STORE.search(query=query, top_k=top_k)
    except Exception:
        logger.exception("search_similar: vector store query failed")
        return {"results": [], "available": True, "error": "search failed"}

    results: list[dict[str, Any]] = []
    for r in raw_results:
        metadata = r.get("metadata", {})
        if subject and metadata.get("subject_safe_name") != subject:
            continue
        results.append(
            {
                "text": r.get("text", ""),
                "metadata": metadata,
                "score": round(1.0 - r.get("distance", 0.0), 4),
            }
        )

    return {"results": results, "available": True}


def search_similar_tool_schema() -> dict[str, Any]:
    """Return the MCP tool definition for search_similar."""
    return {
        "name": "search_similar",
        "description": (
            "Search for semantically similar clauses or text across the document corpus. "
            "Returns matching text snippets with relevance scores."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query (e.g., 'change of control clause')",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject_safe_name to filter results",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results (1-20, default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "handler": "dd_agents.tools.search_similar.search_similar",
    }
