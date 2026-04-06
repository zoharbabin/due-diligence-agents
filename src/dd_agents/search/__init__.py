"""Search sub-package: targeted clause search with custom prompts.

Provides a multi-phase search engine that analyzes contract documents
against user-defined prompts and produces Excel reports with citations.
"""

from __future__ import annotations

from dd_agents.search.analyzer import SearchAnalyzer
from dd_agents.search.chunker import (
    AnalysisChunk,
    create_analysis_chunks,
    detect_page_markers,
    is_tabular,
    split_by_table_rows,
)
from dd_agents.search.runner import SearchRunner

__all__ = [
    "AnalysisChunk",
    "SearchAnalyzer",
    "SearchRunner",
    "create_analysis_chunks",
    "detect_page_markers",
    "is_tabular",
    "split_by_table_rows",
]
