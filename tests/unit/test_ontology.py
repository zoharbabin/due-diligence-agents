"""Tests for Ontology-Based Reasoning (Issue #152)."""

from __future__ import annotations

from typing import Any

import pytest

from dd_agents.models.ontology import (
    ClauseNode,
    ClauseType,
    DocumentRelationship,
    DocumentType,
    Obligation,
    OntologyGraph,
    PartyRole,
    RelationshipType,
)
from dd_agents.reasoning.contract_graph import ContractKnowledgeGraph, _category_to_clause_type


class TestOntologyModels:
    """Test ontology data models."""

    def test_document_types(self) -> None:
        assert DocumentType.MSA.value == "MSA"
        assert DocumentType.AMENDMENT.value == "Amendment"
        assert len(DocumentType) == 13

    def test_clause_types(self) -> None:
        assert ClauseType.OBLIGATION.value == "obligation"
        assert ClauseType.CHANGE_OF_CONTROL.value == "change_of_control"
        assert len(ClauseType) == 15

    def test_relationship_types(self) -> None:
        assert RelationshipType.AMENDS.value == "amends"
        assert RelationshipType.CONFLICTS_WITH.value == "conflicts_with"
        assert len(RelationshipType) == 8

    def test_party_roles(self) -> None:
        assert PartyRole.OBLIGOR.value == "obligor"
        assert len(PartyRole) == 6

    def test_clause_node(self) -> None:
        clause = ClauseNode(
            id="test:clause:1",
            document_path="contract.pdf",
            subject_safe_name="acme",
            clause_type=ClauseType.CHANGE_OF_CONTROL,
            summary="CoC requires consent",
            exact_quote="Party shall obtain written consent...",
        )
        assert clause.clause_type == ClauseType.CHANGE_OF_CONTROL
        assert clause.subject_safe_name == "acme"

    def test_document_relationship(self) -> None:
        rel = DocumentRelationship(
            source_id="doc1",
            target_id="doc2",
            relationship=RelationshipType.AMENDS,
            description="Amendment to MSA",
        )
        assert rel.relationship == RelationshipType.AMENDS

    def test_obligation(self) -> None:
        obl = Obligation(
            id="obl1",
            clause_id="clause1",
            subject_safe_name="acme",
            obligor="Target Inc",
            obligee="Acme Corp",
            description="Provide 30-day notice before termination",
            recurring=False,
        )
        assert obl.status == "active"

    def test_ontology_graph_model(self) -> None:
        graph = OntologyGraph()
        assert graph.clauses == []
        assert graph.total_clauses == 0


class TestContractKnowledgeGraph:
    """Test contract knowledge graph operations."""

    @pytest.fixture()
    def graph(self) -> ContractKnowledgeGraph:
        g = ContractKnowledgeGraph()
        # Add some clauses
        g.add_clause(
            ClauseNode(
                id="acme:msa:coc",
                document_path="acme_msa.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.CHANGE_OF_CONTROL,
                summary="CoC requires written consent",
            )
        )
        g.add_clause(
            ClauseNode(
                id="acme:msa:term",
                document_path="acme_msa.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.TERMINATION,
                summary="30-day termination for convenience",
            )
        )
        g.add_clause(
            ClauseNode(
                id="acme:sow:obligation",
                document_path="acme_sow.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.OBLIGATION,
                summary="Monthly reporting requirement",
            )
        )
        g.add_clause(
            ClauseNode(
                id="beta:msa:coc",
                document_path="beta_msa.pdf",
                subject_safe_name="beta",
                clause_type=ClauseType.CHANGE_OF_CONTROL,
                summary="CoC triggers automatic termination",
            )
        )
        # Add relationships
        g.add_relationship(
            DocumentRelationship(
                source_id="acme:msa:coc",
                target_id="acme:sow:obligation",
                relationship=RelationshipType.CONDITIONS,
            )
        )
        return g

    def test_total_nodes(self, graph: ContractKnowledgeGraph) -> None:
        assert graph.total_nodes == 4

    def test_total_edges(self, graph: ContractKnowledgeGraph) -> None:
        assert graph.total_edges == 1

    def test_get_clauses_by_type(self, graph: ContractKnowledgeGraph) -> None:
        coc = graph.get_clauses_by_type(ClauseType.CHANGE_OF_CONTROL)
        assert len(coc) == 2
        subjects = {c.subject_safe_name for c in coc}
        assert subjects == {"acme", "beta"}

    def test_get_clauses_by_subject(self, graph: ContractKnowledgeGraph) -> None:
        acme_clauses = graph.get_clauses_by_subject("acme")
        assert len(acme_clauses) == 3

    def test_get_affected_documents(self, graph: ContractKnowledgeGraph) -> None:
        affected = graph.get_affected_documents("acme:msa:coc")
        assert "acme:sow:obligation" in affected

    def test_get_affected_nonexistent(self, graph: ContractKnowledgeGraph) -> None:
        affected = graph.get_affected_documents("nonexistent")
        assert affected == []

    def test_coc_impact_analysis(self, graph: ContractKnowledgeGraph) -> None:
        impacts = graph.coc_impact_analysis()
        assert len(impacts) == 2
        # Acme has an affected document, beta doesn't
        acme_impact = next(i for i in impacts if i["subject"] == "acme")
        assert acme_impact["affected_count"] == 1

    def test_to_serializable(self, graph: ContractKnowledgeGraph) -> None:
        serial = graph.to_serializable()
        assert serial.total_clauses == 4
        assert serial.total_relationships == 1
        assert len(serial.clauses) == 4


class TestAmendmentChain:
    """Test amendment chain traversal."""

    def test_simple_chain(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(ClauseNode(id="v1", document_path="v1.pdf", clause_type=ClauseType.OBLIGATION))
        g.add_clause(ClauseNode(id="v2", document_path="v2.pdf", clause_type=ClauseType.OBLIGATION))
        g.add_clause(ClauseNode(id="v3", document_path="v3.pdf", clause_type=ClauseType.OBLIGATION))
        # v1 amends v2 (v1 is the amendment, v2 is the original)
        # v2 amends v3 (v2 amends v3)
        g.add_relationship(DocumentRelationship(source_id="v1", target_id="v2", relationship=RelationshipType.AMENDS))
        g.add_relationship(DocumentRelationship(source_id="v2", target_id="v3", relationship=RelationshipType.AMENDS))
        # From v2, chain should be [v1, v2, v3] — v1 amends v2 amends v3
        chain = g.get_amendment_chain("v2")
        assert len(chain) == 3
        assert "v1" in chain
        assert "v2" in chain
        assert "v3" in chain

    def test_no_amendments(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(ClauseNode(id="standalone", document_path="doc.pdf", clause_type=ClauseType.OBLIGATION))
        chain = g.get_amendment_chain("standalone")
        assert chain == ["standalone"]


class TestConflictDetection:
    """Test conflict detection."""

    def test_explicit_conflict(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(ClauseNode(id="a", document_path="a.pdf", clause_type=ClauseType.GOVERNING_LAW))
        g.add_clause(ClauseNode(id="b", document_path="b.pdf", clause_type=ClauseType.GOVERNING_LAW))
        g.add_relationship(
            DocumentRelationship(
                source_id="a",
                target_id="b",
                relationship=RelationshipType.CONFLICTS_WITH,
                description="Different governing law",
            )
        )
        conflicts = g.find_conflicts()
        assert len(conflicts) >= 1
        assert conflicts[0]["description"] == "Different governing law"

    def test_governing_law_conflict(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(
            ClauseNode(
                id="acme:gov1",
                document_path="a.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.GOVERNING_LAW,
                summary="New York law",
            )
        )
        g.add_clause(
            ClauseNode(
                id="acme:gov2",
                document_path="b.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.GOVERNING_LAW,
                summary="California law",
            )
        )
        conflicts = g.find_conflicts()
        gov_conflicts = [c for c in conflicts if c.get("type") == "governing_law_conflict"]
        assert len(gov_conflicts) == 1
        assert "acme" in gov_conflicts[0]["subject"]

    def test_no_conflict_same_law(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(
            ClauseNode(
                id="acme:gov1",
                document_path="a.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.GOVERNING_LAW,
                summary="New York law",
            )
        )
        g.add_clause(
            ClauseNode(
                id="acme:gov2",
                document_path="b.pdf",
                subject_safe_name="acme",
                clause_type=ClauseType.GOVERNING_LAW,
                summary="New York law",
            )
        )
        conflicts = g.find_conflicts()
        gov_conflicts = [c for c in conflicts if c.get("type") == "governing_law_conflict"]
        assert len(gov_conflicts) == 0


class TestObligationTracking:
    """Test obligation tracking."""

    def test_add_obligation(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_clause(ClauseNode(id="clause1", document_path="doc.pdf", clause_type=ClauseType.OBLIGATION))
        g.add_obligation(
            Obligation(
                id="obl1",
                clause_id="clause1",
                subject_safe_name="acme",
                obligor="Target",
                obligee="Acme",
                description="Monthly report",
                due_date="2026-06-01",
            )
        )
        chain = g.get_obligation_chain("acme")
        assert len(chain) == 1
        assert chain[0].description == "Monthly report"

    def test_obligation_ordering(self) -> None:
        g = ContractKnowledgeGraph()
        g.add_obligation(
            Obligation(
                id="obl2",
                clause_id="c1",
                subject_safe_name="acme",
                obligor="T",
                obligee="A",
                description="Later",
                due_date="2026-12-01",
            )
        )
        g.add_obligation(
            Obligation(
                id="obl1",
                clause_id="c1",
                subject_safe_name="acme",
                obligor="T",
                obligee="A",
                description="Earlier",
                due_date="2026-06-01",
            )
        )
        chain = g.get_obligation_chain("acme")
        assert chain[0].description == "Earlier"
        assert chain[1].description == "Later"


class TestCategoryMapping:
    """Test finding category to clause type mapping."""

    def test_coc_mapping(self) -> None:
        assert _category_to_clause_type("change_of_control") == ClauseType.CHANGE_OF_CONTROL

    def test_termination_mapping(self) -> None:
        assert _category_to_clause_type("termination_for_convenience") == ClauseType.TERMINATION

    def test_ip_mapping(self) -> None:
        assert _category_to_clause_type("ip_ownership") == ClauseType.IP_ASSIGNMENT

    def test_unknown_mapping(self) -> None:
        assert _category_to_clause_type("random_category") == ClauseType.UNKNOWN


class TestFromFindings:
    """Test building knowledge graph from merged findings."""

    def _make_merged(self) -> dict[str, Any]:
        return {
            "acme": {
                "subject": "Acme",
                "findings": [
                    {
                        "title": "CoC clause requires consent",
                        "category": "change_of_control",
                        "severity": "P0",
                        "agent": "legal",
                        "citations": [
                            {
                                "source_path": "acme_msa.pdf",
                                "exact_quote": "Party must consent...",
                                "section_ref": "§5.2",
                            },
                        ],
                    },
                    {
                        "title": "30-day TfC",
                        "category": "termination_for_convenience",
                        "severity": "P1",
                        "agent": "legal",
                        "citations": [
                            {
                                "source_path": "acme_msa.pdf",
                                "exact_quote": "Either party may terminate...",
                                "section_ref": "§12",
                            },
                        ],
                    },
                ],
                "governance_graph": {
                    "edges": [
                        {"source": "acme_sow.pdf", "target": "acme_msa.pdf", "type": "references"},
                    ],
                },
            },
        }

    def test_from_findings_extracts_clauses(self) -> None:
        graph = ContractKnowledgeGraph.from_findings(self._make_merged())
        assert graph.total_nodes >= 2
        coc = graph.get_clauses_by_type(ClauseType.CHANGE_OF_CONTROL)
        assert len(coc) == 1
        assert coc[0].subject_safe_name == "acme"

    def test_from_findings_builds_relationships(self) -> None:
        graph = ContractKnowledgeGraph.from_findings(self._make_merged())
        assert graph.total_edges >= 1

    def test_from_findings_skips_unknown(self) -> None:
        merged = {
            "acme": {
                "findings": [{"title": "Random", "category": "unknown_cat", "citations": []}],
            },
        }
        graph = ContractKnowledgeGraph.from_findings(merged)
        assert graph.total_nodes == 0
