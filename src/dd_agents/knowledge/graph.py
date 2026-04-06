"""Unified Deal Knowledge Graph — cross-document relationship graph (Issue #179).

Wraps a NetworkX DiGraph with typed nodes and edges to represent relationships
between entities, documents, clauses, findings, gaps, articles, and obligations.
Supports governance graph merging, amendment chain detection, cycle detection,
contradiction detection, and LLM-readable context generation.

Persistence uses JSON serialization — NEVER pickle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import networkx as nx  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from dd_agents.knowledge._utils import now_iso

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class NodeType(StrEnum):
    """Types of nodes in the deal knowledge graph."""

    ENTITY = "entity"
    DOCUMENT = "document"
    CLAUSE = "clause"
    FINDING = "finding"
    GAP = "gap"
    ARTICLE = "article"
    OBLIGATION = "obligation"


class EdgeType(StrEnum):
    """Types of directed edges in the deal knowledge graph."""

    GOVERNS = "governs"
    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"
    INCORPORATES = "incorporates"
    CONFLICTS_WITH = "conflicts_with"
    PARTY_TO = "party_to"
    ANALYZED_IN = "analyzed_in"
    FOUND_IN = "found_in"
    AFFECTS = "affects"
    CONTRADICTS = "contradicts"
    CORROBORATES = "corroborates"
    DERIVED_FROM = "derived_from"
    RELATED_TO = "related_to"
    CONTAINS = "contains"
    OVERRIDES = "overrides"


class GraphEdge(BaseModel):
    """A typed, directed edge in the knowledge graph."""

    source_id: str = Field(description="Source node ID (e.g. 'entity:acme')")
    target_id: str = Field(description="Target node ID (e.g. 'doc:abc123')")
    edge_type: EdgeType = Field(description="Relationship type")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0-1")
    created_by: str = Field(default="", description="Origin of this edge (e.g. 'pipeline:run_001')")
    created_at: str = Field(default="", description="ISO-8601 creation timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extensible metadata")


def _doc_node_id(file_path: str) -> str:
    """Deterministic document node ID from file path."""
    h = hashlib.sha256(file_path.encode()).hexdigest()[:12]
    return f"doc:{h}"


class DealKnowledgeGraph:
    """Unified cross-document relationship graph for a deal.

    Wraps ``networkx.DiGraph`` with typed nodes and edges. Supports
    governance graph merging, amendment chain detection, and LLM-readable
    context generation.

    Node IDs are prefixed by type: ``entity:foo``, ``doc:abc123``,
    ``finding:xyz``, ``article:art_001``.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph[str] = nx.DiGraph()
        # Reverse lookup: file_path -> node_id for documents
        self._doc_path_to_id: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_entity(self, safe_name: str, display_name: str, **meta: Any) -> str:
        """Add an entity node. Returns node ID ``entity:{safe_name}``.

        Parameters
        ----------
        safe_name:
            The entity's customer_safe_name.
        display_name:
            Human-readable entity name.
        **meta:
            Additional metadata stored on the node.
        """
        node_id = f"entity:{safe_name}"
        self._graph.add_node(
            node_id,
            node_type=NodeType.ENTITY,
            safe_name=safe_name,
            display_name=display_name,
            **meta,
        )
        return node_id

    def add_document(self, file_path: str, doc_type_str: str, **meta: Any) -> str:
        """Add a document node. Returns node ID ``doc:{hash}``.

        Parameters
        ----------
        file_path:
            Relative path to the document in the data room.
        doc_type_str:
            Document type (e.g. 'contract', 'amendment', 'financial').
        **meta:
            Additional metadata stored on the node.
        """
        node_id = _doc_node_id(file_path)
        self._graph.add_node(
            node_id,
            node_type=NodeType.DOCUMENT,
            file_path=file_path,
            doc_type=doc_type_str,
            **meta,
        )
        self._doc_path_to_id[file_path] = node_id
        return node_id

    def add_finding(self, finding_id: str, severity: str, **meta: Any) -> str:
        """Add a finding node. Returns node ID ``finding:{finding_id}``.

        Parameters
        ----------
        finding_id:
            Unique finding identifier.
        severity:
            Severity level (e.g. 'P0', 'P1', 'P2', 'P3').
        **meta:
            Additional metadata stored on the node.
        """
        node_id = f"finding:{finding_id}"
        self._graph.add_node(
            node_id,
            node_type=NodeType.FINDING,
            finding_id=finding_id,
            severity=severity,
            **meta,
        )
        return node_id

    def add_article(self, article_id: str, article_type_str: str, **meta: Any) -> str:
        """Add a knowledge article node. Returns node ID ``article:{article_id}``.

        Parameters
        ----------
        article_id:
            Knowledge article identifier.
        article_type_str:
            Article type (e.g. 'entity_profile', 'clause_summary').
        **meta:
            Additional metadata stored on the node.
        """
        node_id = f"article:{article_id}"
        self._graph.add_node(
            node_id,
            node_type=NodeType.ARTICLE,
            article_id=article_id,
            article_type=article_type_str,
            **meta,
        )
        return node_id

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> None:
        """Add a typed, directed edge between two nodes.

        Creates missing nodes as needed (with minimal attributes).

        Parameters
        ----------
        edge:
            The GraphEdge to add.
        """
        # Ensure both nodes exist
        if not self._graph.has_node(edge.source_id):
            self._graph.add_node(edge.source_id, node_type=edge.source_id.split(":")[0])
        if not self._graph.has_node(edge.target_id):
            self._graph.add_node(edge.target_id, node_type=edge.target_id.split(":")[0])

        self._graph.add_edge(
            edge.source_id,
            edge.target_id,
            edge_type=edge.edge_type,
            confidence=edge.confidence,
            created_by=edge.created_by,
            created_at=edge.created_at,
            metadata=edge.metadata,
        )

    def get_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[GraphEdge]:
        """Get all outgoing edges from a node.

        Parameters
        ----------
        node_id:
            The source node ID.
        edge_type:
            Optional filter by edge type.

        Returns
        -------
        list[GraphEdge]
            All matching outgoing edges.
        """
        if not self._graph.has_node(node_id):
            return []

        edges: list[GraphEdge] = []
        for _src, tgt, data in self._graph.out_edges(node_id, data=True):
            if edge_type is not None and data.get("edge_type") != edge_type:
                continue
            edges.append(
                GraphEdge(
                    source_id=node_id,
                    target_id=tgt,
                    edge_type=data.get("edge_type", EdgeType.RELATED_TO),
                    confidence=data.get("confidence", 1.0),
                    created_by=data.get("created_by", ""),
                    created_at=data.get("created_at", ""),
                    metadata=data.get("metadata", {}),
                )
            )
        return edges

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_entity_documents(self, entity_safe_name: str) -> list[str]:
        """Get all document node IDs connected to an entity via ``party_to``.

        Parameters
        ----------
        entity_safe_name:
            The entity's safe_name.

        Returns
        -------
        list[str]
            Document node IDs.
        """
        entity_id = f"entity:{entity_safe_name}"
        if not self._graph.has_node(entity_id):
            return []

        doc_ids: list[str] = []
        # Check outgoing edges from entity
        for _src, tgt, data in self._graph.out_edges(entity_id, data=True):
            if data.get("edge_type") == EdgeType.PARTY_TO:
                doc_ids.append(tgt)
        # Check incoming edges to entity (document -> entity via party_to)
        for src, _tgt, data in self._graph.in_edges(entity_id, data=True):
            if data.get("edge_type") == EdgeType.PARTY_TO:
                doc_ids.append(src)
        return doc_ids

    def get_document_findings(self, file_path: str) -> list[str]:
        """Get all finding node IDs connected to a document via ``found_in``.

        Parameters
        ----------
        file_path:
            The document's file path.

        Returns
        -------
        list[str]
            Finding node IDs.
        """
        doc_id = self._doc_path_to_id.get(file_path)
        if doc_id is None:
            return []

        finding_ids: list[str] = []
        # Findings point to documents via found_in
        for src, _tgt, data in self._graph.in_edges(doc_id, data=True):
            if data.get("edge_type") == EdgeType.FOUND_IN:
                finding_ids.append(src)
        return finding_ids

    def get_amendment_chain(self, doc_path: str) -> list[str]:
        """Get topologically sorted amendment chain for a document.

        Follows ``amends`` and ``supersedes`` edges to build a subgraph,
        then returns a topological sort of connected nodes.

        Parameters
        ----------
        doc_path:
            The document's file path.

        Returns
        -------
        list[str]
            Topologically sorted list of document node IDs in the chain.
        """
        doc_id = self._doc_path_to_id.get(doc_path)
        if doc_id is None:
            return []

        # BFS to collect all connected nodes via amends/supersedes
        amendment_types = {EdgeType.AMENDS, EdgeType.SUPERSEDES}
        visited: set[str] = set()
        queue: list[str] = [doc_id]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Follow outgoing amends/supersedes edges
            for _src, tgt, data in self._graph.out_edges(current, data=True):
                if data.get("edge_type") in amendment_types and tgt not in visited:
                    queue.append(tgt)
            # Follow incoming amends/supersedes edges
            for src, _tgt, data in self._graph.in_edges(current, data=True):
                if data.get("edge_type") in amendment_types and src not in visited:
                    queue.append(src)

        if not visited:
            return []

        # Build subgraph and topological sort
        subgraph: nx.DiGraph[str] = nx.DiGraph(self._graph.subgraph(visited))
        # Filter to only amends/supersedes edges
        edges_to_remove = [(u, v) for u, v, d in subgraph.edges(data=True) if d.get("edge_type") not in amendment_types]
        subgraph.remove_edges_from(edges_to_remove)

        try:
            return list(nx.topological_sort(subgraph))
        except nx.NetworkXUnfeasible:
            # Cycle detected — return unsorted
            return sorted(visited)

    # ------------------------------------------------------------------
    # Analysis operations
    # ------------------------------------------------------------------

    def detect_cycles(self) -> list[list[str]]:
        """Detect all cycles in the graph.

        Returns
        -------
        list[list[str]]
            Each inner list is a cycle (list of node IDs).
        """
        return [list(c) for c in nx.simple_cycles(self._graph)]

    def detect_contradictions(self) -> list[tuple[str, str, str]]:
        """Detect contradictions via ``conflicts_with`` edges.

        Returns
        -------
        list[tuple[str, str, str]]
            Each tuple is (node_a, node_b, reason) from the edge metadata.
        """
        contradictions: list[tuple[str, str, str]] = []
        for src, tgt, data in self._graph.edges(data=True):
            if data.get("edge_type") == EdgeType.CONFLICTS_WITH:
                reason = data.get("metadata", {}).get("reason", "conflicts_with edge")
                contradictions.append((src, tgt, reason))
        return contradictions

    # ------------------------------------------------------------------
    # Governance graph integration
    # ------------------------------------------------------------------

    def merge_governance_graph(self, gov_graph_data: dict[str, Any], run_id: str) -> int:
        """Merge a governance graph (from pipeline output) into the knowledge graph.

        Parameters
        ----------
        gov_graph_data:
            Dict with ``"edges"`` list. Each edge has ``from_file``,
            ``to_file``, ``relationship``, and optionally ``citation``.
        run_id:
            Pipeline run identifier for provenance.

        Returns
        -------
        int
            Number of edges added.
        """
        edges_added = 0
        now = now_iso()
        created_by = f"governance:{run_id}"

        raw_edges = gov_graph_data.get("edges", [])
        if not isinstance(raw_edges, list):
            return 0

        # Map governance relationship strings to EdgeType
        rel_map: dict[str, EdgeType] = {
            "governs": EdgeType.GOVERNS,
            "amends": EdgeType.AMENDS,
            "supersedes": EdgeType.SUPERSEDES,
            "references": EdgeType.REFERENCES,
            "incorporates": EdgeType.INCORPORATES,
        }

        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                continue

            from_file = raw_edge.get("from_file", "")
            to_file = raw_edge.get("to_file", "")
            if not from_file or not to_file:
                continue

            relationship = raw_edge.get("relationship", "references")
            edge_type = rel_map.get(relationship, EdgeType.RELATED_TO)

            # Ensure document nodes exist
            if from_file not in self._doc_path_to_id:
                self.add_document(from_file, "unknown")
            if to_file not in self._doc_path_to_id:
                self.add_document(to_file, "unknown")

            from_id = self._doc_path_to_id[from_file]
            to_id = self._doc_path_to_id[to_file]

            # Build citation metadata
            citation = raw_edge.get("citation", {})
            meta: dict[str, Any] = {}
            if isinstance(citation, dict):
                meta["citation"] = citation

            edge = GraphEdge(
                source_id=from_id,
                target_id=to_id,
                edge_type=edge_type,
                confidence=1.0,
                created_by=created_by,
                created_at=now,
                metadata=meta,
            )
            self.add_edge(edge)
            edges_added += 1

        return edges_added

    # ------------------------------------------------------------------
    # LLM context generation
    # ------------------------------------------------------------------

    def get_entity_context(self, entity: str, max_chars: int = 5000) -> str:
        """Generate LLM-readable context for an entity.

        Parameters
        ----------
        entity:
            Entity safe_name.
        max_chars:
            Maximum character budget.

        Returns
        -------
        str
            Formatted context string.
        """
        entity_id = f"entity:{entity}"
        if not self._graph.has_node(entity_id):
            return f"No graph data for entity: {entity}"

        node_data = self._graph.nodes[entity_id]
        display = node_data.get("display_name", entity)

        lines: list[str] = [
            f"Entity: {display} ({entity})",
            "",
        ]

        # Outgoing edges
        out_edges = list(self._graph.out_edges(entity_id, data=True))
        if out_edges:
            lines.append("Relationships (outgoing):")
            for _src, tgt, data in out_edges:
                et = data.get("edge_type", "related_to")
                conf = data.get("confidence", 1.0)
                tgt_label = self._node_label(tgt)
                lines.append(f"  -> {et}: {tgt_label} (confidence: {conf:.2f})")

        # Incoming edges
        in_edges = list(self._graph.in_edges(entity_id, data=True))
        if in_edges:
            lines.append("Relationships (incoming):")
            for src, _tgt, data in in_edges:
                et = data.get("edge_type", "related_to")
                conf = data.get("confidence", 1.0)
                src_label = self._node_label(src)
                lines.append(f"  <- {et}: {src_label} (confidence: {conf:.2f})")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    def get_document_context(self, file_path: str, max_chars: int = 3000) -> str:
        """Generate LLM-readable context for a document.

        Parameters
        ----------
        file_path:
            Document file path.
        max_chars:
            Maximum character budget.

        Returns
        -------
        str
            Formatted context string.
        """
        doc_id = self._doc_path_to_id.get(file_path)
        if doc_id is None:
            return f"No graph data for document: {file_path}"

        node_data = self._graph.nodes[doc_id]
        doc_type = node_data.get("doc_type", "unknown")

        lines: list[str] = [
            f"Document: {file_path}",
            f"Type: {doc_type}",
            "",
        ]

        # Outgoing edges
        out_edges = list(self._graph.out_edges(doc_id, data=True))
        if out_edges:
            lines.append("Relationships (outgoing):")
            for _src, tgt, data in out_edges:
                et = data.get("edge_type", "related_to")
                tgt_label = self._node_label(tgt)
                lines.append(f"  -> {et}: {tgt_label}")

        # Incoming edges
        in_edges = list(self._graph.in_edges(doc_id, data=True))
        if in_edges:
            lines.append("Relationships (incoming):")
            for src, _tgt, data in in_edges:
                et = data.get("edge_type", "related_to")
                src_label = self._node_label(src)
                lines.append(f"  <- {et}: {src_label}")

        # Findings
        findings = self.get_document_findings(file_path)
        if findings:
            lines.append(f"Findings ({len(findings)}):")
            for fid in findings:
                fdata = self._graph.nodes.get(fid, {})
                sev = fdata.get("severity", "?")
                lines.append(f"  - {fid} (severity: {sev})")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    def _node_label(self, node_id: str) -> str:
        """Build a human-readable label for a node."""
        data = self._graph.nodes.get(node_id, {})
        nt = data.get("node_type", "")

        if nt == NodeType.ENTITY:
            return str(data.get("display_name", node_id))
        if nt == NodeType.DOCUMENT:
            return str(data.get("file_path", node_id))
        if nt == NodeType.FINDING:
            sev = data.get("severity", "?")
            return f"{node_id} ({sev})"
        if nt == NodeType.ARTICLE:
            return str(data.get("article_id", node_id))
        return node_id

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Serialize the graph to JSON atomically (temp + os.replace).

        Parameters
        ----------
        path:
            File path to write the JSON to.
        """
        from pathlib import Path as _Path

        p = _Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_serializable()
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(p))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path) -> DealKnowledgeGraph:
        """Deserialize the graph from JSON.

        Parameters
        ----------
        path:
            File path to read the JSON from.

        Returns
        -------
        DealKnowledgeGraph
            Reconstructed graph.
        """
        from pathlib import Path as _Path

        p = _Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        graph = cls()

        # Restore nodes
        for node in data.get("nodes", []):
            node_id = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            graph._graph.add_node(node_id, **attrs)
            # Rebuild doc path lookup
            if attrs.get("node_type") == NodeType.DOCUMENT:
                fp = attrs.get("file_path", "")
                if fp:
                    graph._doc_path_to_id[fp] = node_id

        # Restore edges
        for edge_data in data.get("edges", []):
            edge = GraphEdge.model_validate(edge_data)
            graph._graph.add_edge(
                edge.source_id,
                edge.target_id,
                edge_type=edge.edge_type,
                confidence=edge.confidence,
                created_by=edge.created_by,
                created_at=edge.created_at,
                metadata=edge.metadata,
            )

        return graph

    def to_serializable(self) -> dict[str, Any]:
        """Convert the graph to a JSON-serializable dict.

        Returns
        -------
        dict[str, Any]
            Dict with ``"nodes"`` and ``"edges"`` lists.
        """
        nodes: list[dict[str, Any]] = []
        for node_id, data in self._graph.nodes(data=True):
            node_dict: dict[str, Any] = {"id": node_id}
            node_dict.update(data)
            # Convert StrEnum values to plain strings for JSON
            if "node_type" in node_dict:
                node_dict["node_type"] = str(node_dict["node_type"])
            nodes.append(node_dict)

        edges: list[dict[str, Any]] = []
        for src, tgt, data in self._graph.edges(data=True):
            edge = GraphEdge(
                source_id=src,
                target_id=tgt,
                edge_type=data.get("edge_type", EdgeType.RELATED_TO),
                confidence=data.get("confidence", 1.0),
                created_by=data.get("created_by", ""),
                created_at=data.get("created_at", ""),
                metadata=data.get("metadata", {}),
            )
            edges.append(edge.model_dump(mode="json"))

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Aggregate statistics about the graph.

        Returns
        -------
        dict[str, Any]
            Node and edge counts grouped by type.
        """
        node_counts: dict[str, int] = {}
        for _nid, data in self._graph.nodes(data=True):
            nt = str(data.get("node_type", "unknown"))
            node_counts[nt] = node_counts.get(nt, 0) + 1

        edge_counts: dict[str, int] = {}
        for _src, _tgt, data in self._graph.edges(data=True):
            et = str(data.get("edge_type", "unknown"))
            edge_counts[et] = edge_counts.get(et, 0) + 1

        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "nodes_by_type": node_counts,
            "edges_by_type": edge_counts,
        }
