"""Natural language query interface for DD reports (Issue #124).

Allows users to ask questions about the analyzed findings,
returning natural-language answers with supporting evidence.
"""

from __future__ import annotations

from dd_agents.query.engine import QueryEngine
from dd_agents.query.indexer import FindingIndex, FindingIndexer

__all__ = [
    "FindingIndex",
    "FindingIndexer",
    "QueryEngine",
]
