"""Unit tests for the Unified Deal Knowledge Graph (Issue #179)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge.graph import (
    DealKnowledgeGraph,
    EdgeType,
    GraphEdge,
    NodeType,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph() -> DealKnowledgeGraph:
    """Return a fresh empty graph."""
    return DealKnowledgeGraph()


@pytest.fixture()
def populated_graph() -> DealKnowledgeGraph:
    """Return a graph with entities, documents, findings, and edges."""
    g = DealKnowledgeGraph()

    g.add_entity("acme_corp", "Acme Corporation")
    g.add_entity("globex", "Globex Industries")

    doc1 = g.add_document("acme/msa.pdf", "contract")
    doc2 = g.add_document("acme/amendment_1.pdf", "amendment")
    doc3 = g.add_document("globex/services.pdf", "contract")

    g.add_finding("f001", "P0", title="CoC risk")
    g.add_finding("f002", "P1", title="Short notice")
    g.add_finding("f003", "P2", title="Standard clause")

    g.add_article("art_001", "entity_profile", title="Acme Profile")

    # Entity -> document edges (party_to)
    g.add_edge(GraphEdge(source_id="entity:acme_corp", target_id=doc1, edge_type=EdgeType.PARTY_TO))
    g.add_edge(GraphEdge(source_id="entity:acme_corp", target_id=doc2, edge_type=EdgeType.PARTY_TO))
    g.add_edge(GraphEdge(source_id="entity:globex", target_id=doc3, edge_type=EdgeType.PARTY_TO))

    # Finding -> document edges (found_in)
    g.add_edge(GraphEdge(source_id="finding:f001", target_id=doc1, edge_type=EdgeType.FOUND_IN))
    g.add_edge(GraphEdge(source_id="finding:f002", target_id=doc1, edge_type=EdgeType.FOUND_IN))
    g.add_edge(GraphEdge(source_id="finding:f003", target_id=doc3, edge_type=EdgeType.FOUND_IN))

    # Amendment chain: amendment_1 amends msa
    g.add_edge(GraphEdge(source_id=doc2, target_id=doc1, edge_type=EdgeType.AMENDS))

    return g


# ---------------------------------------------------------------------------
# Node type and edge type enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_node_types_complete(self) -> None:
        expected = {"entity", "document", "clause", "finding", "gap", "article", "obligation"}
        assert {nt.value for nt in NodeType} == expected

    def test_edge_types_complete(self) -> None:
        expected = {
            "governs",
            "amends",
            "supersedes",
            "references",
            "incorporates",
            "conflicts_with",
            "party_to",
            "analyzed_in",
            "found_in",
            "affects",
            "contradicts",
            "corroborates",
            "derived_from",
            "related_to",
            "contains",
            "overrides",
        }
        assert {et.value for et in EdgeType} == expected


# ---------------------------------------------------------------------------
# GraphEdge model tests
# ---------------------------------------------------------------------------


class TestGraphEdge:
    def test_edge_creation(self) -> None:
        edge = GraphEdge(
            source_id="entity:acme",
            target_id="doc:abc123",
            edge_type=EdgeType.PARTY_TO,
            confidence=0.95,
            created_by="pipeline:run_001",
        )
        assert edge.source_id == "entity:acme"
        assert edge.target_id == "doc:abc123"
        assert edge.edge_type == EdgeType.PARTY_TO
        assert edge.confidence == 0.95

    def test_edge_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GraphEdge(source_id="a", target_id="b", edge_type=EdgeType.GOVERNS, confidence=1.5)
        with pytest.raises(ValidationError):
            GraphEdge(source_id="a", target_id="b", edge_type=EdgeType.GOVERNS, confidence=-0.1)

    def test_edge_serialization_roundtrip(self) -> None:
        edge = GraphEdge(
            source_id="entity:acme",
            target_id="doc:abc",
            edge_type=EdgeType.GOVERNS,
            confidence=0.8,
            metadata={"citation": "Section 4.3"},
        )
        data = edge.model_dump(mode="json")
        restored = GraphEdge.model_validate(data)
        assert restored.edge_type == EdgeType.GOVERNS
        assert restored.metadata == {"citation": "Section 4.3"}


# ---------------------------------------------------------------------------
# Node CRUD tests
# ---------------------------------------------------------------------------


class TestNodeCRUD:
    def test_add_entity(self, graph: DealKnowledgeGraph) -> None:
        node_id = graph.add_entity("acme_corp", "Acme Corporation", industry="tech")
        assert node_id == "entity:acme_corp"
        assert graph.stats["total_nodes"] == 1
        assert graph.stats["nodes_by_type"]["entity"] == 1

    def test_add_document(self, graph: DealKnowledgeGraph) -> None:
        node_id = graph.add_document("contracts/msa.pdf", "contract")
        assert node_id.startswith("doc:")
        assert graph.stats["total_nodes"] == 1
        assert graph.stats["nodes_by_type"]["document"] == 1

    def test_add_finding(self, graph: DealKnowledgeGraph) -> None:
        node_id = graph.add_finding("f001", "P0", title="Critical issue")
        assert node_id == "finding:f001"
        assert graph.stats["total_nodes"] == 1
        assert graph.stats["nodes_by_type"]["finding"] == 1

    def test_add_article(self, graph: DealKnowledgeGraph) -> None:
        node_id = graph.add_article("art_001", "entity_profile", title="Profile")
        assert node_id == "article:art_001"
        assert graph.stats["total_nodes"] == 1
        assert graph.stats["nodes_by_type"]["article"] == 1

    def test_document_id_deterministic(self, graph: DealKnowledgeGraph) -> None:
        id1 = graph.add_document("contracts/msa.pdf", "contract")
        # Adding same path again should produce same ID
        graph2 = DealKnowledgeGraph()
        id2 = graph2.add_document("contracts/msa.pdf", "contract")
        assert id1 == id2

    def test_multiple_node_types(self, populated_graph: DealKnowledgeGraph) -> None:
        stats = populated_graph.stats
        assert stats["nodes_by_type"]["entity"] == 2
        assert stats["nodes_by_type"]["document"] == 3
        assert stats["nodes_by_type"]["finding"] == 3
        assert stats["nodes_by_type"]["article"] == 1


# ---------------------------------------------------------------------------
# Edge CRUD tests
# ---------------------------------------------------------------------------


class TestEdgeCRUD:
    def test_add_and_get_edge(self, graph: DealKnowledgeGraph) -> None:
        graph.add_entity("acme", "Acme")
        doc_id = graph.add_document("msa.pdf", "contract")
        edge = GraphEdge(
            source_id="entity:acme",
            target_id=doc_id,
            edge_type=EdgeType.PARTY_TO,
        )
        graph.add_edge(edge)

        edges = graph.get_edges("entity:acme")
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.PARTY_TO

    def test_get_edges_filtered_by_type(self, graph: DealKnowledgeGraph) -> None:
        graph.add_entity("acme", "Acme")
        doc_id = graph.add_document("msa.pdf", "contract")
        art_id = graph.add_article("art_1", "profile")

        graph.add_edge(GraphEdge(source_id="entity:acme", target_id=doc_id, edge_type=EdgeType.PARTY_TO))
        graph.add_edge(GraphEdge(source_id="entity:acme", target_id=art_id, edge_type=EdgeType.ANALYZED_IN))

        party_edges = graph.get_edges("entity:acme", edge_type=EdgeType.PARTY_TO)
        assert len(party_edges) == 1
        assert party_edges[0].target_id == doc_id

        analyzed_edges = graph.get_edges("entity:acme", edge_type=EdgeType.ANALYZED_IN)
        assert len(analyzed_edges) == 1

    def test_get_edges_nonexistent_node(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_edges("entity:nonexistent") == []

    def test_edge_creates_missing_nodes(self, graph: DealKnowledgeGraph) -> None:
        edge = GraphEdge(source_id="entity:auto1", target_id="doc:auto2", edge_type=EdgeType.REFERENCES)
        graph.add_edge(edge)
        assert graph.stats["total_nodes"] == 2
        assert graph.stats["total_edges"] == 1


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_entity_documents(self, populated_graph: DealKnowledgeGraph) -> None:
        docs = populated_graph.get_entity_documents("acme_corp")
        assert len(docs) == 2
        # Both docs should be for acme
        for doc_id in docs:
            assert doc_id.startswith("doc:")

    def test_get_entity_documents_empty(self, populated_graph: DealKnowledgeGraph) -> None:
        assert populated_graph.get_entity_documents("nonexistent") == []

    def test_get_document_findings(self, populated_graph: DealKnowledgeGraph) -> None:
        findings = populated_graph.get_document_findings("acme/msa.pdf")
        assert len(findings) == 2
        assert "finding:f001" in findings
        assert "finding:f002" in findings

    def test_get_document_findings_empty(self, populated_graph: DealKnowledgeGraph) -> None:
        assert populated_graph.get_document_findings("nonexistent.pdf") == []

    def test_get_document_findings_single(self, populated_graph: DealKnowledgeGraph) -> None:
        findings = populated_graph.get_document_findings("globex/services.pdf")
        assert len(findings) == 1
        assert "finding:f003" in findings


# ---------------------------------------------------------------------------
# Amendment chain tests
# ---------------------------------------------------------------------------


class TestAmendmentChain:
    def test_simple_amendment_chain(self, populated_graph: DealKnowledgeGraph) -> None:
        chain = populated_graph.get_amendment_chain("acme/msa.pdf")
        assert len(chain) == 2
        # amendment should come before msa in topological order (amends points to msa)
        msa_id = populated_graph._doc_path_to_id["acme/msa.pdf"]
        amend_id = populated_graph._doc_path_to_id["acme/amendment_1.pdf"]
        assert amend_id in chain
        assert msa_id in chain

    def test_amendment_chain_nonexistent_doc(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_amendment_chain("nonexistent.pdf") == []

    def test_multi_step_amendment_chain(self, graph: DealKnowledgeGraph) -> None:
        doc1 = graph.add_document("original.pdf", "contract")
        doc2 = graph.add_document("amendment_1.pdf", "amendment")
        doc3 = graph.add_document("amendment_2.pdf", "amendment")

        graph.add_edge(GraphEdge(source_id=doc2, target_id=doc1, edge_type=EdgeType.AMENDS))
        graph.add_edge(GraphEdge(source_id=doc3, target_id=doc2, edge_type=EdgeType.SUPERSEDES))

        chain = graph.get_amendment_chain("original.pdf")
        assert len(chain) == 3
        # Topological order: doc3 -> doc2 -> doc1
        assert chain.index(doc3) < chain.index(doc2)
        assert chain.index(doc2) < chain.index(doc1)


# ---------------------------------------------------------------------------
# Cycle detection tests
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_no_cycles_in_dag(self, populated_graph: DealKnowledgeGraph) -> None:
        cycles = populated_graph.detect_cycles()
        assert len(cycles) == 0

    def test_detect_simple_cycle(self, graph: DealKnowledgeGraph) -> None:
        doc1 = graph.add_document("a.pdf", "contract")
        doc2 = graph.add_document("b.pdf", "contract")
        graph.add_edge(GraphEdge(source_id=doc1, target_id=doc2, edge_type=EdgeType.GOVERNS))
        graph.add_edge(GraphEdge(source_id=doc2, target_id=doc1, edge_type=EdgeType.GOVERNS))

        cycles = graph.detect_cycles()
        assert len(cycles) >= 1


# ---------------------------------------------------------------------------
# Contradiction detection tests
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    def test_no_contradictions(self, populated_graph: DealKnowledgeGraph) -> None:
        contradictions = populated_graph.detect_contradictions()
        assert len(contradictions) == 0

    def test_detect_contradiction(self, graph: DealKnowledgeGraph) -> None:
        f1 = graph.add_finding("f1", "P0")
        f2 = graph.add_finding("f2", "P3")
        graph.add_edge(
            GraphEdge(
                source_id=f1,
                target_id=f2,
                edge_type=EdgeType.CONFLICTS_WITH,
                metadata={"reason": "Severity disagreement on CoC clause"},
            )
        )

        contradictions = graph.detect_contradictions()
        assert len(contradictions) == 1
        assert contradictions[0][0] == f1
        assert contradictions[0][1] == f2
        assert "Severity disagreement" in contradictions[0][2]


# ---------------------------------------------------------------------------
# Governance graph merge tests
# ---------------------------------------------------------------------------


class TestGovernanceGraphMerge:
    def test_merge_governance_graph(self, graph: DealKnowledgeGraph) -> None:
        gov_data = {
            "edges": [
                {
                    "from_file": "sow_1.pdf",
                    "to_file": "msa.pdf",
                    "relationship": "governs",
                    "citation": {"exact_quote": "Subject to the MSA"},
                },
                {
                    "from_file": "amendment_1.pdf",
                    "to_file": "msa.pdf",
                    "relationship": "amends",
                },
            ],
        }
        added = graph.merge_governance_graph(gov_data, "run_001")
        assert added == 2
        assert graph.stats["total_nodes"] == 3  # 3 unique documents
        assert graph.stats["total_edges"] == 2

    def test_merge_governance_graph_empty(self, graph: DealKnowledgeGraph) -> None:
        added = graph.merge_governance_graph({"edges": []}, "run_001")
        assert added == 0
        assert graph.stats["total_nodes"] == 0

    def test_merge_governance_graph_invalid_edges(self, graph: DealKnowledgeGraph) -> None:
        gov_data = {
            "edges": [
                {"from_file": "", "to_file": "msa.pdf", "relationship": "governs"},
                {"from_file": "sow.pdf", "to_file": "", "relationship": "governs"},
                "not_a_dict",
            ],
        }
        added = graph.merge_governance_graph(gov_data, "run_001")
        assert added == 0

    def test_merge_governance_graph_no_edges_key(self, graph: DealKnowledgeGraph) -> None:
        added = graph.merge_governance_graph({}, "run_001")
        assert added == 0

    def test_merge_governance_graph_unknown_relationship(self, graph: DealKnowledgeGraph) -> None:
        gov_data = {
            "edges": [
                {"from_file": "a.pdf", "to_file": "b.pdf", "relationship": "unknown_rel"},
            ],
        }
        added = graph.merge_governance_graph(gov_data, "run_001")
        assert added == 1
        # Unknown relationship mapped to RELATED_TO
        edges = graph.get_edges(graph._doc_path_to_id["a.pdf"])
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.RELATED_TO


# ---------------------------------------------------------------------------
# LLM context generation tests
# ---------------------------------------------------------------------------


class TestLLMContext:
    def test_get_entity_context(self, populated_graph: DealKnowledgeGraph) -> None:
        ctx = populated_graph.get_entity_context("acme_corp")
        assert "Acme Corporation" in ctx
        assert "party_to" in ctx

    def test_get_entity_context_nonexistent(self, graph: DealKnowledgeGraph) -> None:
        ctx = graph.get_entity_context("nonexistent")
        assert "No graph data" in ctx

    def test_get_entity_context_max_chars(self, populated_graph: DealKnowledgeGraph) -> None:
        ctx = populated_graph.get_entity_context("acme_corp", max_chars=50)
        assert len(ctx) <= 50

    def test_get_document_context(self, populated_graph: DealKnowledgeGraph) -> None:
        ctx = populated_graph.get_document_context("acme/msa.pdf")
        assert "acme/msa.pdf" in ctx
        assert "contract" in ctx

    def test_get_document_context_nonexistent(self, graph: DealKnowledgeGraph) -> None:
        ctx = graph.get_document_context("nonexistent.pdf")
        assert "No graph data" in ctx

    def test_get_document_context_includes_findings(self, populated_graph: DealKnowledgeGraph) -> None:
        ctx = populated_graph.get_document_context("acme/msa.pdf")
        assert "Findings" in ctx
        assert "finding:f001" in ctx

    def test_get_document_context_max_chars(self, populated_graph: DealKnowledgeGraph) -> None:
        ctx = populated_graph.get_document_context("acme/msa.pdf", max_chars=50)
        assert len(ctx) <= 50


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load_roundtrip(self, populated_graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        save_path = tmp_path / "graph.json"
        populated_graph.save(save_path)

        assert save_path.exists()
        loaded = DealKnowledgeGraph.load(save_path)

        assert loaded.stats["total_nodes"] == populated_graph.stats["total_nodes"]
        assert loaded.stats["total_edges"] == populated_graph.stats["total_edges"]

        # Verify entity documents still work after load
        docs = loaded.get_entity_documents("acme_corp")
        assert len(docs) == 2

    def test_save_produces_valid_json(self, populated_graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        save_path = tmp_path / "graph.json"
        populated_graph.save(save_path)

        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)

    def test_to_serializable(self, populated_graph: DealKnowledgeGraph) -> None:
        data = populated_graph.to_serializable()
        assert "nodes" in data
        assert "edges" in data
        # Verify JSON-serializable (no sets, no custom objects)
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0

    def test_save_load_empty_graph(self, graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        save_path = tmp_path / "empty_graph.json"
        graph.save(save_path)
        loaded = DealKnowledgeGraph.load(save_path)
        assert loaded.stats["total_nodes"] == 0
        assert loaded.stats["total_edges"] == 0

    def test_load_preserves_edge_types(self, graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        graph.add_entity("acme", "Acme")
        doc_id = graph.add_document("msa.pdf", "contract")
        graph.add_edge(
            GraphEdge(
                source_id="entity:acme",
                target_id=doc_id,
                edge_type=EdgeType.PARTY_TO,
                confidence=0.9,
                metadata={"note": "test"},
            )
        )

        save_path = tmp_path / "graph.json"
        graph.save(save_path)
        loaded = DealKnowledgeGraph.load(save_path)

        edges = loaded.get_edges("entity:acme")
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.PARTY_TO
        assert edges[0].confidence == 0.9
        assert edges[0].metadata == {"note": "test"}


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------


class TestStats:
    def test_empty_graph_stats(self, graph: DealKnowledgeGraph) -> None:
        stats = graph.stats
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0
        assert stats["nodes_by_type"] == {}
        assert stats["edges_by_type"] == {}

    def test_populated_graph_stats(self, populated_graph: DealKnowledgeGraph) -> None:
        stats = populated_graph.stats
        assert stats["total_nodes"] == 9  # 2 entities + 3 docs + 3 findings + 1 article
        assert stats["total_edges"] == 7  # 3 party_to + 3 found_in + 1 amends
        assert stats["nodes_by_type"]["entity"] == 2
        assert stats["nodes_by_type"]["document"] == 3
        assert stats["nodes_by_type"]["finding"] == 3
        assert stats["nodes_by_type"]["article"] == 1
        assert stats["edges_by_type"]["party_to"] == 3
        assert stats["edges_by_type"]["found_in"] == 3
        assert stats["edges_by_type"]["amends"] == 1


# ---------------------------------------------------------------------------
# Empty graph safety tests
# ---------------------------------------------------------------------------


class TestEmptyGraphSafety:
    def test_get_entity_documents_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_entity_documents("x") == []

    def test_get_document_findings_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_document_findings("x.pdf") == []

    def test_get_amendment_chain_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_amendment_chain("x.pdf") == []

    def test_detect_cycles_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.detect_cycles() == []

    def test_detect_contradictions_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.detect_contradictions() == []

    def test_stats_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.stats["total_nodes"] == 0

    def test_get_edges_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.get_edges("nonexistent") == []

    def test_merge_governance_empty(self, graph: DealKnowledgeGraph) -> None:
        assert graph.merge_governance_graph({}, "r1") == 0


# ---------------------------------------------------------------------------
# Save atomicity tests (U3)
# ---------------------------------------------------------------------------


class TestSaveAtomicity:
    def test_save_does_not_leave_tmp_file(self, graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        """After save(), no .tmp file should remain."""
        graph.add_entity("test", "Test")
        save_path = tmp_path / "graph.json"
        graph.save(save_path)
        assert save_path.exists()
        assert not save_path.with_suffix(".tmp").exists()

    def test_save_creates_parent_dirs(self, graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        """save() should create missing parent directories."""
        deep_path = tmp_path / "a" / "b" / "c" / "graph.json"
        graph.add_entity("test", "Test")
        graph.save(deep_path)
        assert deep_path.exists()

    def test_save_is_valid_json(self, graph: DealKnowledgeGraph, tmp_path: Path) -> None:
        """Saved file must be valid JSON loadable by load()."""
        graph.add_entity("acme", "Acme")
        graph.add_document("msa.pdf", "contract")
        graph.add_edge(
            GraphEdge(
                source_id="entity:acme",
                target_id=graph._doc_path_to_id["msa.pdf"],
                edge_type=EdgeType.PARTY_TO,
            )
        )
        save_path = tmp_path / "graph.json"
        graph.save(save_path)

        # Load and verify integrity
        data = json.loads(save_path.read_text(encoding="utf-8"))
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        loaded = DealKnowledgeGraph.load(save_path)
        assert loaded.stats["total_nodes"] == 2
