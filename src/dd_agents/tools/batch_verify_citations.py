"""batch_verify_citations MCP tool.

Verifies multiple citations in a single call, reducing round-trips for
agents that need to validate many findings at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.tools.verify_citation import verify_citation


def batch_verify_citations(
    citations: list[dict[str, Any]],
    files_list: list[str],
    text_dir: str | Path,
    allowed_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Verify multiple citations in a single call.

    Args:
        citations: List of dicts, each with ``source_path`` and ``exact_quote``.
        files_list: List of known file paths from inventory.
        text_dir: Path to directory containing extracted text files.
        allowed_dir: If set, restrict reads to this directory tree.

    Returns:
        ``{"results": [...], "summary": {"verified": N, "failed": N, "total": N}}``.
    """
    results: list[dict[str, Any]] = []
    verified_count = 0
    failed_count = 0

    for citation in citations:
        result = verify_citation(
            citation=citation,
            files_list=files_list,
            text_dir=text_dir,
            allowed_dir=allowed_dir,
        )
        results.append(result)
        if result.get("found"):
            verified_count += 1
        else:
            failed_count += 1

    return {
        "results": results,
        "summary": {
            "verified": verified_count,
            "failed": failed_count,
            "total": len(citations),
        },
    }
