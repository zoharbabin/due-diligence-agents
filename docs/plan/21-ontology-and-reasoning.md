# 21 -- Contract Ontology, Graph-Based Reasoning, and Explainability

How the DD system understands contract language, maintains reasoning chains, and produces verifiable findings. This document defines the lightweight ontology for contract documents, the graph-based reasoning architecture, and the explainability framework that ensures every finding is traceable to source text.

Cross-references: `01-architecture-decisions.md` (ADR-04: NetworkX), `04-data-models.md` (GovernanceEdge, Finding, Citation), `06-agents.md` (specialist focus areas, Judge protocol), `07-tools-and-hooks.md` (verify_citation hook), `11-qa-validation.md` (audit gates, numerical validation), `19-vector-graph-db-comparison.md` (NetworkX selection rationale), `20-cross-document-analysis.md` (cross-document patterns).

**Implementation files** (see also `17-file-manifest.md`): `models/ontology.py` (Pydantic models), `reasoning/contract_graph.py` (NetworkX graph operations), `reasoning/verification.py` (hallucination prevention). These files are listed in the file manifest under the Reasoning category.

**Dependency direction with doc 20**: Doc 20 (cross-document analysis) defines the analysis patterns. Doc 21 (this document — ontology and reasoning) provides the data structures and graph algorithms that support those patterns. Dependency direction: doc 21 provides infrastructure that doc 20 consumes. Implementation order: build doc 21's models and graph first, then implement doc 20's analysis patterns on top.

---

## 1. The Accuracy Challenge

Contract analysis is among the most demanding applications for LLM-based systems. Three independent research findings define the risk landscape this architecture must address.

### 1.1 Baseline Accuracy Is Insufficient

The Addleshaw Goddard (AG) RAG report evaluated LLM performance on contract review tasks. Key findings:

- **Baseline accuracy**: 74% on contract provision extraction and analysis. This means roughly 1 in 4 contract provisions are missed, misidentified, or incorrectly characterized.
- **Optimized accuracy**: 95% after applying clause-aware chunking (3,500 characters with 700-character overlap), hybrid retrieval (keyword + semantic), provision-specific prompts, and follow-up verification prompts.
- **Implication**: A naive "send the contract to the LLM" approach fails on every fourth clause. For M&A due diligence reviewing 400 documents across 200 customers, a 26% error rate produces hundreds of incorrect findings -- unacceptable for legal-grade output.

### 1.2 Hallucination Is Structural, Not Incidental

The Stanford study on legal AI tools found hallucination rates of 17-33% across commercial legal AI products. Hallucinations in contract analysis take specific forms:

- **Fabricated clauses**: The model reports a clause that does not exist in the document
- **Invented citations**: The model generates an exact_quote that appears nowhere in the source text
- **Conflated provisions**: The model merges language from two different sections into a single finding
- **Phantom cross-references**: The model asserts that Document A references Document B when no such reference exists

For forensic M&A due diligence, a fabricated finding at P0 severity could influence deal negotiations. A missed P0 clause could expose the acquirer to undisclosed liability. Both failure modes have material financial consequences.

### 1.3 Agentic Workflows Compound Errors

Multi-step agentic pipelines face exponential error accumulation. With a 10% per-step error rate across a 10-step pipeline, the probability of a fully correct output is:

```
(1 - 0.10)^10 = 0.349 = 34.9% success rate
```

This means roughly 2 out of 3 multi-step analyses will contain at least one error. For a 35-step pipeline (this system's full scope), even a 3% per-step error rate yields:

```
(1 - 0.03)^35 = 0.344 = 34.4% success rate
```

### 1.4 Context Window Degradation

Even models advertising 128K token context windows show measurable accuracy degradation starting at approximately 64K tokens. The "lost in the middle" phenomenon means information placed in the middle of long contexts is recalled less accurately than information at the beginning or end. For contract analysis, this means:

- Critical clauses buried in the middle of a long document may be missed
- Cross-reference data from the 15th page of a spreadsheet may be ignored
- Amendment details in the body of a multi-document prompt may be overlooked

### 1.5 How This Architecture Addresses These Risks

| Risk | AG Finding / Stanford Finding | Architectural Mitigation |
|------|------------------------------|--------------------------|
| 74% baseline accuracy | AG report | Clause-aware chunking, provision-specific prompts, follow-up verification prompts (Section 5) |
| 17-33% hallucination rate | Stanford study | Citation verification hook, dual-citation requirement, deterministic graph operations (Section 6) |
| Agentic error compounding | 10% per step | Deterministic Python gates, independent validation at each gate, Judge as independent verifier (Section 8) |
| Context window degradation at 64K | Lost-in-the-middle | Customer batching, per-customer analysis, reference file routing, 80K token prompt ceiling (Section 7) |
| Fabricated cross-references | Stanford study | Graph-based provenance tracking, amendment chain traversal, contradiction detection (Section 3) |

The core design principle: **replace probabilistic LLM reasoning with deterministic computation wherever possible**. The LLM reads contracts and extracts structured data. Python validates that data. NetworkX reasons over relationships. The LLM never decides whether to validate -- Python always validates.

---

## 2. Contract Ontology Schema

A lightweight ontology for contract documents at the project's scale (~200 customers, ~400 documents, ~1,000 governance edges). This is not an enterprise knowledge graph -- it is a typed vocabulary that ensures agents, validators, and graph operations share a common language.

### 2.1 Document Types

```python
# src/dd_agents/models/ontology.py

from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class DocumentType(str, Enum):
    """Contract document types. Used in FileHeader.doc_type_guess."""
    MSA = "MSA"                             # Master Service Agreement
    ORDER_FORM = "OrderForm"                 # Order Form / Purchase Order addendum
    AMENDMENT = "Amendment"                  # Modification to existing agreement
    SIDE_LETTER = "SideLetter"               # Informal modification or waiver
    SOW = "SOW"                              # Statement of Work
    NDA = "NDA"                              # Non-Disclosure Agreement
    DPA = "DPA"                              # Data Processing Agreement/Addendum
    SLA = "SLA"                              # Service Level Agreement
    PURCHASE_ORDER = "PurchaseOrder"          # Standalone purchase order
    RENEWAL_AGREEMENT = "RenewalAgreement"   # Explicit renewal contract
    ASSIGNMENT_AGREEMENT = "AssignmentAgreement"  # Assignment of rights
    TERMINATION_NOTICE = "TerminationNotice" # Notice of termination
    UNKNOWN = "Unknown"                      # Unclassifiable document
```

**Hierarchy**: MSA is the root document type. All other types either reference, modify, or operate under an MSA. If no MSA exists for a customer, the most comprehensive agreement (often the first signed contract) takes the MSA role with `governed_by: "SELF"`.

### 2.2 Clause Types

```python
class ClauseType(str, Enum):
    """Clause types found within contract documents.
    Used in reasoning chains and ontology graph edges."""
    TERMINATION = "Termination"
    INDEMNITY = "Indemnity"
    LIMITATION_OF_LIABILITY = "LimitationOfLiability"
    ASSIGNMENT = "Assignment"
    CHANGE_OF_CONTROL = "ChangeOfControl"
    IP_OWNERSHIP = "IPOwnership"
    CONFIDENTIALITY = "Confidentiality"
    DATA_PROTECTION = "DataProtection"
    GOVERNING_LAW = "GoverningLaw"
    DISPUTE_RESOLUTION = "DisputeResolution"
    NON_COMPETE = "NonCompete"
    SLA_TERMS = "SLATerms"
    PRICING = "Pricing"
    PAYMENT_TERMS = "PaymentTerms"
    AUTO_RENEWAL = "AutoRenewal"
    NOTICE_REQUIREMENTS = "NoticeRequirements"
    FORCE_MAJEURE = "ForceMajeure"
    EXCLUSIVITY = "Exclusivity"
    MFN = "MostFavoredNation"
    WARRANTY = "Warranty"
```

### 2.3 Relationship Types

```python
class RelationshipType(str, Enum):
    """Typed relationships between documents, clauses, and parties.
    Extends GovernanceRelationship from 04-data-models.md."""
    # Document-to-document
    GOVERNS = "GOVERNS"             # MSA governs Order Form
    AMENDS = "AMENDS"               # Amendment modifies MSA
    SUPERSEDES = "SUPERSEDES"       # New agreement replaces old
    REFERENCES = "REFERENCES"       # Document mentions another
    INCORPORATES = "INCORPORATES"   # Document includes another by reference

    # Clause-level
    CONFLICTS_WITH = "CONFLICTS_WITH"  # Two clauses contradict
    DEFINES = "DEFINES"                # Clause defines a term used elsewhere
    WAIVES = "WAIVES"                  # Side letter waives a right

    # Party-level
    CONTROLS = "CONTROLS"           # Parent entity controls subsidiary
    ASSIGNED_TO = "ASSIGNED_TO"     # Rights assigned to new party
```

### 2.4 Party Roles

```python
class PartyRole(str, Enum):
    """Roles that entities play in contract relationships."""
    SERVICE_PROVIDER = "ServiceProvider"  # The target company (being acquired)
    CUSTOMER = "Customer"                # Counterparty receiving services
    GUARANTOR = "Guarantor"              # Entity guaranteeing obligations
    ASSIGNEE = "Assignee"                # Entity receiving assigned rights
    SUBSIDIARY = "Subsidiary"            # Controlled entity
    PARENT = "Parent"                    # Controlling entity
```

### 2.5 Ontology Node Models

```python
class ContractNode(BaseModel):
    """A node in the contract ontology graph representing a document."""
    model_config = ConfigDict(extra="forbid")

    document_id: str                         # Unique ID: customer_safe_name + filename hash
    file_path: str                           # Original file path in data room
    text_path: str | None = None             # Path to pre-extracted text
    doc_type: DocumentType
    customer: str                            # Canonical customer name
    customer_safe_name: str
    effective_date: str | None = None        # YYYY-MM-DD
    expiry_date: str | None = None           # YYYY-MM-DD
    parties: list[str] = Field(default_factory=list)
    governed_by: str = "UNRESOLVED"          # File path, "SELF", or "UNRESOLVED"


class ClauseNode(BaseModel):
    """A node representing a specific clause within a document."""
    model_config = ConfigDict(extra="forbid")

    clause_id: str                           # document_id + section identifier
    document_id: str                         # Parent document
    clause_type: ClauseType
    section_ref: str = ""                    # "Section 4.2", "Clause 12(a)", etc.
    exact_quote: str = ""                    # Verbatim text of the clause
    summary: str = ""                        # Agent-generated summary


class PartyNode(BaseModel):
    """A node representing a legal entity in contract relationships."""
    model_config = ConfigDict(extra="forbid")

    entity_name: str                         # Canonical name
    role: PartyRole
    aliases: list[str] = Field(default_factory=list)
```

### 2.6 Ontology Edge Model

```python
class OntologyEdge(BaseModel):
    """A typed, directed edge in the ontology graph.
    Extends GovernanceEdge from 04-data-models.md with richer typing."""
    model_config = ConfigDict(extra="forbid")

    from_node: str                           # Source node ID
    to_node: str                             # Target node ID
    relationship: RelationshipType
    evidence: str = ""                       # How the relationship was established
    citation_source: str = ""                # File path where evidence was found
    citation_location: str = ""              # Section/page reference
    citation_quote: str = ""                 # Exact text establishing the relationship
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    detected_by: str = ""                    # Agent name that detected this edge
```

---

## 3. Graph-Based Reasoning Architecture

NetworkX graphs enable deterministic reasoning about contract relationships. Every query below replaces what would otherwise be an LLM inference ("does Amendment #2 modify the MSA?") with a graph traversal ("is there a path from Amendment #2 to MSA via AMENDS edges?").

### 3.1 Building the Contract Graph

```python
# src/dd_agents/reasoning/contract_graph.py

import networkx as nx
from datetime import date
from dd_agents.models.ontology import (
    ContractNode, ClauseNode, OntologyEdge,
    RelationshipType, DocumentType,
)
from dd_agents.models.governance import GovernanceGraph, GovernanceEdge


class ContractReasoningGraph:
    """NetworkX-backed contract reasoning graph for a single customer.

    Nodes: documents (ContractNode), clauses (ClauseNode), parties (PartyNode)
    Edges: typed relationships (OntologyEdge)

    All queries are deterministic graph traversals, not LLM inferences.
    """

    def __init__(self, customer: str, customer_safe_name: str):
        self.customer = customer
        self.customer_safe_name = customer_safe_name
        self.G = nx.DiGraph()

    def add_document(self, node: ContractNode) -> None:
        """Add a document node to the graph."""
        self.G.add_node(
            node.document_id,
            node_type="document",
            file_path=node.file_path,
            doc_type=node.doc_type.value,
            effective_date=node.effective_date,
            expiry_date=node.expiry_date,
            parties=node.parties,
        )

    def add_clause(self, node: ClauseNode) -> None:
        """Add a clause node and link it to its parent document."""
        self.G.add_node(
            node.clause_id,
            node_type="clause",
            clause_type=node.clause_type.value,
            section_ref=node.section_ref,
            summary=node.summary,
        )
        # Clause belongs to document
        self.G.add_edge(
            node.document_id, node.clause_id,
            relationship="CONTAINS",
        )

    def add_relationship(self, edge: OntologyEdge) -> None:
        """Add a typed relationship edge."""
        self.G.add_edge(
            edge.from_node, edge.to_node,
            relationship=edge.relationship.value,
            evidence=edge.evidence,
            citation_source=edge.citation_source,
            citation_quote=edge.citation_quote,
            confidence=edge.confidence,
            detected_by=edge.detected_by,
        )

    @classmethod
    def from_governance_graph(
        cls,
        customer: str,
        customer_safe_name: str,
        gov_graph: GovernanceGraph,
    ) -> "ContractReasoningGraph":
        """Build from existing GovernanceGraph (04-data-models.md)."""
        crg = cls(customer, customer_safe_name)
        for edge in gov_graph.edges:
            crg.G.add_node(edge.from_file, node_type="document", file_path=edge.from_file)
            crg.G.add_node(edge.to_file, node_type="document", file_path=edge.to_file)
            crg.G.add_edge(
                edge.from_file, edge.to_file,
                relationship=edge.relationship.upper() if edge.relationship else "REFERENCES",
                evidence=edge.link_reason,
                citation_quote=edge.citation.exact_quote if edge.citation else "",
            )
        return crg
```

### 3.2 Clause Provenance Tracking

Determine which document introduced a specific term or clause -- critical for understanding whether an amendment changed the original provision.

```python
    # ContractReasoningGraph continued

    def get_clause_provenance(self, clause_id: str) -> list[dict]:
        """Trace which document(s) define a clause and how it was modified.

        Returns a list of (document, relationship) pairs showing the
        clause's history from original introduction through amendments.

        Example output:
        [
            {"document": "MSA-2024.pdf", "relationship": "DEFINES", "date": "2024-01-15"},
            {"document": "Amendment-1.pdf", "relationship": "AMENDS", "date": "2024-06-01"},
            {"document": "SideLetter-2024.pdf", "relationship": "WAIVES", "date": "2024-09-15"},
        ]
        """
        provenance = []
        if clause_id not in self.G:
            return provenance

        # Find the document that contains this clause
        parent_docs = [
            pred for pred in self.G.predecessors(clause_id)
            if self.G.nodes[pred].get("node_type") == "document"
        ]
        if not parent_docs:
            return provenance

        origin_doc = parent_docs[0]
        provenance.append({
            "document": self.G.nodes[origin_doc].get("file_path", origin_doc),
            "relationship": "DEFINES",
            "date": self.G.nodes[origin_doc].get("effective_date", ""),
        })

        # Find all documents that AMEND or WAIVE this clause
        for node in self.G.nodes:
            if self.G.nodes[node].get("node_type") != "document":
                continue
            # Check if this document has an edge that modifies the origin
            for _, target, data in self.G.out_edges(node, data=True):
                rel = data.get("relationship", "")
                if target == origin_doc and rel in ("AMENDS", "SUPERSEDES", "WAIVES"):
                    provenance.append({
                        "document": self.G.nodes[node].get("file_path", node),
                        "relationship": rel,
                        "date": self.G.nodes[node].get("effective_date", ""),
                    })

        # Sort by date
        provenance.sort(key=lambda p: p.get("date", "") or "9999")
        return provenance
```

### 3.3 Amendment Chain Traversal

Follow the full chain from original agreement through all modifications to determine current effective terms.

```python
    def get_amendment_chain(self, document_id: str) -> list[str]:
        """Traverse from a document through all AMENDS/SUPERSEDES edges
        to build the ordered amendment chain.

        Returns: [original_doc, amendment_1, amendment_2, ..., current_doc]
        """
        chain = []
        visited = set()

        def _walk_back(node_id: str) -> str | None:
            """Walk backwards to find the root (original) document."""
            for pred in self.G.predecessors(node_id):
                edge_data = self.G.edges[pred, node_id]
                rel = edge_data.get("relationship", "")
                if rel in ("AMENDS", "SUPERSEDES") and pred not in visited:
                    visited.add(pred)
                    return pred
            return None

        # Walk backwards to find root
        current = document_id
        path_to_root = [current]
        visited.add(current)
        while True:
            parent = _walk_back(current)
            if parent is None:
                break
            path_to_root.append(parent)
            current = parent

        # Reverse to get root-first order
        chain = list(reversed(path_to_root))

        # Walk forwards to find any later amendments not yet in chain
        def _walk_forward(node_id: str) -> None:
            for succ in self.G.successors(node_id):
                edge_data = self.G.edges[node_id, succ]
                rel = edge_data.get("relationship", "")
                if rel in ("AMENDS", "SUPERSEDES") and succ not in visited:
                    visited.add(succ)
                    chain.append(succ)
                    _walk_forward(succ)

        for node in list(chain):
            _walk_forward(node)

        return chain
```

### 3.4 Point-in-Time State Reconstruction

Determine what terms were effective on a specific date by filtering the amendment chain.

```python
    def get_effective_terms_at(
        self, document_id: str, as_of: str
    ) -> list[str]:
        """Return the documents that were effective on `as_of` date.

        For a given base document, finds all amendments/supersessions
        that were effective on or before the as_of date.

        Args:
            document_id: The base document (e.g., the MSA)
            as_of: Date string in YYYY-MM-DD format

        Returns: list of document IDs effective on that date, in precedence order
        """
        chain = self.get_amendment_chain(document_id)
        effective = []
        for doc_id in chain:
            node_data = self.G.nodes.get(doc_id, {})
            effective_date = node_data.get("effective_date", "")
            if effective_date and effective_date <= as_of:
                effective.append(doc_id)
            elif not effective_date:
                # No date available -- include with caveat
                effective.append(doc_id)
        return effective
```

### 3.5 Contradiction Detection

Identify conflicts via graph patterns. Two clauses conflict when they operate on the same right with opposing effects.

```python
    def detect_contradictions(self) -> list[dict]:
        """Detect contradictions using graph patterns.

        Contradiction patterns:
        1. GRANTS + WAIVES on the same right (clause type)
        2. AMENDS with conflicting values on the same clause
        3. Two documents GOVERN the same subordinate (multi-parent)
        4. Circular governance (A governs B governs A)

        Returns: list of contradiction descriptions with evidence.
        """
        contradictions = []

        # Pattern 1: Conflicting clause operations
        clause_effects: dict[str, list[dict]] = {}  # clause_type -> [effects]
        for u, v, data in self.G.edges(data=True):
            rel = data.get("relationship", "")
            if rel in ("DEFINES", "WAIVES", "AMENDS"):
                target_type = self.G.nodes.get(v, {}).get("clause_type", "")
                if target_type:
                    clause_effects.setdefault(target_type, []).append({
                        "source": u,
                        "target": v,
                        "relationship": rel,
                        "evidence": data.get("citation_quote", ""),
                    })

        for clause_type, effects in clause_effects.items():
            relationships = {e["relationship"] for e in effects}
            if "DEFINES" in relationships and "WAIVES" in relationships:
                contradictions.append({
                    "type": "GRANT_WAIVE_CONFLICT",
                    "clause_type": clause_type,
                    "effects": effects,
                    "description": (
                        f"{clause_type}: One document DEFINES the right "
                        f"while another WAIVES it entirely"
                    ),
                })

        # Pattern 2: Multi-parent governance
        for node in self.G.nodes:
            if self.G.nodes[node].get("node_type") != "document":
                continue
            governing_parents = []
            for pred in self.G.predecessors(node):
                edge_data = self.G.edges[pred, node]
                if edge_data.get("relationship") == "GOVERNS":
                    governing_parents.append(pred)
            if len(governing_parents) > 1:
                contradictions.append({
                    "type": "MULTI_PARENT_GOVERNANCE",
                    "document": node,
                    "governing_parents": governing_parents,
                    "description": (
                        f"Document '{node}' is governed by multiple parents: "
                        f"{governing_parents}"
                    ),
                })

        # Pattern 3: Circular governance
        try:
            cycle = nx.find_cycle(self.G, orientation="original")
            contradictions.append({
                "type": "CIRCULAR_GOVERNANCE",
                "cycle": [(u, v) for u, v, _ in cycle],
                "description": f"Circular governance detected: {cycle}",
            })
        except nx.NetworkXNoCycle:
            pass

        return contradictions
```

### 3.6 Change-of-Control Impact Analysis

Traverse CONTROLS edges from the target entity and identify all contracts with change-of-control or assignment clauses.

```python
    def analyze_change_of_control_impact(
        self, target_entity: str
    ) -> list[dict]:
        """Find all contracts affected by a change-of-control event.

        1. Find all entities controlled by target_entity (CONTROLS edges)
        2. Find all contracts involving those entities
        3. Filter for contracts with ChangeOfControl or Assignment clauses
        4. Return the affected contracts with their CoC clause details

        This is the core analysis for M&A due diligence: which customer
        contracts could be terminated or renegotiated upon acquisition?
        """
        affected = []

        # Step 1: Find controlled entities
        controlled_entities = set()
        controlled_entities.add(target_entity)
        for node in self.G.nodes:
            node_data = self.G.nodes[node]
            if node_data.get("node_type") != "document":
                # Check party nodes for CONTROLS relationship
                for _, target, data in self.G.out_edges(node, data=True):
                    if data.get("relationship") == "CONTROLS":
                        controlled_entities.add(target)

        # Step 2-3: Find contracts with CoC/Assignment clauses
        for node in self.G.nodes:
            node_data = self.G.nodes[node]
            if node_data.get("node_type") != "clause":
                continue
            clause_type = node_data.get("clause_type", "")
            if clause_type not in ("ChangeOfControl", "Assignment"):
                continue

            # Find the parent document
            for pred in self.G.predecessors(node):
                if self.G.nodes[pred].get("node_type") == "document":
                    parties = self.G.nodes[pred].get("parties", [])
                    # Check if any controlled entity is a party
                    involved = [p for p in parties if p in controlled_entities]
                    if involved:
                        affected.append({
                            "document": self.G.nodes[pred].get("file_path", pred),
                            "doc_type": self.G.nodes[pred].get("doc_type", ""),
                            "clause_type": clause_type,
                            "section_ref": node_data.get("section_ref", ""),
                            "summary": node_data.get("summary", ""),
                            "affected_entities": involved,
                        })

        return affected
```

---

## 4. Explainability: Reasoning Chains as Graph Paths

Every finding in the final report includes a verifiable reasoning chain. A reasoning chain is a sequence of (document, clause, relationship) triples that traces the logical path from source evidence to conclusion. This ensures lawyers reviewing the report can verify every step.

### 4.1 Reasoning Chain Structure

```python
# src/dd_agents/models/reasoning.py

from pydantic import BaseModel, Field, ConfigDict
from dd_agents.models.ontology import RelationshipType, ClauseType


class ReasoningStep(BaseModel):
    """A single step in a reasoning chain.
    Each step represents one traversal of a graph edge."""
    model_config = ConfigDict(extra="forbid")

    step_number: int
    document: str                            # File path of the document
    section_ref: str = ""                    # Section or clause reference
    clause_type: ClauseType | None = None
    relationship: RelationshipType | None = None  # How this step connects to next
    exact_quote: str = ""                    # Verbatim text supporting this step
    summary: str                             # What this step establishes


class ReasoningChain(BaseModel):
    """A complete reasoning chain from evidence to conclusion.
    Stored alongside each finding for audit and explainability."""
    model_config = ConfigDict(extra="forbid")

    chain_id: str                            # finding_id + "_chain"
    finding_id: str                          # The finding this chain supports
    steps: list[ReasoningStep] = Field(min_length=1)
    conclusion: str                          # The finding's title/description
    chain_valid: bool = True                 # Set by validation (Section 10)

    def to_narrative(self) -> str:
        """Convert the chain to a human-readable narrative.
        Used in the Excel report's Reasoning column."""
        parts = []
        for step in self.steps:
            rel_arrow = f" --[{step.relationship.value}]--> " if step.relationship else " => "
            parts.append(
                f"Step {step.step_number}: {step.document} "
                f"{step.section_ref}: {step.summary}"
                f"{rel_arrow}"
            )
        parts.append(f"FINDING: {self.conclusion}")
        return "\n".join(parts)
```

### 4.2 Example Reasoning Chain

A concrete example showing how a termination rights inconsistency is traced across three documents:

```python
# Example: Inconsistent termination rights across MSA, Amendment, and Order Form

example_chain = ReasoningChain(
    chain_id="forensic-dd_legal_0042_chain",
    finding_id="forensic-dd_legal_0042",
    steps=[
        ReasoningStep(
            step_number=1,
            document="./Above 200K/Globex Corp/MSA-2023.pdf",
            section_ref="Section 4.2",
            clause_type=ClauseType.TERMINATION,
            relationship=RelationshipType.DEFINES,
            exact_quote="Either party may terminate this Agreement for cause upon "
                        "thirty (30) days written notice.",
            summary="MSA grants mutual termination right with 30-day notice",
        ),
        ReasoningStep(
            step_number=2,
            document="./Above 200K/Globex Corp/Amendment-2-2024.pdf",
            section_ref="Section 1(b)",
            clause_type=ClauseType.TERMINATION,
            relationship=RelationshipType.AMENDS,
            exact_quote="Section 4.2 of the Agreement is hereby amended to add: "
                        "'provided, however, that Customer may not terminate during "
                        "the first twelve (12) months of any Order Form.'",
            summary="Amendment #2 adds termination lock-in period for Order Forms",
        ),
        ReasoningStep(
            step_number=3,
            document="./Above 200K/Globex Corp/OrderForm-003-2024.pdf",
            section_ref="Exhibit A, Section 3",
            clause_type=ClauseType.TERMINATION,
            relationship=RelationshipType.WAIVES,
            exact_quote="Notwithstanding anything in the Agreement to the contrary, "
                        "Customer shall have the right to terminate this Order Form "
                        "at any time without cause upon fifteen (15) days notice.",
            summary="Order Form #3 waives the lock-in period entirely",
        ),
    ],
    conclusion=(
        "Termination rights inconsistency: MSA Section 4.2 grants mutual "
        "termination right, Amendment #2 adds 12-month lock-in for Order Forms, "
        "but Order Form #3 waives the lock-in entirely. The Order Form language "
        "may override the Amendment depending on governing law interpretation."
    ),
)

# Narrative output:
# Step 1: ./Above 200K/Globex Corp/MSA-2023.pdf Section 4.2:
#   MSA grants mutual termination right --[DEFINES]-->
# Step 2: ./Above 200K/Globex Corp/Amendment-2-2024.pdf Section 1(b):
#   Amendment #2 adds termination lock-in period --[AMENDS]-->
# Step 3: ./Above 200K/Globex Corp/OrderForm-003-2024.pdf Exhibit A, Section 3:
#   Order Form #3 waives the lock-in entirely --[WAIVES]-->
# FINDING: Termination rights inconsistency...
```

### 4.3 Reasoning Chain Storage

Reasoning chains are stored as JSON alongside the finding in the merged customer output:

```json
{
  "id": "forensic-dd_legal_0042",
  "severity": "P1",
  "category": "termination",
  "title": "Termination rights inconsistency across MSA, Amendment #2, Order Form #3",
  "description": "...",
  "citations": [ ... ],
  "confidence": "high",
  "reasoning_chain": {
    "chain_id": "forensic-dd_legal_0042_chain",
    "finding_id": "forensic-dd_legal_0042",
    "steps": [
      {
        "step_number": 1,
        "document": "./Above 200K/Globex Corp/MSA-2023.pdf",
        "section_ref": "Section 4.2",
        "clause_type": "Termination",
        "relationship": "DEFINES",
        "exact_quote": "Either party may terminate this Agreement...",
        "summary": "MSA grants mutual termination right with 30-day notice"
      },
      {
        "step_number": 2,
        "document": "./Above 200K/Globex Corp/Amendment-2-2024.pdf",
        "section_ref": "Section 1(b)",
        "clause_type": "Termination",
        "relationship": "AMENDS",
        "exact_quote": "Section 4.2 of the Agreement is hereby amended...",
        "summary": "Amendment #2 adds termination lock-in period for Order Forms"
      },
      {
        "step_number": 3,
        "document": "./Above 200K/Globex Corp/OrderForm-003-2024.pdf",
        "section_ref": "Exhibit A, Section 3",
        "clause_type": "Termination",
        "relationship": "WAIVES",
        "exact_quote": "Notwithstanding anything in the Agreement...",
        "summary": "Order Form #3 waives the lock-in period entirely"
      }
    ],
    "conclusion": "Termination rights inconsistency...",
    "chain_valid": true
  }
}
```

### 4.4 Reasoning Chains in the Excel Report

The Excel report includes reasoning chains in two forms:

1. **Reasoning_Summary column** (Findings sheet): The `conclusion` field as a single cell
2. **Reasoning_Chain column** (Wolf_Pack sheet, P0/P1 findings): The full `to_narrative()` output, formatted with line breaks within the cell

This ensures lawyers reviewing the report can trace every P0/P1 finding back to specific document sections without opening the JSON files.

### 4.5 Judge Validation of Reasoning Chains

The Judge agent validates reasoning chains as part of its spot-check protocol (see `06-agents.md` Section 10.4). For each sampled finding that includes a reasoning chain:

1. **Chain traversability**: Every step references a document that exists in the customer's file list
2. **Citation verification**: Every `exact_quote` in the chain is verified against the source document (via the `verify_citation` MCP tool)
3. **Relationship validity**: Each relationship type is logically valid for the document types involved (e.g., an MSA cannot AMEND an Order Form -- only the reverse)
4. **Conclusion support**: The conclusion logically follows from the chain steps

```python
# src/dd_agents/reasoning/chain_validator.py

from dd_agents.models.reasoning import ReasoningChain, ReasoningStep


class ChainValidator:
    """Deterministic validation of reasoning chains.
    Runs as part of the QA audit (pipeline step 28)."""

    def __init__(self, customer_files: set[str], text_dir: Path):
        self.customer_files = customer_files
        self.text_dir = text_dir

    def validate(self, chain: ReasoningChain) -> list[str]:
        """Validate a reasoning chain. Returns list of errors (empty = valid)."""
        errors = []

        # Check 1: All referenced documents exist
        for step in chain.steps:
            if step.document not in self.customer_files:
                errors.append(
                    f"Step {step.step_number}: document '{step.document}' "
                    f"not in customer file list"
                )

        # Check 2: All quotes can be found in source text
        for step in chain.steps:
            if step.exact_quote:
                text_path = self._resolve_text_path(step.document)
                if text_path and text_path.exists():
                    text = text_path.read_text(encoding="utf-8")
                    normalized_quote = self._normalize(step.exact_quote)
                    normalized_text = self._normalize(text)
                    if normalized_quote not in normalized_text:
                        errors.append(
                            f"Step {step.step_number}: exact_quote not found "
                            f"in extracted text of '{step.document}'"
                        )

        # Check 3: Chain has at least 2 steps for cross-document findings
        if len(chain.steps) < 2 and chain.conclusion and "inconsistency" in chain.conclusion.lower():
            errors.append(
                "Cross-document finding requires at least 2 chain steps"
            )

        # Check 4: Steps are in order
        step_numbers = [s.step_number for s in chain.steps]
        if step_numbers != sorted(step_numbers):
            errors.append("Steps are not in sequential order")

        return errors
```

---

## 5. Retrieval Optimization (RAG Lessons Applied)

Based on the Addleshaw Goddard report findings, this system applies five retrieval optimizations to achieve the 74% to 95% accuracy improvement.

### 5.1 Clause-Aware Chunking

Standard fixed-size chunking splits text at arbitrary points, often breaking a clause in the middle. Clause-aware chunking respects document structure:

```python
# src/dd_agents/reasoning/chunking.py

import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    """A chunk of text with metadata about its position and type."""
    text: str
    start_char: int
    end_char: int
    section_ref: str           # "Section 4.2" or "Clause 12(a)"
    document_path: str
    chunk_index: int


# Regex patterns for section boundaries in contracts
SECTION_PATTERNS = [
    r"(?:^|\n)(?:Section|SECTION)\s+\d+(?:\.\d+)*",   # Section 4.2
    r"(?:^|\n)(?:Article|ARTICLE)\s+\w+",               # Article IV
    r"(?:^|\n)\d+(?:\.\d+)*\s+[A-Z]",                   # 12.3 Termination
    r"(?:^|\n)(?:Clause|CLAUSE)\s+\d+",                  # Clause 12
    r"(?:^|\n)(?:Exhibit|Schedule|Appendix)\s+[A-Z]",    # Exhibit A
]


def chunk_contract_text(
    text: str,
    document_path: str,
    max_chunk_size: int = 3500,
    overlap: int = 700,
) -> list[TextChunk]:
    """Clause-aware chunking per AG report findings.

    Key principles:
    1. Never split in the middle of a clause/section
    2. Keep definitions with their usage (definitions section stays whole)
    3. Respect section boundaries as natural chunk points
    4. Use 3,500 char chunks with 700 char overlap (AG optimal)
    5. Preserve document order for downstream agents

    Args:
        text: Full extracted text of the contract
        document_path: Original file path for metadata
        max_chunk_size: Maximum chunk size in characters (3500 per AG)
        overlap: Overlap between chunks in characters (700 per AG)
    """
    # Find all section boundaries
    boundaries = set()
    boundaries.add(0)
    for pattern in SECTION_PATTERNS:
        for match in re.finditer(pattern, text):
            boundaries.add(match.start())
    boundaries.add(len(text))
    sorted_boundaries = sorted(boundaries)

    # Build chunks respecting section boundaries
    chunks = []
    chunk_start = 0
    chunk_index = 0

    while chunk_start < len(text):
        # Find the best end point: the furthest section boundary
        # within max_chunk_size, or max_chunk_size if no boundary found
        chunk_end = min(chunk_start + max_chunk_size, len(text))

        # Look for the nearest section boundary before chunk_end
        best_boundary = chunk_start
        for b in sorted_boundaries:
            if b <= chunk_end and b > chunk_start:
                best_boundary = b
            elif b > chunk_end:
                break

        # If no good boundary found within range, use max_chunk_size
        if best_boundary == chunk_start:
            actual_end = chunk_end
        else:
            actual_end = best_boundary

        # Ensure minimum chunk size (avoid tiny fragments)
        if actual_end - chunk_start < 200 and actual_end < len(text):
            actual_end = min(chunk_start + max_chunk_size, len(text))

        chunk_text = text[chunk_start:actual_end]

        # Identify section reference
        section_ref = _extract_section_ref(chunk_text)

        chunks.append(TextChunk(
            text=chunk_text,
            start_char=chunk_start,
            end_char=actual_end,
            section_ref=section_ref,
            document_path=document_path,
            chunk_index=chunk_index,
        ))

        # Advance with overlap
        chunk_start = max(actual_end - overlap, chunk_start + 1)
        chunk_index += 1

    return chunks


def _extract_section_ref(text: str) -> str:
    """Extract the section reference from a chunk of text."""
    for pattern in SECTION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return ""
```

### 5.2 Document-Order Preservation

When feeding chunks to agents, the order matches the original document. This avoids the "lost in the middle" problem by ensuring the agent encounters definitions before their usage and general terms before specific exceptions.

### 5.3 Provision-Specific Prompts

Different analysis types receive different prompt sections, following the AG finding that provision-specific prompts significantly improve accuracy. The specialist focus areas in `06-agents.md` Section 4 implement this:

```python
# Agent prompt templates for specific provision types
# These are appended to the base specialist prompt based on
# which clause types are detected in the customer's documents

PROVISION_PROMPTS = {
    "termination": (
        "TERMINATION ANALYSIS CHECKLIST:\n"
        "1. Identify ALL termination triggers (for cause, for convenience, "
        "change of control, insolvency, material breach)\n"
        "2. Note the notice period for each trigger\n"
        "3. Check for termination lock-in periods\n"
        "4. Verify whether termination rights survive assignment\n"
        "5. Compare termination provisions in the MSA vs. any amendments "
        "or order forms that may override them\n"
        "6. Flag any asymmetric termination rights (one party has more "
        "termination triggers than the other)"
    ),
    "pricing": (
        "PRICING ANALYSIS CHECKLIST:\n"
        "1. Extract the base pricing terms and any discount schedules\n"
        "2. Identify MFN (most-favored-nation) clauses\n"
        "3. Check for price escalation or CPI adjustment provisions\n"
        "4. Cross-reference contract pricing against the Pricing Guidelines "
        "reference file (if available)\n"
        "5. Verify whether discounts have been approved per policy\n"
        "6. Calculate the total contract value and compare against ARR data"
    ),
    "change_of_control": (
        "CHANGE OF CONTROL ANALYSIS CHECKLIST:\n"
        "1. Does the contract define 'change of control'? Quote the definition.\n"
        "2. What happens upon a change of control? (consent required, "
        "termination right, automatic assignment, no restriction)\n"
        "3. Does the definition include indirect changes (parent company "
        "acquisition)?\n"
        "4. Is there a cure period or negotiation window?\n"
        "5. Are there financial consequences (termination fees, pricing "
        "adjustments) upon change of control?\n"
        "6. Do any amendments modify the original CoC provision?"
    ),
}
```

### 5.4 Follow-Up Verification Prompts

Per the AG report finding, follow-up prompts that explicitly challenge the agent to find what it may have missed improve accuracy by ~10 percentage points. This is implemented as a second-pass prompt appended after initial analysis:

```python
FOLLOW_UP_VERIFICATION_PROMPT = """
VERIFICATION PASS -- READ THIS CAREFULLY:

You have completed your initial analysis. Before writing output, perform
these verification checks:

1. RE-READ the last 3 files you analyzed. The "lost in the middle" effect
   means you are most likely to have missed information in documents you
   read in the middle of your analysis session.

2. For each customer with ZERO findings, ask yourself: "Is it truly the
   case that this customer's contracts contain no issues, or did I skip
   something?" If you skipped analysis, go back and read the files.

3. For each P0/P1 finding, verify the exact_quote by re-reading the
   source document. Use the verify_citation tool. If the quote is not
   found, CORRECT the finding before writing.

4. Check your governance graph: is every file's governed_by field set to
   a valid value? "UNRESOLVED" must have a corresponding gap.

5. Have you cross-referenced EVERY customer against the reference files
   assigned to you? Customers that appear in reference files but have no
   cross-reference data in your output need attention.

I ACCUSE YOU OF HAVING MISSED INFORMATION in at least one customer's
analysis. Prove me wrong by re-checking, or fix the gaps.
"""
```

### 5.5 Temperature Setting

All agent invocations use temperature 0 for deterministic, reproducible outputs. This is configured in `ClaudeAgentOptions` (see `06-agents.md` Section 3).

---

## 6. Hallucination Prevention Architecture

Specific architectural measures targeting the Stanford-identified failure modes (17-33% hallucination rate in legal AI tools).

Hallucination prevention significantly reduces but does not eliminate fabricated content. The verification protocol catches ~95% of citation fabrications based on retrospective analysis. Remaining risk is mitigated by the Judge agent's spot-check sampling.

### 6.1 Citation Verification Hook

Every finding with an `exact_quote` is verified against the source text before being accepted. This is implemented as the `verify_citation` MCP tool (see `07-tools-and-hooks.md` Section 1.5) and enforced in two places:

1. **Agent self-check**: Agents are instructed to call `verify_citation` before writing each finding
2. **QA audit check**: The citation integrity check (QA 8e in `11-qa-validation.md`) samples at least 10% of findings and verifies quotes against source text

```python
# Citation verification result categories:
# - "verified":       exact substring match (after whitespace normalization)
# - "verified_fuzzy": >90% fuzzy match (accounts for OCR artifacts)
# - "not_found":      quote does not appear in source (hallucination candidate)
# - "source_not_found": extracted text file missing (extraction failure)
```

### 6.2 Dual-Citation Requirement

Cross-document findings (those comparing terms across two or more documents) must cite BOTH documents. A finding claiming "MSA conflicts with Amendment" must include citations from both the MSA and the Amendment. Single-citation cross-document findings are flagged by the Judge.

```python
# src/dd_agents/reasoning/citation_check.py

def validate_cross_document_citations(
    finding: dict,
    reasoning_chain: ReasoningChain | None,
) -> list[str]:
    """Validate that cross-document findings cite all relevant documents.

    Returns list of errors (empty = valid).
    """
    errors = []

    # Detect cross-document findings by keywords in title/description
    cross_doc_indicators = [
        "inconsisten", "conflict", "contradict", "mismatch",
        "differs from", "overrides", "supersedes", "amends",
    ]
    text = (finding.get("title", "") + " " + finding.get("description", "")).lower()
    is_cross_doc = any(indicator in text for indicator in cross_doc_indicators)

    if not is_cross_doc:
        return errors

    # Cross-document findings must have citations from 2+ distinct documents
    citation_sources = set()
    for cit in finding.get("citations", []):
        source = cit.get("source_path", "")
        if source:
            citation_sources.add(source)

    if len(citation_sources) < 2:
        errors.append(
            f"Cross-document finding '{finding.get('title', '')}' "
            f"cites only {len(citation_sources)} document(s). "
            f"Must cite at least 2 documents for cross-document claims."
        )

    # If reasoning chain exists, verify all chain documents are cited
    if reasoning_chain:
        chain_docs = {step.document for step in reasoning_chain.steps}
        uncited = chain_docs - citation_sources
        if uncited:
            errors.append(
                f"Reasoning chain references {len(chain_docs)} documents "
                f"but citations only cover {len(citation_sources)}. "
                f"Missing citations for: {uncited}"
            )

    return errors
```

### 6.3 Deterministic Graph Operations Replace LLM Calls

Where possible, the system uses deterministic computation instead of asking the LLM to reason:

| Task | LLM Approach (unreliable) | Graph Approach (deterministic) |
|------|--------------------------|-------------------------------|
| "Does Amendment #2 modify the MSA?" | Ask the LLM | `nx.has_path(G, "Amendment-2", "MSA")` |
| "Is there a governance cycle?" | Ask the LLM to check | `nx.find_cycle(G)` |
| "Which documents govern this Order Form?" | Ask the LLM to trace | `nx.ancestors(G, "OrderForm")` |
| "Are there conflicting termination clauses?" | Ask the LLM to compare | `detect_contradictions()` (Section 3.5) |
| "What was the effective pricing on date X?" | Ask the LLM to reconstruct | `get_effective_terms_at(doc, date)` (Section 3.4) |

### 6.4 Numerical Audit (5-Layer Validation)

The 5-layer numerical validation framework (`11-qa-validation.md`) catches fabricated numbers:

- **Layer 1**: Every number traces to a source file
- **Layer 2**: Every number is re-derived from source (not trusted from agent output)
- **Layer 3**: Numbers across files agree
- **Layer 4**: Excel cells match manifest values
- **Layer 5**: Numbers are semantically reasonable

### 6.5 Coverage Gate

The coverage gate (pipeline step 17) ensures no customers are skipped. Every customer must have output from all 4 specialist agents. This prevents the failure mode where agents "summarize" multiple customers into a single aggregate file.

### 6.6 Adversarial Follow-Up Prompts

The follow-up verification prompt (Section 5.4) explicitly challenges the agent: "I ACCUSE YOU OF HAVING MISSED INFORMATION." This adversarial framing, per the AG report, forces the model to re-examine its work rather than confidently proceeding with incomplete analysis.

---

## 7. Context Window Management

The system operates within reliable context window limits to avoid the degradation measured at ~64K tokens.

### 7.1 Prompt Size Budget

```python
# src/dd_agents/agents/prompt_builder.py

# Context window budget (from 06-agents.md Section 6.1)
CONTEXT_LIMIT = 200_000     # Claude Sonnet context window
SAFETY_MARGIN = 0.80        # Use at most 80% for prompt (160K tokens)
RELIABLE_THRESHOLD = 80_000  # Prompt ceiling for reliable instruction-following

# Token estimation: ~4 characters per token for English text
CHARS_PER_TOKEN = 4
```

### 7.2 Customer Batching

When a specialist's prompt exceeds `RELIABLE_THRESHOLD` tokens (80K), customers are split into batches. Each batch receives the same rules, reference files, and instructions but a subset of customers. See `06-agents.md` Section 6.2 for the splitting implementation.

### 7.3 Per-Customer Analysis

Agents analyze one customer at a time within their prompt scope. They do not perform bulk analysis across all customers simultaneously. The prompt structure (Section 5.3 of `06-agents.md`) lists all customers but instructs the agent to process each one sequentially, writing the per-customer JSON before moving to the next.

### 7.4 Reference File Routing

Agents only see reference files relevant to their specialist domain (see `06-agents.md` Section 8). The Legal agent does not receive the Pricing Guidelines. The Finance agent does not receive the Compliance Certifications. This reduces prompt size and ensures each agent's context window is not consumed by irrelevant material.

### 7.5 Extracted Text Caching

Agents read pre-extracted markdown text (`_dd/forensic-dd/index/text/*.md`), not raw PDFs. This is smaller (no base64 encoding overhead), faster (no runtime extraction), and deterministic (same text on every read). See `08-extraction.md` for the extraction pipeline.

### 7.6 Progressive Summarization

For very large customer portfolios (>200 customers, >500 documents), the system applies progressive summarization:

1. **First pass**: Full analysis of each customer's documents
2. **Summary extraction**: Key findings are summarized to ~500 tokens per customer
3. **Cross-customer comparison**: The summary set (200 customers x 500 tokens = 100K tokens) is used for cross-customer pattern detection
4. **Detail retrieval**: When patterns are found, the full findings for affected customers are loaded on demand

This keeps every agent invocation within the 80K-token reliable-instruction-following window.

---

## 8. Error Compounding Mitigation

The system prevents the agentic 10%-per-step cascade identified in Section 1.3 through five structural measures.

### 8.1 Deterministic Python Gates

Every gate between pipeline steps is a Python `if/else` statement, not an LLM decision. The 5 blocking gates (steps 5, 17, 27, 28, 31) are implemented as Python functions that count files, validate schemas, and compare numbers. The LLM has no influence on whether a gate passes or fails.

```python
# Example: Coverage gate (step 17) -- from 05-orchestrator.md
async def step_17_coverage_gate(state: PipelineState) -> PipelineState:
    """BLOCKING GATE: Every customer must have output from all 4 agents."""
    missing = []
    for customer in state.customer_safe_names:
        for agent in ["legal", "finance", "commercial", "producttech"]:
            path = state.run_dir / "findings" / agent / f"{customer}.json"
            if not path.exists():
                missing.append({"customer": customer, "agent": agent})

    if missing:
        raise BlockingGateError(
            f"Coverage gate failed: {len(missing)} missing outputs. "
            f"First 5: {missing[:5]}"
        )
    return state
```

### 8.2 Independent Validation at Each Gate

Each gate validates independently of prior steps. The numerical audit (step 27) re-derives every number from source files -- it does not trust the numbers produced by the Reporting Lead. The QA audit (step 28) re-reads agent outputs from disk -- it does not trust in-memory state.

### 8.3 Judge as Independent Verifier

The Judge agent (pipeline steps 19-22) is an independent reviewer, not a rubber stamp. It:

- Reads source documents directly (not summaries)
- Verifies citations against extracted text (not against the finding's claim)
- Scores each agent on 5 dimensions independently (not relative to other agents)
- Can trigger re-analysis of failing agents (Section 10.7 of `06-agents.md`)

The Judge is a different agent invocation than the specialists. It does not review its own prior work.

### 8.4 Per-Finding Citation Verification

The `verify_citation` tool (`07-tools-and-hooks.md` Section 1.5) performs exact substring matching against pre-extracted text. It does not ask the LLM "does this quote exist?" -- it performs a deterministic string search. This eliminates the circular validation problem where an LLM confirms its own fabrication.

### 8.5 Re-Analysis Loop

When the Judge scores an agent below threshold, the orchestrator triggers a targeted re-analysis (Section 10.7 of `06-agents.md`). The re-analysis prompt:

1. Includes only the failing customers (not all customers)
2. Includes specific feedback from the Judge's spot-check results
3. Instructs the agent to overwrite its previous output for those customers only
4. Is followed by a second Judge review round

This pattern limits the blast radius of errors: only the identified problems are re-processed, not the entire pipeline.

---

## 9. Implementation Integration

How the ontology, reasoning, and explainability components integrate with existing plan files.

### 9.1 Pipeline Steps Enhanced

| Pipeline Step | Enhancement | Details |
|--------------|-------------|---------|
| 5 (Bulk Extraction) | Clause-aware chunking | Apply `chunk_contract_text()` during extraction for ChromaDB indexing |
| 14 (Prepare Prompts) | Provision-specific prompts | Append `PROVISION_PROMPTS` based on detected document types |
| 14 (Prepare Prompts) | Follow-up verification prompt | Append `FOLLOW_UP_VERIFICATION_PROMPT` to all specialist prompts |
| 16 (Spawn Specialists) | Reasoning chain generation | Agents produce `reasoning_chain` in finding output |
| 17 (Coverage Gate) | No change | Existing gate already validates per-customer output |
| 19-22 (Judge) | Chain validation | Judge validates reasoning chains as part of spot-checks |
| 24 (Merge/Dedup) | Chain preservation | Reasoning chains carried through merge into final findings |
| 27 (Numerical Audit) | No change | Existing 5-layer validation already prevents fabricated numbers |
| 28 (QA Audit) | Cross-document citation check | Add `validate_cross_document_citations()` to QA checks |
| 30 (Excel Generation) | Reasoning column | Add Reasoning_Summary and Reasoning_Chain columns |

### 9.2 Pydantic Models Extended

From `04-data-models.md`:

| Existing Model | Extension | New Fields |
|---------------|-----------|------------|
| `GovernanceEdge` | Extended by `OntologyEdge` | `relationship` typed as `RelationshipType`, citation fields |
| `GovernanceGraph` | Wrapped by `ContractReasoningGraph` | All graph query methods (Sections 3.2-3.6) |
| `AgentFinding` | Extended with reasoning chain | `reasoning_chain: ReasoningChain | None = None` |
| `Finding` | Extended with reasoning chain | `reasoning_chain: ReasoningChain | None = None` |
| `FileHeader` | Extended with `doc_type` typing | `doc_type_guess` validated against `DocumentType` enum |

### 9.3 Agent Prompts Modified

From `06-agents.md`:

| Agent | Prompt Modification | Source Section |
|-------|-------------------|----------------|
| All specialists | Add `FOLLOW_UP_VERIFICATION_PROMPT` | Section 5.4 |
| All specialists | Add provision-specific checklists | Section 5.3 |
| Legal | Add ontology vocabulary for governance relationships | Section 2.3 |
| Legal | Add reasoning chain generation instructions | Section 4.1 |
| Judge | Add reasoning chain validation rules | Section 4.5 |
| Reporting Lead | Add reasoning chain preservation during merge | Section 9.1 |

### 9.4 QA Checks Added

From `11-qa-validation.md`:

| New Check | DoD Integration | Blocking? |
|-----------|----------------|-----------|
| Cross-document citation validation | Add to DoD check 5 (citation integrity) | Yes |
| Reasoning chain traversability | Add to DoD check 4 (governance completeness) | No (warning) |
| Reasoning chain quote verification | Add to DoD check 5 (citation integrity) | Yes (for P0/P1) |

### 9.5 Dependency on 20-cross-document-analysis.md

The cross-document analysis module (Document 20) consumes the ontology graph built by this module. Specifically:

- `ContractReasoningGraph.detect_contradictions()` feeds cross-document contradiction findings
- `ContractReasoningGraph.get_amendment_chain()` feeds amendment chain analysis
- `ContractReasoningGraph.analyze_change_of_control_impact()` feeds the Change-of-Control risk report
- Reasoning chains are the primary output format for cross-document findings

---

## 10. Verification Protocol

Every finding passes through a 4-tier verification protocol before reaching the final report. Each tier operates independently; a finding must pass all applicable tiers.

The verification protocol defined here should be checked as part of the QA audit (see `11-qa-validation.md`). Specifically, DoD check for citation verification should invoke `reasoning/verification.py` to validate that cited clauses exist in the source documents.

### Tier 1: Deterministic Checks

Python functions that verify structural correctness. No LLM involvement.

| Check | Implementation | Failure Action |
|-------|---------------|----------------|
| Citation file exists | `source_path in files.txt` | Reject finding |
| Dates are valid | `datetime.strptime(date, "%Y-%m-%d")` | Flag for review |
| Numbers add up | Layer 2 re-derivation | Auto-correct |
| Finding schema valid | `AgentFinding.model_validate()` | Reject and re-spawn |
| Quote non-empty for P0/P1 | `len(exact_quote) > 0` | Block agent stop |

```python
# src/dd_agents/reasoning/verification.py

class Tier1Verifier:
    """Deterministic structural checks. No LLM calls."""

    def verify(self, finding: dict, files_txt: set[str]) -> list[str]:
        errors = []

        # Citation file exists
        for cit in finding.get("citations", []):
            if cit.get("source_path") and cit["source_path"] not in files_txt:
                errors.append(f"Citation file not found: {cit['source_path']}")

        # Quote non-empty for P0/P1
        severity = finding.get("severity", "")
        if severity in ("P0", "P1"):
            for cit in finding.get("citations", []):
                if not cit.get("exact_quote"):
                    errors.append(f"{severity} finding missing exact_quote")

        # Dates valid
        for date_field in ["effective_date_guess", "expiry_date_guess"]:
            date_val = finding.get("metadata", {}).get(date_field, "")
            if date_val:
                try:
                    from datetime import datetime
                    datetime.strptime(date_val, "%Y-%m-%d")
                except ValueError:
                    errors.append(f"Invalid date in {date_field}: {date_val}")

        return errors
```

### Tier 2: Graph-Based Checks

Reasoning chain traversability and graph integrity. Deterministic via NetworkX.

| Check | Implementation | Failure Action |
|-------|---------------|----------------|
| Chain traversable | All chain documents exist in customer files | Flag finding |
| No broken links | Every edge target exists as a node | Flag governance gap |
| Amendment chain valid | `get_amendment_chain()` returns non-empty | Warning if empty |
| No governance cycles | `nx.find_cycle()` raises NoCycle | Flag contradiction |

```python
class Tier2Verifier:
    """Graph-based reasoning chain verification."""

    def __init__(self, graph: ContractReasoningGraph):
        self.graph = graph

    def verify(self, chain: ReasoningChain | None) -> list[str]:
        errors = []

        if chain is None:
            return errors  # Chain is optional for simple findings

        # All chain documents exist in graph
        for step in chain.steps:
            doc_nodes = [
                n for n in self.graph.G.nodes
                if self.graph.G.nodes[n].get("file_path") == step.document
            ]
            if not doc_nodes:
                errors.append(
                    f"Chain step {step.step_number}: document "
                    f"'{step.document}' not in contract graph"
                )

        # Graph has no cycles
        try:
            cycle = nx.find_cycle(self.graph.G, orientation="original")
            errors.append(f"Governance cycle detected: {cycle}")
        except nx.NetworkXNoCycle:
            pass

        # All edge targets exist as nodes
        for u, v in self.graph.G.edges():
            if v not in self.graph.G:
                errors.append(f"Broken edge: {u} -> {v} (target not in graph)")

        return errors
```

### Tier 3: LLM-Assisted Review

The Judge agent spot-checks findings per the sampling protocol (`06-agents.md` Section 10.3). This is the only tier that uses LLM reasoning, and it operates on a sample -- not all findings.

| Finding Severity | Sample Rate | What Judge Checks |
|-----------------|-------------|-------------------|
| P0 | 100% | All 5 spot-check dimensions |
| P1 | 20% | Citation verification + contextual validation |
| P2 | 10% | Citation verification |
| P3 | 0% | Not reviewed (enforced by manifest audit) |

The Judge is a separate agent invocation from the specialists. It reads source documents independently and does not have access to the specialist's reasoning -- only the specialist's output. This prevents confirmation bias.

### Tier 4: Human Review

Flagged items for lawyer attention. The system does not replace human judgment -- it surfaces items that require it.

| Flag Condition | Report Indicator | Action Required |
|---------------|-----------------|-----------------|
| P0 finding | Red highlight in Wolf_Pack sheet | Lawyer must verify |
| Judge score < threshold | Quality caveat in metadata | Lawyer must review scope |
| Unresolved contradiction | Contradiction section in report | Lawyer must adjudicate |
| Reasoning chain invalid | Chain_Valid = false in findings | Lawyer must trace manually |
| Fuzzy-match citation | "verified_fuzzy" flag | Lawyer should confirm quote |

```python
class Tier4Flagger:
    """Flag findings that require human review."""

    def flag(
        self,
        finding: dict,
        chain: ReasoningChain | None,
        judge_result: dict | None,
    ) -> list[str]:
        flags = []

        # P0 always flagged
        if finding.get("severity") == "P0":
            flags.append("P0_REQUIRES_LAWYER_REVIEW")

        # Invalid reasoning chain
        if chain and not chain.chain_valid:
            flags.append("INVALID_REASONING_CHAIN")

        # Judge scored finding as FAIL
        if judge_result and judge_result.get("result") == "FAIL":
            flags.append(f"JUDGE_FAIL: {judge_result.get('notes', '')}")

        # Fuzzy-match citation (not exact match)
        for cit in finding.get("citations", []):
            if cit.get("verification_result", "").startswith("verified_fuzzy"):
                flags.append("FUZZY_CITATION_MATCH")

        return flags
```

### Verification Pipeline Summary

```
Finding produced by specialist agent
         |
    [Tier 1] Deterministic checks (schema, citations, dates)
         |  FAIL -> reject finding, re-spawn agent
         |
    [Tier 2] Graph checks (chain traversable, no cycles)
         |  FAIL -> flag finding, add to QA report
         |
    [Tier 3] Judge spot-check (sampled per severity)
         |  FAIL -> trigger re-analysis, re-spawn specialist
         |
    [Tier 4] Flag for human review (P0, contradictions)
         |
    Finding included in final Excel report
    with chain_valid status and review flags
```

This 4-tier protocol ensures that:
- 100% of findings pass structural validation (Tier 1)
- 100% of findings with reasoning chains are graph-verified (Tier 2)
- 100% of P0 findings and a meaningful sample of P1/P2 findings are independently reviewed (Tier 3)
- All findings requiring human judgment are clearly flagged (Tier 4)
