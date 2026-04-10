"""Contract knowledge graph for ontology-based reasoning (Issue #152).

Builds a NetworkX directed graph from extracted contract clauses,
document relationships, and obligations. Supports queries like:
- "What happens if Company X triggers a change of control?"
- "Which contracts have conflicting governing law?"
- "What's the total liability cap across Customer Y's contracts?"

Spec: docs/plan/21-ontology-and-reasoning.md §2-4
"""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx  # type: ignore[import-untyped]

from dd_agents.models.ontology import (
    ClauseNode,
    ClauseType,
    DocumentRelationship,
    Obligation,
    OntologyGraph,
    RelationshipType,
)

logger = logging.getLogger(__name__)


class ContractKnowledgeGraph:
    """NetworkX-based contract knowledge graph."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph[str] = nx.DiGraph()
        self._clauses: dict[str, ClauseNode] = {}
        self._obligations: dict[str, Obligation] = {}

    @property
    def total_nodes(self) -> int:
        return int(self.graph.number_of_nodes())

    @property
    def total_edges(self) -> int:
        return int(self.graph.number_of_edges())

    def add_clause(self, clause: ClauseNode) -> None:
        """Add a clause node to the graph."""
        self._clauses[clause.id] = clause
        self.graph.add_node(
            clause.id,
            node_type="clause",
            clause_type=clause.clause_type.value,
            document_path=clause.document_path,
            subject=clause.subject_safe_name,
            summary=clause.summary,
            effective_date=clause.effective_date,
            expiry_date=clause.expiry_date,
        )

    def add_relationship(self, rel: DocumentRelationship) -> None:
        """Add a relationship edge between two nodes."""
        # Ensure both nodes exist
        for node_id in (rel.source_id, rel.target_id):
            if node_id not in self.graph:
                self.graph.add_node(node_id, node_type="document")

        self.graph.add_edge(
            rel.source_id,
            rel.target_id,
            relationship=rel.relationship.value,
            description=rel.description,
            confidence=rel.confidence,
        )

    def add_obligation(self, obligation: Obligation) -> None:
        """Track a contractual obligation."""
        self._obligations[obligation.id] = obligation
        self.graph.add_node(
            obligation.id,
            node_type="obligation",
            obligor=obligation.obligor,
            obligee=obligation.obligee,
            description=obligation.description,
            status=obligation.status,
        )
        # Link obligation to its source clause
        if obligation.clause_id in self.graph:
            self.graph.add_edge(
                obligation.clause_id,
                obligation.id,
                relationship="creates_obligation",
            )

    def get_clauses_by_type(self, clause_type: ClauseType) -> list[ClauseNode]:
        """Find all clauses of a given type."""
        return [c for c in self._clauses.values() if c.clause_type == clause_type]

    def get_clauses_by_subject(self, subject_safe_name: str) -> list[ClauseNode]:
        """Find all clauses for a specific subject."""
        return [c for c in self._clauses.values() if c.subject_safe_name == subject_safe_name]

    def get_affected_documents(self, document_id: str) -> list[str]:
        """Find all documents affected by changes to a given document.

        Follows amends/supersedes/parent_of edges transitively.
        """
        if document_id not in self.graph:
            return []

        affected: set[str] = set()
        propagating_rels = {
            RelationshipType.AMENDS.value,
            RelationshipType.SUPERSEDES.value,
            RelationshipType.PARENT_OF.value,
            RelationshipType.CONDITIONS.value,
        }

        # BFS through propagating relationships
        queue = [document_id]
        visited: set[str] = {document_id}
        while queue:
            current = queue.pop(0)
            for _, target, data in self.graph.out_edges(current, data=True):
                if data.get("relationship") in propagating_rels and target not in visited:
                    visited.add(target)
                    affected.add(target)
                    queue.append(target)

        return sorted(affected)

    def find_conflicts(self) -> list[dict[str, Any]]:
        """Find conflicting clauses (e.g., different governing law)."""
        conflicts: list[dict[str, Any]] = []

        # Check explicit conflict edges
        for source, target, data in self.graph.edges(data=True):
            if data.get("relationship") == RelationshipType.CONFLICTS_WITH.value:
                conflicts.append(
                    {
                        "source": source,
                        "target": target,
                        "description": data.get("description", "Conflicting provisions"),
                    }
                )

        # Check governing law conflicts within same subject
        gov_law_clauses = self.get_clauses_by_type(ClauseType.GOVERNING_LAW)
        by_subject: dict[str, list[ClauseNode]] = {}
        for c in gov_law_clauses:
            by_subject.setdefault(c.subject_safe_name, []).append(c)

        for subj, clauses in by_subject.items():
            if len(clauses) > 1:
                summaries = {c.summary.lower().strip() for c in clauses if c.summary}
                if len(summaries) > 1:
                    conflicts.append(
                        {
                            "subject": subj,
                            "type": "governing_law_conflict",
                            "clauses": [c.id for c in clauses],
                            "description": f"Multiple governing law provisions: {', '.join(summaries)}",
                        }
                    )

        return conflicts

    def get_obligation_chain(self, subject_safe_name: str) -> list[Obligation]:
        """Get all obligations for a subject, ordered by due date."""
        obligations = [o for o in self._obligations.values() if o.subject_safe_name == subject_safe_name]
        return sorted(obligations, key=lambda o: o.due_date or "9999")

    def get_amendment_chain(self, document_id: str) -> list[str]:
        """Get the chain of amendments for a document (oldest first)."""
        chain: list[str] = []
        current = document_id

        # Walk backwards through amends edges
        visited: set[str] = {current}
        while True:
            predecessors = [
                src
                for src, _, data in self.graph.in_edges(current, data=True)
                if data.get("relationship") == RelationshipType.AMENDS.value and src not in visited
            ]
            if not predecessors:
                break
            current = predecessors[0]
            visited.add(current)
            chain.insert(0, current)

        chain.append(document_id)

        # Walk forward
        current = document_id
        visited = {current}
        while True:
            successors = [
                tgt
                for _, tgt, data in self.graph.out_edges(current, data=True)
                if data.get("relationship") == RelationshipType.AMENDS.value and tgt not in visited
            ]
            if not successors:
                break
            current = successors[0]
            visited.add(current)
            chain.append(current)

        return chain

    def coc_impact_analysis(self) -> list[dict[str, Any]]:
        """Analyze change-of-control clause impacts across the portfolio."""
        coc_clauses = self.get_clauses_by_type(ClauseType.CHANGE_OF_CONTROL)
        impacts: list[dict[str, Any]] = []

        for clause in coc_clauses:
            affected = self.get_affected_documents(clause.id)
            impacts.append(
                {
                    "clause_id": clause.id,
                    "subject": clause.subject_safe_name,
                    "document": clause.document_path,
                    "summary": clause.summary,
                    "notice_period_days": clause.notice_period_days,
                    "affected_documents": affected,
                    "affected_count": len(affected),
                }
            )

        return sorted(impacts, key=lambda x: x["affected_count"], reverse=True)

    def to_serializable(self) -> OntologyGraph:
        """Export the graph as a serializable model."""
        relationships: list[DocumentRelationship] = []
        for source, target, data in self.graph.edges(data=True):
            rel_str = data.get("relationship", "references")
            try:
                rel_type = RelationshipType(rel_str)
            except ValueError:
                continue
            relationships.append(
                DocumentRelationship(
                    source_id=source,
                    target_id=target,
                    relationship=rel_type,
                    description=data.get("description", ""),
                    confidence=data.get("confidence", 1.0),
                )
            )

        return OntologyGraph(
            clauses=list(self._clauses.values()),
            relationships=relationships,
            obligations=list(self._obligations.values()),
            total_documents=sum(1 for _, d in self.graph.nodes(data=True) if d.get("node_type") == "document"),
            total_clauses=len(self._clauses),
            total_relationships=len(relationships),
        )

    @classmethod
    def from_findings(cls, merged_data: dict[str, Any]) -> ContractKnowledgeGraph:
        """Build a knowledge graph from merged DD findings.

        Extracts clause information from findings and cross-references
        to build the initial graph. This provides a foundation that
        can be enriched with deeper ontology extraction.
        """
        graph = cls()

        for subject_key, subject_data in merged_data.items():
            if not isinstance(subject_data, dict):
                continue

            findings = subject_data.get("findings", [])
            for finding in findings:
                category = str(finding.get("category", "")).lower()
                title = str(finding.get("title", ""))

                # Map finding categories to clause types
                clause_type = _category_to_clause_type(category)
                if clause_type == ClauseType.UNKNOWN:
                    continue

                # Extract clause from citations
                citations = finding.get("citations", [])
                for citation in citations:
                    source_path = citation.get("source_path", citation.get("file_path", ""))
                    exact_quote = citation.get("exact_quote", "")
                    section_ref = citation.get("section_ref", "")

                    clause_id = f"{subject_key}:{source_path}:{clause_type.value}:{hash(title) & 0xFFFF:04x}"
                    clause = ClauseNode(
                        id=clause_id,
                        document_path=source_path,
                        subject_safe_name=subject_key,
                        clause_type=clause_type,
                        section_ref=section_ref,
                        summary=title,
                        exact_quote=exact_quote[:500],
                    )
                    graph.add_clause(clause)

            # Build relationships from governance graph if available
            gov_graph = subject_data.get("governance_graph", {})
            for edge in gov_graph.get("edges", []):
                source = edge.get("source", "")
                target = edge.get("target", "")
                rel_type_str = edge.get("type", "references")
                try:
                    rel_type = RelationshipType(rel_type_str)
                except ValueError:
                    rel_type = RelationshipType.REFERENCES

                graph.add_relationship(
                    DocumentRelationship(
                        source_id=f"{subject_key}:{source}",
                        target_id=f"{subject_key}:{target}",
                        relationship=rel_type,
                    )
                )

        return graph


def _category_to_clause_type(category: str) -> ClauseType:
    """Map a finding category to a clause type."""
    mapping: dict[str, ClauseType] = {
        "change_of_control": ClauseType.CHANGE_OF_CONTROL,
        "termination": ClauseType.TERMINATION,
        "termination_for_convenience": ClauseType.TERMINATION,
        "indemnification": ClauseType.INDEMNIFICATION,
        "liability": ClauseType.LIMITATION,
        "liability_cap": ClauseType.LIMITATION,
        "ip_ownership": ClauseType.IP_ASSIGNMENT,
        "ip_assignment": ClauseType.IP_ASSIGNMENT,
        "governing_law": ClauseType.GOVERNING_LAW,
        "confidentiality": ClauseType.CONFIDENTIALITY,
        "data_privacy": ClauseType.CONFIDENTIALITY,
        "warranty": ClauseType.WARRANTY,
        "force_majeure": ClauseType.FORCE_MAJEURE,
        "obligation": ClauseType.OBLIGATION,
        "right": ClauseType.RIGHT,
    }
    for key, ctype in mapping.items():
        if key in category:
            return ctype
    return ClauseType.UNKNOWN
