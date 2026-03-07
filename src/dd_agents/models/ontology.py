"""Contract ontology models for knowledge graph reasoning (Issue #152).

Defines the typed vocabulary for contract documents, clause types,
obligation tracking, and relationship reasoning. Built on NetworkX
for graph operations.

Spec: docs/plan/21-ontology-and-reasoning.md
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    """Contract document types."""

    MSA = "MSA"
    ORDER_FORM = "OrderForm"
    AMENDMENT = "Amendment"
    SIDE_LETTER = "SideLetter"
    SOW = "SOW"
    NDA = "NDA"
    DPA = "DPA"
    SLA = "SLA"
    PURCHASE_ORDER = "PurchaseOrder"
    RENEWAL_AGREEMENT = "RenewalAgreement"
    ASSIGNMENT_AGREEMENT = "AssignmentAgreement"
    TERMINATION_NOTICE = "TerminationNotice"
    UNKNOWN = "Unknown"


class ClauseType(StrEnum):
    """Types of contract clauses."""

    OBLIGATION = "obligation"
    RIGHT = "right"
    CONDITION = "condition"
    DEFINITION = "definition"
    REMEDY = "remedy"
    LIMITATION = "limitation"
    TERMINATION = "termination"
    INDEMNIFICATION = "indemnification"
    CONFIDENTIALITY = "confidentiality"
    IP_ASSIGNMENT = "ip_assignment"
    CHANGE_OF_CONTROL = "change_of_control"
    GOVERNING_LAW = "governing_law"
    FORCE_MAJEURE = "force_majeure"
    WARRANTY = "warranty"
    UNKNOWN = "unknown"


class RelationshipType(StrEnum):
    """Relationship types between documents/clauses."""

    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"
    CONDITIONS = "conditions"
    INCORPORATES = "incorporates"
    CONFLICTS_WITH = "conflicts_with"
    PARENT_OF = "parent_of"
    CHILD_OF = "child_of"


class PartyRole(StrEnum):
    """Roles parties play in contractual obligations."""

    OBLIGOR = "obligor"
    OBLIGEE = "obligee"
    GUARANTOR = "guarantor"
    BENEFICIARY = "beneficiary"
    LICENSOR = "licensor"
    LICENSEE = "licensee"


class ClauseNode(BaseModel):
    """A contract clause as a node in the knowledge graph."""

    id: str = Field(description="Unique clause ID (file_path:section:clause_type)")
    document_path: str = Field(description="Source document path")
    customer_safe_name: str = Field(default="")
    clause_type: ClauseType = Field(default=ClauseType.UNKNOWN)
    section_ref: str = Field(default="", description="Section reference in the document")
    summary: str = Field(default="", description="Brief clause summary")
    exact_quote: str = Field(default="", description="Exact text from document")
    effective_date: str = Field(default="", description="When clause takes effect (YYYY-MM-DD)")
    expiry_date: str = Field(default="", description="When clause expires (YYYY-MM-DD)")
    notice_period_days: int | None = Field(default=None, description="Notice period in days")
    parties: list[PartyInfo] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class PartyInfo(BaseModel):
    """Party information for an obligation or right."""

    name: str = Field(description="Party name")
    role: PartyRole = Field(description="Role in the clause")


# Fix forward reference
ClauseNode.model_rebuild()


class DocumentRelationship(BaseModel):
    """A relationship edge between two documents or clauses."""

    source_id: str = Field(description="Source node ID")
    target_id: str = Field(description="Target node ID")
    relationship: RelationshipType = Field(description="Type of relationship")
    description: str = Field(default="", description="Description of the relationship")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Obligation(BaseModel):
    """A tracked obligation from a contract."""

    id: str = Field(description="Unique obligation ID")
    clause_id: str = Field(description="Source clause ID")
    customer_safe_name: str = Field(default="")
    obligor: str = Field(description="Who owes the obligation")
    obligee: str = Field(description="Who is owed")
    description: str = Field(description="What is required")
    due_date: str = Field(default="", description="When it's due (YYYY-MM-DD)")
    recurring: bool = Field(default=False, description="Whether this is a recurring obligation")
    status: str = Field(default="active", description="active | fulfilled | breached | waived")


class OntologyGraph(BaseModel):
    """Serializable representation of the contract knowledge graph."""

    clauses: list[ClauseNode] = Field(default_factory=list)
    relationships: list[DocumentRelationship] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    total_documents: int = Field(default=0)
    total_clauses: int = Field(default=0)
    total_relationships: int = Field(default=0)
