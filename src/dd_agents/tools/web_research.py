"""Web research tool definition (Issue #139).

Provides the tool schema for the optional google-researcher-mcp integration.
The actual web research is performed by the MCP server at runtime; this module
defines the tool interface and returns structured results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def web_research_tool_schema() -> dict[str, Any]:
    """Return the tool definition schema for web research.

    This schema is registered with the Judge agent when
    ``web_research_enabled`` is True in the deal config.
    """
    return {
        "name": "web_research",
        "description": (
            "Search the web to verify claims from the data room against public information. "
            "Use for: verifying company certifications (SOC 2, ISO 27001), checking regulatory "
            "filings, validating market data, and confirming company facts. "
            "Results have source_type='web_research' and confidence='low' unless "
            "corroborated by data room documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to verify a specific claim or fact.",
                },
                "context": {
                    "type": "string",
                    "description": "Context from the data room claim being verified.",
                },
            },
            "required": ["query"],
        },
    }


def format_web_research_result(
    query: str,
    url: str = "",
    snippet: str = "",
    verified: bool = False,
) -> dict[str, Any]:
    """Format a web research result with proper metadata.

    All web research results have ``source_type='web_research'`` and
    ``confidence='low'`` unless independently verified against data room docs.
    """
    return {
        "source_type": "web_research",
        "query": query,
        "url": url,
        "snippet": snippet,
        "access_date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "confidence": "medium" if verified else "low",
        "verified_against_data_room": verified,
    }
