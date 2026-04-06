"""Deal Knowledge Base — persistent cross-run knowledge layer (Issue #178).

Implements the knowledge compounding architecture inspired by the LLM Wiki
pattern. Every pipeline run, search, and query enriches a persistent knowledge
base that sits between raw extracted text and per-run findings.

Public API
----------
- :class:`DealKnowledgeBase` — CRUD operations on the knowledge store.
- :class:`KnowledgeArticle` — Pydantic model for a single knowledge article.
- :class:`DealKnowledgeGraph` — Unified cross-document relationship graph.
- :class:`AnalysisChronicle` — Append-only interaction timeline.
- :class:`FindingLineageTracker` — Cross-run finding evolution tracking.
- :class:`KnowledgeHealthChecker` — Automated integrity validation.

Storage: ``_dd/forensic-dd/knowledge/`` (PERMANENT tier).
"""

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle, KnowledgeSource
from dd_agents.knowledge.base import DealKnowledgeBase
from dd_agents.knowledge.chronicle import AnalysisChronicle, AnalysisLogEntry, FindingsSummary, InteractionType
from dd_agents.knowledge.compiler import CompilationResult, KnowledgeCompiler
from dd_agents.knowledge.filing import file_annotation, file_query_result, file_search_results
from dd_agents.knowledge.graph import DealKnowledgeGraph, EdgeType, GraphEdge, NodeType
from dd_agents.knowledge.health import HealthCheckCategory, HealthCheckResult, HealthIssue, KnowledgeHealthChecker
from dd_agents.knowledge.index import IndexEntry, KnowledgeIndex
from dd_agents.knowledge.lineage import (
    FindingLineage,
    FindingLineageTracker,
    FindingStatus,
    LineageUpdateResult,
    SeverityEvent,
    compute_finding_fingerprint,
)
from dd_agents.knowledge.prompt_enrichment import AgentKnowledgeEnricher
from dd_agents.knowledge.search_context import KnowledgeContextBuilder

__all__ = [
    "AgentKnowledgeEnricher",
    "AnalysisChronicle",
    "AnalysisLogEntry",
    "ArticleType",
    "CompilationResult",
    "DealKnowledgeBase",
    "DealKnowledgeGraph",
    "EdgeType",
    "FindingLineage",
    "FindingLineageTracker",
    "FindingStatus",
    "FindingsSummary",
    "GraphEdge",
    "HealthCheckCategory",
    "HealthCheckResult",
    "HealthIssue",
    "IndexEntry",
    "InteractionType",
    "KnowledgeArticle",
    "KnowledgeCompiler",
    "KnowledgeContextBuilder",
    "KnowledgeHealthChecker",
    "KnowledgeIndex",
    "KnowledgeSource",
    "LineageUpdateResult",
    "NodeType",
    "SeverityEvent",
    "compute_finding_fingerprint",
    "file_annotation",
    "file_query_result",
    "file_search_results",
]
