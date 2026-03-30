# 20 -- Cross-Document Analysis

How the DD system analyzes relationships between contracts, detects overrides, contradictions, and missing documents, and maintains a governance graph that ensures no legal relationship is lost or misrepresented. Cross-document analysis is the core differentiator between naive per-file extraction and forensic-grade due diligence.

Cross-references: `04-data-models.md` (GovernanceEdge, Finding, Citation, Gap, GapType, GovernanceRelationship), `05-orchestrator.md` (pipeline steps 7-11, 17, 24-25), `06-agents.md` (specialist focus areas, Judge protocol), `07-tools-and-hooks.md` (check_governance tool, verify_citation hook), `09-entity-resolution.md` (customer name normalization), `10-reporting.md` (merge/dedup, Excel sheets), `11-qa-validation.md` (governance validation, cross-reference checks), `21-ontology-and-reasoning.md` (ontology schema, graph reasoning, document type taxonomy).

---

## 1. Why Cross-Document Analysis Is Essential

### 1.1 The Isolation Failure Mode

Analyzing contracts in isolation -- treating each file as an independent document -- produces structurally incomplete due diligence. In M&A, contracts form networks of legal relationships. An MSA governs multiple Order Forms. Amendments modify specific clauses in the MSA. Side Letters create exceptions. Renewal Agreements supersede prior terms while inheriting unchanged ones.

When an analyst (human or AI) reads a single Order Form without understanding that Amendment No. 3 to the governing MSA changed the liability cap from $5M to unlimited, the entire financial risk assessment for that customer is wrong. This is not an edge case -- it is the standard operating pattern for enterprise SaaS contracts.

### 1.2 Failure Modes from Isolated Analysis

| Failure Mode | Example | Consequence |
|-------------|---------|-------------|
| **Missed override** | Amendment changes payment terms from Net-30 to Net-60; analyst reads the MSA and reports Net-30 | Incorrect financial modeling; cash flow projection wrong by 30 days per customer |
| **Phantom provision** | MSA contains auto-renewal clause; Amendment explicitly removes it; analyst reports auto-renewal exists | Buyer assumes recurring revenue protection that does not exist |
| **Orphaned addendum** | Order Form references MSA-2023-001 which is not in the data room | Cannot determine governance chain; unknown liability exposure |
| **Superseded terms** | Renewal Agreement replaces pricing schedule; analyst reports old pricing from original contract | Incorrect revenue projections; potential purchase price miscalculation |
| **Undetected contradiction** | MSA says governing law is New York; Order Form says Delaware | Legal uncertainty; potential enforceability issues |
| **Missing amendment chain** | "Amendment No. 3" exists but Amendments 1 and 2 are absent | Unknown modifications to the base contract; gap in legal history |

### 1.3 Scale in This System

The system operates at the following typical scale:

- ~200 customers in a data room
- ~400 documents total (~2 documents per customer average, range 1-20)
- ~600-1,000 governance edges across all customers (~3-5 per customer)
- 13 document types recognized (see `21-ontology-and-reasoning.md` Section 2.1)
- 4 governance relationship types: governs, amends, supersedes, references

Cross-document analysis touches every customer. It is not an optional enhancement -- it is the primary mechanism by which the system ensures legal accuracy.

---

## 2. Contract Hierarchy and Governance

### 2.1 Document Precedence Model

Enterprise SaaS contracts follow a hierarchical structure where each document type has a defined position in the governance chain:

```
Level 0: MSA (Master Service Agreement)
    |
    +-- Level 1: Order Forms / Purchase Orders
    |       |
    |       +-- Level 2: SOWs (Statements of Work)
    |
    +-- Level 1: Amendments (modify MSA clauses)
    |       |
    |       +-- Level 2: Amendments to Amendments (rare but valid)
    |
    +-- Level 1: Side Letters (informal modifications)
    |
    +-- Level 1: DPA (Data Processing Agreement)
    |
    +-- Level 1: SLA (Service Level Agreement)
    |
    +-- Level 1: NDA (Non-Disclosure Agreement, often predates MSA)

Parallel: Renewal Agreements (supersede the prior term's MSA)
Parallel: Assignment Agreements (transfer rights between parties)
Parallel: Termination Notices (end specific agreements)
```

### 2.2 Governance Relationship Types

Four relationship types encode how documents connect:

```python
# From src/dd_agents/models/finding.py (already defined in 04-data-models.md)

class GovernanceRelationship(str, Enum):
    GOVERNS = "governs"         # MSA governs Order Form
    AMENDS = "amends"           # Amendment modifies MSA
    SUPERSEDES = "supersedes"   # Renewal replaces prior MSA
    REFERENCES = "references"   # Document cites another document
```

**Relationship semantics**:

| Relationship | Direction | Legal Effect |
|-------------|-----------|-------------|
| `governs` | Parent → Child | Child operates under Parent's terms. Parent's clauses apply to Child unless Child explicitly overrides. |
| `amends` | Amendment → Target | Amendment modifies specific clauses in Target. Unmodified clauses remain in effect. |
| `supersedes` | New → Old | New document replaces Old entirely. Old document is no longer active (but remains in the record). |
| `references` | Referrer → Referenced | Informational link. Referrer mentions Referenced but does not modify it. Used for cross-reference validation. |

### 2.3 Governance Graph Construction

The governance graph is built per-customer as a NetworkX DiGraph during pipeline step 7 (ENTITY_RESOLUTION) and enriched during specialist analysis (step 16). The graph is validated at step 17 (COVERAGE_GATE).

```python
import networkx as nx
from dd_agents.models.finding import GovernanceRelationship

def build_governance_graph(
    customer_safe_name: str,
    edges: list[dict],
) -> nx.DiGraph:
    """Build a per-customer governance graph from agent-detected relationships.

    Args:
        customer_safe_name: Normalized customer name.
        edges: List of dicts with keys: source, target, relation, evidence.
            source/target are filenames.
            relation is a GovernanceRelationship value.
            evidence is the text excerpt proving the relationship.
    """
    G = nx.DiGraph(customer=customer_safe_name)

    for edge in edges:
        G.add_edge(
            edge["source"],
            edge["target"],
            relation=GovernanceRelationship(edge["relation"]),
            evidence=edge["evidence"],
            confidence=edge.get("confidence", "high"),
        )

    return G


def validate_governance_graph(G: nx.DiGraph) -> list[dict]:
    """Validate a governance graph. Returns list of issues found."""
    issues = []

    # 1. Cycle detection -- governance must be a DAG
    try:
        cycle = nx.find_cycle(G, orientation="original")
        issues.append({
            "type": "circular_governance",
            "severity": "P0",
            "detail": f"Circular governance detected: {cycle}",
            "cycle_edges": [(u, v) for u, v, _ in cycle],
        })
    except nx.NetworkXNoCycle:
        pass  # Expected: no cycles

    # 2. Isolate detection -- documents with no governance link
    isolates = list(nx.isolates(G))
    for node in isolates:
        issues.append({
            "type": "ungoverned_document",
            "severity": "P2",
            "detail": f"Document '{node}' has no governance relationship to any other document",
            "file": node,
        })

    # 3. Multi-root detection -- more than one root MSA per customer is unusual
    roots = [n for n in G.nodes() if G.in_degree(n) == 0 and G.out_degree(n) > 0]
    if len(roots) > 1:
        issues.append({
            "type": "multiple_governance_roots",
            "severity": "P1",
            "detail": f"Customer has {len(roots)} root documents: {roots}. Expected one MSA as root.",
            "roots": roots,
        })

    # 4. Multi-parent detection -- a document governed by two MSAs
    for node in G.nodes():
        parents = list(G.predecessors(node))
        governing_parents = [
            p for p in parents
            if G.edges[p, node].get("relation") == GovernanceRelationship.GOVERNS
        ]
        if len(governing_parents) > 1:
            issues.append({
                "type": "multi_parent_governance",
                "severity": "P1",
                "detail": f"Document '{node}' is governed by multiple parents: {governing_parents}",
                "file": node,
                "parents": governing_parents,
            })

    return issues
```

### 2.4 Root Document Identification

Every customer should have exactly one root document (typically the MSA). The root is identified by:

1. **Explicit MSA**: A document classified as `DocumentType.MSA` with `out_degree > 0`
2. **Implicit MSA**: If no explicit MSA exists, the oldest contract with the broadest scope (most governance edges out) serves as the root, annotated with `governed_by: "SELF"`
3. **No root**: If the customer has only standalone documents with no governance links, each is treated as independent. This triggers a `Missing_Doc` gap for the expected MSA.

```python
def find_root_document(G: nx.DiGraph) -> str | None:
    """Find the root (MSA) of a governance graph.

    Returns the filename of the root document, or None if no clear root exists.
    """
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]

    if len(roots) == 1:
        return roots[0]

    if len(roots) == 0:
        # All nodes have predecessors -- implies a cycle (caught by validate_governance_graph)
        return None

    # Multiple roots: prefer the one with the most descendants
    root_scores = {
        root: len(nx.descendants(G, root))
        for root in roots
    }
    return max(root_scores, key=root_scores.get)
```

### 2.5 Orphaned Document Detection

A document is **orphaned** when it references a parent that does not exist in the data room:

- Order Form references "MSA dated January 15, 2024" but no such MSA is in the data room
- Amendment references "Agreement No. SVC-2023-001" which is absent
- SOW states "pursuant to the Master Service Agreement between [parties]" but no MSA is found

Orphaned documents are flagged as `GapType.MISSING_DOC` gaps with `DetectionMethod.CROSS_REFERENCE`. These are always at least P1 severity because the missing document may contain terms that materially affect the analysis.

```python
from dd_agents.models.finding import GapType, DetectionMethod, Severity

def detect_orphaned_documents(
    G: nx.DiGraph,
    referenced_but_absent: list[dict],
) -> list[dict]:
    """Detect documents that reference parents not in the data room.

    Args:
        G: Governance graph (contains only documents IN the data room).
        referenced_but_absent: List of dicts with keys: referencing_file,
            referenced_description, reference_text.
    """
    gaps = []
    for ref in referenced_but_absent:
        gaps.append({
            "gap_type": GapType.MISSING_DOC,
            "detection_method": DetectionMethod.CROSS_REFERENCE,
            "severity": Severity.P1,
            "title": f"Missing referenced document: {ref['referenced_description']}",
            "detail": (
                f"Document '{ref['referencing_file']}' references "
                f"'{ref['referenced_description']}' which is not in the data room."
            ),
            "evidence": ref["reference_text"],
            "referencing_file": ref["referencing_file"],
            "recommendation": (
                "Request the missing document from the seller. "
                "Without it, the governance chain for this customer is incomplete."
            ),
        })
    return gaps
```

---

## 3. Override and Supersession Detection

### 3.1 Override Categories

Overrides occur when a later or more specific document changes terms established in an earlier or more general document. There are five categories:

| Category | Trigger Language | Legal Effect | Example |
|----------|-----------------|-------------|---------|
| **Amendment override** | "Section X is hereby amended to read...", "The following replaces Section X..." | Specific clause replaced. All other clauses remain. | Amendment No. 2 changes liability cap from $5M to unlimited |
| **Order Form override** | "Notwithstanding anything to the contrary in the MSA...", "The terms of this Order Form shall prevail..." | Order Form terms take precedence over MSA for the scope of the Order Form | Order Form specifies Net-60 payment overriding MSA's Net-30 |
| **Renewal supersession** | "This Agreement replaces and supersedes the prior Agreement...", "Effective as of the Renewal Date, the prior terms shall be..." | Entire prior agreement replaced. Unchanged terms may be carried forward explicitly or by reference. | 2025 Renewal Agreement replaces 2022 MSA |
| **Side letter modification** | "The parties agree to the following modification...", "By way of this letter..." | Informal but binding modification. May not reference specific sections. | Side letter waiving exclusivity requirement for Q4 2024 |
| **Termination override** | "This Agreement is terminated effective...", "The parties agree to terminate..." | All provisions cease except survival clauses. | Termination Notice ending service as of March 31, 2025 |

### 3.2 Override Detection Data Model

```python
# src/dd_agents/models/cross_document.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import date
from dd_agents.models.finding import Severity, Confidence


class Override(BaseModel):
    """An override relationship between two documents."""
    model_config = ConfigDict(populate_by_name=True)

    overriding_file: str = Field(description="File that contains the override language")
    overridden_file: str = Field(description="File whose terms are being overridden")
    category: str = Field(description="One of: amendment, order_form, renewal, side_letter, termination")
    clause_reference: Optional[str] = Field(
        default=None,
        description="Specific clause being overridden (e.g., 'Section 5.2 Liability')",
    )
    original_term: Optional[str] = Field(
        default=None,
        description="The original provision text (from overridden document)",
    )
    new_term: Optional[str] = Field(
        default=None,
        description="The replacement provision text (from overriding document)",
    )
    effective_date: Optional[date] = Field(
        default=None,
        description="Date the override takes effect",
    )
    override_evidence: str = Field(
        description="Exact quote from the overriding document proving the override",
    )
    severity: Severity = Field(
        description="Impact severity: P0 for financial/liability changes, P1 for scope, P2 for administrative",
    )
    confidence: Confidence = Field(default=Confidence.HIGH)


class SupersessionChain(BaseModel):
    """A chain of documents where each supersedes the previous."""
    model_config = ConfigDict(populate_by_name=True)

    customer_safe_name: str
    chain: list[str] = Field(
        description="Ordered list of filenames from oldest to newest. Each supersedes the previous.",
    )
    current_active: str = Field(description="The currently active (most recent) document in the chain")
    gaps_in_chain: list[str] = Field(
        default_factory=list,
        description="Expected but missing documents in the supersession sequence",
    )
    carried_forward_clauses: list[str] = Field(
        default_factory=list,
        description="Clauses explicitly carried forward from prior versions",
    )
    renegotiated_clauses: list[str] = Field(
        default_factory=list,
        description="Clauses that changed between versions",
    )
```

### 3.3 Temporal Logic

The system must determine which version of a clause is "current" as of the analysis date. Rules:

1. **Effective date ordering**: Amendments take effect on their stated effective date, not their signing date.
2. **Latest-wins for same clause**: If two Amendments modify the same clause, the one with the later effective date prevails.
3. **Sunset clauses**: A provision that expires on a specific date is no longer current after that date, even if no explicit override exists.
4. **Retroactive amendments**: Rare but valid. An Amendment effective January 1, 2024 signed on March 15, 2024 applies retroactively.
5. **Auto-renewal interaction**: If an MSA auto-renewed and a subsequent Amendment modifies the original term, the Amendment applies to the renewed term unless it states otherwise.

```python
from datetime import date


def determine_current_clause(
    overrides: list[Override],
    analysis_date: date | None = None,
) -> Override | None:
    """Given a list of overrides affecting the same clause, determine which is current.

    Returns the override that represents the currently active version,
    or None if the original clause is still in effect (no applicable override).
    """
    if analysis_date is None:
        analysis_date = date.today()

    # Filter to overrides with effective dates on or before analysis date
    applicable = [
        o for o in overrides
        if o.effective_date is None or o.effective_date <= analysis_date
    ]

    if not applicable:
        return None

    # Sort by effective date descending; most recent wins
    applicable.sort(
        key=lambda o: o.effective_date or date.min,
        reverse=True,
    )

    return applicable[0]
```

### 3.4 Conflict Detection Between Overrides

When two documents override the same clause differently (e.g., Amendment No. 2 says liability cap is $10M, Order Form addendum says $5M), this is a **contradiction** -- not a valid override chain. The system detects this by:

1. Building a map of clause → list of overrides
2. For each clause with multiple overrides, checking whether a single precedence chain can be established
3. If not (e.g., an Amendment and an Order Form both modify the same clause with different effective dates), flagging as `GapType.CONTRADICTION`

---

## 4. Cross-Reference Reconciliation

### 4.1 What Cross-References Look Like

Contracts routinely reference other documents. Common patterns:

| Pattern | Example Text | Extraction Rule |
|---------|-------------|----------------|
| **Named reference** | "as defined in the Master Service Agreement dated January 15, 2024" | Extract document type + date |
| **Section reference** | "pursuant to Section 3.2 of the Order Form" | Extract document type + section number |
| **Agreement number** | "under Agreement No. SVC-2023-001" | Extract agreement identifier |
| **Exhibit reference** | "as set forth in Exhibit A hereto" | Extract exhibit label; check if exhibit is a separate file or embedded |
| **Renewal reference** | "this Agreement renews and replaces the Agreement dated March 1, 2022" | Extract prior agreement date; mark supersession relationship |
| **Amendment reference** | "This Amendment No. 3 to the Master Service Agreement" | Extract amendment number; implies Amendments 1-2 should exist |

### 4.2 Cross-Reference Integrity Model

```python
# src/dd_agents/models/cross_document.py (continued)

class CrossReference(BaseModel):
    """A reference from one document to another."""
    model_config = ConfigDict(populate_by_name=True)

    source_file: str = Field(description="File containing the reference")
    reference_text: str = Field(description="Exact quote containing the reference")
    referenced_document_type: Optional[str] = Field(
        default=None,
        description="Inferred document type of the referenced document",
    )
    referenced_identifier: Optional[str] = Field(
        default=None,
        description="Agreement number, date, or other identifier of the referenced document",
    )
    resolved_to: Optional[str] = Field(
        default=None,
        description="Filename in the data room that this reference resolves to. None if unresolved.",
    )
    resolution_confidence: Confidence = Field(default=Confidence.HIGH)
    is_resolved: bool = Field(
        default=False,
        description="True if the referenced document was found in the data room",
    )


class CrossReferenceIntegrity(BaseModel):
    """Cross-reference integrity summary for a customer."""
    model_config = ConfigDict(populate_by_name=True)

    customer_safe_name: str
    total_references: int = Field(description="Total cross-references detected")
    resolved_references: int = Field(description="References resolved to a file in the data room")
    unresolved_references: int = Field(description="References to documents not in the data room")
    integrity_score: float = Field(
        description="resolved / total. 1.0 = all references resolved.",
        ge=0.0,
        le=1.0,
    )
    unresolved_details: list[CrossReference] = Field(
        default_factory=list,
        description="Details of each unresolved cross-reference",
    )
```

### 4.3 Cross-Reference Resolution Algorithm

For each cross-reference extracted by an agent:

1. **Exact match**: Search the data room for a file whose name or metadata matches the referenced identifier (agreement number, date + type).
2. **Fuzzy match**: If no exact match, use the entity resolution system (`09-entity-resolution.md`) to check for name variations, OCR-mangled identifiers, or alternative file naming conventions.
3. **Contextual match**: If the reference says "the MSA" without a specific identifier, and the customer has exactly one MSA in the data room, resolve to that MSA with `confidence: "medium"`.
4. **Unresolved**: If no match is found, the reference becomes an unresolved cross-reference, triggering a `GapType.MISSING_DOC` gap finding.

```python
def resolve_cross_references(
    references: list[CrossReference],
    data_room_files: dict[str, dict],  # filename -> metadata
    entity_matcher,  # EntityMatcher from entity_resolution
) -> list[CrossReference]:
    """Attempt to resolve each cross-reference to a file in the data room.

    Returns updated list with resolved_to and is_resolved fields populated.
    """
    resolved = []
    for ref in references:
        updated = ref.model_copy()

        # Pass 1: Exact identifier match
        if ref.referenced_identifier:
            for filename, meta in data_room_files.items():
                if ref.referenced_identifier.lower() in filename.lower():
                    updated.resolved_to = filename
                    updated.is_resolved = True
                    updated.resolution_confidence = Confidence.HIGH
                    break

        # Pass 2: Date + type match
        if not updated.is_resolved and ref.referenced_document_type:
            candidates = [
                f for f, m in data_room_files.items()
                if m.get("doc_type", "").lower() == ref.referenced_document_type.lower()
            ]
            if len(candidates) == 1:
                updated.resolved_to = candidates[0]
                updated.is_resolved = True
                updated.resolution_confidence = Confidence.MEDIUM

        # Pass 3: Fuzzy match on identifier
        if not updated.is_resolved and ref.referenced_identifier:
            match = entity_matcher.fuzzy_match(
                ref.referenced_identifier,
                list(data_room_files.keys()),
                threshold=0.80,
            )
            if match:
                updated.resolved_to = match
                updated.is_resolved = True
                updated.resolution_confidence = Confidence.LOW

        resolved.append(updated)

    return resolved
```

### 4.4 Implied Document Detection

Some cross-references imply the existence of documents even without explicit names:

| Pattern | Implication | Gap If Missing |
|---------|------------|---------------|
| "Amendment No. 3" | Amendments No. 1 and No. 2 should exist | Missing_Doc for each absent amendment |
| "as previously agreed" | A prior agreement exists | Missing_Doc if no prior agreement found |
| "Exhibit B" but only Exhibit A in data room | Exhibit B should be present | Missing_Doc for Exhibit B |
| "Second renewal" | A first renewal should exist | Missing_Doc if only one renewal found |
| "as amended from time to time" | One or more amendments may exist | Informational note (P3) -- does not guarantee amendments exist |

The agent detects these patterns during extraction and the orchestrator validates them during the cross-reference reconciliation phase.

---

## 5. Contradiction and Inconsistency Detection

### 5.1 Contradiction Categories

| Category | Detection Method | Severity | Example |
|----------|-----------------|----------|---------|
| **Financial contradiction** | Compare monetary values across documents for same clause | P0 | MSA: "Total liability shall not exceed $1,000,000." Order Form: "Liability cap: $5,000,000." |
| **Payment term contradiction** | Compare payment terms across governance chain | P0 | MSA: "Net-30 days." Amendment No. 1: "Net-60 days." (This is a valid override unless both claim to be current.) |
| **Scope contradiction** | Compare product/service scope between MSA and Order Forms | P1 | MSA covers "Platform and Analytics." Order Form covers "Platform only." |
| **Term contradiction** | Compare contract duration, auto-renewal, termination | P1 | MSA: "36-month initial term with auto-renewal." Amendment: "This Agreement shall not auto-renew." |
| **Governing law contradiction** | Compare jurisdiction/governing law across documents | P1 | MSA: "Governed by the laws of New York." Order Form: "Governed by the laws of Delaware." |
| **Date contradiction** | Compare effective dates for logical consistency | P2 | Amendment effective date is before the MSA execution date |
| **Administrative contradiction** | Compare notice addresses, contact persons, billing entities | P2 | MSA: billing to "Acme Corp, 100 Main St." Order Form: billing to "Acme Holdings, 200 Oak Ave." |

**Contradiction severity**: P0 (deal-stopper) — contradictions in pricing, payment terms, or termination rights. P1 (major) — contradictions in scope, SLAs, or liability caps. P2 (notable) — contradictions in notice periods, renewal terms, or minor commercial terms. P3 (informational) — contradictions in formatting, naming conventions, or non-binding terms.

### 5.2 Contradiction Data Model

```python
# src/dd_agents/models/cross_document.py (continued)

class Contradiction(BaseModel):
    """A detected contradiction between two documents."""
    model_config = ConfigDict(populate_by_name=True)

    customer_safe_name: str
    category: str = Field(
        description="One of: financial, payment_term, scope, term, governing_law, date, administrative",
    )
    severity: Severity
    file_a: str = Field(description="First document in the contradiction")
    file_b: str = Field(description="Second document in the contradiction")
    clause_a: str = Field(description="Provision text from file_a")
    clause_b: str = Field(description="Provision text from file_b (conflicting)")
    section_a: Optional[str] = Field(default=None, description="Section reference in file_a")
    section_b: Optional[str] = Field(default=None, description="Section reference in file_b")
    is_valid_override: bool = Field(
        default=False,
        description="True if file_b legitimately overrides file_a via governance chain",
    )
    resolution_notes: Optional[str] = Field(
        default=None,
        description="How the contradiction was resolved, or why it remains unresolved",
    )
    recommendation: str = Field(
        description="Recommended action: verify with seller, request clarification, etc.",
    )
```

### 5.3 Distinguishing Contradictions from Valid Overrides

Not every difference between documents is a contradiction. The key distinction:

- **Valid override**: File B explicitly states it modifies File A, and File B has governance authority to do so (Amendment → MSA, Order Form → MSA for Order Form-specific terms).
- **Contradiction**: File A and File B contain conflicting terms but neither explicitly overrides the other, or File B claims to override File A but the governance chain does not support it.

The algorithm:

```python
def classify_difference(
    file_a: str,
    file_b: str,
    clause_a: str,
    clause_b: str,
    governance_graph: nx.DiGraph,
) -> str:
    """Classify a difference between two documents as 'override' or 'contradiction'.

    Returns:
        'valid_override' if file_b has governance authority over file_a
        'contradiction' if the difference cannot be resolved by the governance chain
    """
    # Check if file_b amends or supersedes file_a
    if governance_graph.has_edge(file_b, file_a):
        edge_data = governance_graph.edges[file_b, file_a]
        if edge_data.get("relation") in (
            GovernanceRelationship.AMENDS,
            GovernanceRelationship.SUPERSEDES,
        ):
            return "valid_override"

    # Check if file_b is governed by file_a (child overriding parent for specific scope)
    if governance_graph.has_edge(file_a, file_b):
        edge_data = governance_graph.edges[file_a, file_b]
        if edge_data.get("relation") == GovernanceRelationship.GOVERNS:
            # Child (Order Form) may override parent (MSA) for child-specific scope
            return "valid_override"

    # Check if they share a common ancestor and one has precedence
    try:
        # If A is an ancestor of B, B's specific terms take precedence for its scope
        if nx.has_path(governance_graph, file_a, file_b):
            return "valid_override"
    except nx.NetworkXError:
        pass

    return "contradiction"
```

### 5.4 Dual Citation Requirement

Every contradiction finding must include exact citations from **both** conflicting documents. This is enforced by the `verify_citation` hook and the `Contradiction` model:

```python
# A contradiction finding in the agent output

{
    "finding_type": "Contradiction",
    "title": "Payment term conflict between MSA and Order Form",
    "severity": "P0",
    "customer_safe_name": "acme_corp",
    "citations": [
        {
            "file_name": "Acme_MSA_2023.pdf",
            "section": "Section 7.1 Payment Terms",
            "exact_quote": "All invoices shall be due and payable within thirty (30) days of receipt.",
            "source_type": "file"
        },
        {
            "file_name": "Acme_OrderForm_2024_Q1.pdf",
            "section": "Section 3 Billing",
            "exact_quote": "Payment terms: Net-60 days from invoice date.",
            "source_type": "file"
        }
    ],
    "recommendation": "Clarify with seller which payment terms are in effect. If the Order Form was intended to override the MSA, request written confirmation."
}
```

---

## 6. Missing Document Detection

### 6.1 Detection Methods

Missing documents are detected through four complementary methods. Each method produces `GapType.MISSING_DOC` gap findings.

#### Method 1: Cross-Reference-Based

Documents reference other documents that are not in the data room. This is the most reliable method because it is based on explicit textual evidence.

Examples:
- "This Order Form is governed by the Master Service Agreement dated January 15, 2024" -- but no such MSA exists
- "Pursuant to Amendment No. 2 to the Agreement" -- but only Amendment No. 3 is in the data room
- "As defined in Exhibit C" -- but Exhibit C is not in the data room

**Detection method**: `DetectionMethod.CROSS_REFERENCE`

#### Method 2: Pattern-Based (Sequence Analysis)

Sequential numbering in document names or references implies the existence of intermediate documents.

| Evidence | Expected Documents | Gap If Missing |
|----------|-------------------|---------------|
| "Amendment No. 3" exists | Amendment No. 1, Amendment No. 2 | Missing_Doc for each |
| "Third Renewal Agreement" exists | First and Second Renewal Agreements | Missing_Doc for each |
| "Exhibit D" exists but Exhibit B absent | Exhibit B (Exhibits A and C present) | Missing_Doc for Exhibit B |
| Order Form dated 2025 + MSA dated 2020 | Possible renewals for 2021-2024 | Informational (P3) unless auto-renewal clause requires renewal documents |

**Detection method**: `DetectionMethod.PATTERN_CHECK`

#### Method 3: Structural (Expected Document Patterns)

Certain document combinations are expected for enterprise SaaS customers. Absence of expected documents suggests incompleteness.

| Customer Profile | Expected Documents | Gap Trigger |
|-----------------|-------------------|-------------|
| SaaS customer with MSA | At least one Order Form or SOW | Missing Order Form/SOW if revenue exists but no transactional document |
| Customer with data processing | DPA or data protection clauses in MSA | Missing DPA if customer handles personal data |
| Multi-year customer | Renewal documentation or auto-renewal clause | Missing renewal if contract age exceeds initial term |
| Customer with custom SLA | SLA document or SLA section in MSA | Informational only (P3) -- SLAs may be embedded |

**Detection method**: `DetectionMethod.CHECKLIST`

#### Method 4: Temporal (Date-Gap Analysis)

Contract dates reveal temporal gaps that suggest missing documents.

```python
from datetime import date, timedelta


def detect_temporal_gaps(
    contract_dates: list[dict],
    initial_term_months: int = 12,
) -> list[dict]:
    """Detect gaps in the contract timeline that suggest missing documents.

    Args:
        contract_dates: List of dicts with keys: file, effective_date, expiry_date, doc_type.
        initial_term_months: Expected renewal cycle length in months.
    """
    gaps = []

    # Sort by effective date
    sorted_contracts = sorted(
        contract_dates,
        key=lambda c: c["effective_date"],
    )

    for i in range(len(sorted_contracts) - 1):
        current = sorted_contracts[i]
        next_contract = sorted_contracts[i + 1]

        # Check for time gap between expiry and next effective date
        if current.get("expiry_date"):
            gap_days = (next_contract["effective_date"] - current["expiry_date"]).days
            if gap_days > 90:  # More than 3 months gap
                gaps.append({
                    "type": "temporal_gap",
                    "severity": "P2",
                    "detail": (
                        f"Gap of {gap_days} days between expiry of '{current['file']}' "
                        f"({current['expiry_date']}) and effective date of "
                        f"'{next_contract['file']}' ({next_contract['effective_date']}). "
                        f"Missing renewal or bridge agreement?"
                    ),
                    "gap_start": str(current["expiry_date"]),
                    "gap_end": str(next_contract["effective_date"]),
                })

    return gaps
```

### 6.2 Completeness Score

Each customer receives a document completeness score:

```python
class DocumentCompleteness(BaseModel):
    """Document completeness assessment for a customer."""
    model_config = ConfigDict(populate_by_name=True)

    customer_safe_name: str
    total_documents: int = Field(description="Documents present in the data room")
    expected_documents: int = Field(description="Documents expected based on cross-references and patterns")
    missing_documents: int = Field(description="Expected documents that are absent")
    completeness_score: float = Field(
        description="total / expected. 1.0 = all expected documents present.",
        ge=0.0,
        le=1.0,
    )
    missing_details: list[dict] = Field(
        default_factory=list,
        description="List of missing documents with detection method and severity",
    )
    cross_reference_integrity: float = Field(
        description="Fraction of cross-references that resolve to existing files",
        ge=0.0,
        le=1.0,
    )
```

---

## 7. Renewal Chain Analysis

### 7.1 Renewal Chain Construction

A renewal chain is a sequence of agreements for the same customer where each agreement replaces (supersedes) the previous one. The chain represents the complete contractual history.

```
MSA_2020.pdf  ──supersedes──►  Renewal_2022.pdf  ──supersedes──►  Renewal_2024.pdf
                                                                      (current)
```

The system builds renewal chains by:

1. **Explicit supersession**: Document states "This Agreement replaces the Agreement dated..."
2. **Date-based inference**: Documents of the same type (MSA or Renewal) for the same customer, ordered by effective date
3. **Naming convention**: Files named with sequential years or renewal numbers

### 7.2 Renewal Analysis Data Model

```python
class RenewalChainAnalysis(BaseModel):
    """Analysis of a customer's renewal chain."""
    model_config = ConfigDict(populate_by_name=True)

    customer_safe_name: str
    chain_length: int = Field(description="Number of agreements in the chain")
    chain_documents: list[str] = Field(description="Ordered list of filenames, oldest to newest")
    current_agreement: str = Field(description="Currently active agreement filename")
    initial_term_start: Optional[date] = Field(default=None)
    current_term_end: Optional[date] = Field(default=None)
    total_relationship_years: Optional[float] = Field(default=None)
    renewal_type: str = Field(
        description="'auto' if auto-renewal, 'explicit' if explicit renewal documents, 'mixed'",
    )
    gaps_in_chain: list[dict] = Field(
        default_factory=list,
        description="Missing years or documents in the renewal sequence",
    )
    price_changes: list[dict] = Field(
        default_factory=list,
        description="Price changes across renewals: [{from_doc, to_doc, old_value, new_value, change_pct}]",
    )
    carried_forward_terms: list[str] = Field(
        default_factory=list,
        description="Clauses explicitly carried forward across all renewals",
    )
    renegotiated_terms: list[dict] = Field(
        default_factory=list,
        description="Clauses that changed between renewals: [{clause, from_doc, to_doc, old_text, new_text}]",
    )
```

### 7.3 Price Escalation Tracking

For Finance agent analysis, tracking price changes across renewals is critical for revenue modeling:

```python
def track_price_escalation(
    renewal_chain: list[dict],
) -> list[dict]:
    """Track pricing changes across a renewal chain.

    Args:
        renewal_chain: Ordered list of dicts with keys: file, effective_date, annual_value.
    """
    changes = []
    for i in range(1, len(renewal_chain)):
        prev = renewal_chain[i - 1]
        curr = renewal_chain[i]

        if prev.get("annual_value") and curr.get("annual_value"):
            old_val = prev["annual_value"]
            new_val = curr["annual_value"]
            change_pct = ((new_val - old_val) / old_val) * 100 if old_val > 0 else None

            changes.append({
                "from_doc": prev["file"],
                "to_doc": curr["file"],
                "old_value": old_val,
                "new_value": new_val,
                "change_pct": round(change_pct, 1) if change_pct is not None else None,
                "period": f"{prev.get('effective_date')} to {curr.get('effective_date')}",
            })

    return changes
```

### 7.4 Auto-Renewal vs Explicit Renewal

The distinction matters for revenue predictability:

- **Auto-renewal**: Contract continues under the same terms unless one party provides notice. Revenue is predictable but terms may be stale. The system checks for notice-of-non-renewal documents.
- **Explicit renewal**: A new agreement is signed for each term. Revenue requires active re-engagement. The system checks for gaps between renewal documents.
- **Mixed**: Original MSA auto-renewed for some periods, then an explicit renewal changed terms. Common in long-running customer relationships.

The system determines renewal type by examining the MSA's renewal clause and checking whether explicit renewal documents exist:

```python
def classify_renewal_type(
    msa_has_auto_renewal: bool,
    explicit_renewals_count: int,
) -> str:
    """Classify the renewal pattern for a customer.

    Args:
        msa_has_auto_renewal: Whether the MSA contains an auto-renewal clause.
        explicit_renewals_count: Number of explicit renewal agreements in the data room.
    """
    if explicit_renewals_count > 0 and msa_has_auto_renewal:
        return "mixed"
    elif explicit_renewals_count > 0:
        return "explicit"
    elif msa_has_auto_renewal:
        return "auto"
    else:
        return "unknown"  # Neither auto-renewal clause nor explicit renewals found
```

---

## 8. Agent Responsibilities for Cross-Document Analysis

### 8.1 Division of Labor

Each specialist agent handles cross-document analysis within its domain. The Judge validates cross-agent findings.

| Agent | Cross-Document Responsibilities |
|-------|---------------------------------|
| **Legal** | Governance graph construction, override detection, amendment chain analysis, governing law consistency, signature verification, termination analysis |
| **Finance** | Financial contradiction detection (liability caps, payment terms, pricing), price escalation across renewals, revenue impact of overrides |
| **Commercial** | Scope contradiction detection (product coverage, service levels, exclusivity), renewal pattern analysis, customer classification based on contract evolution |
| **ProductTech** | SLA chaining (MSA SLA → Order Form SLA → DPA), data protection lineage (DPA references in MSAs), technology scope tracking across amendments |
| **Judge** | Cross-agent contradiction resolution (when Legal and Finance disagree on override interpretation), spot-checking of cross-reference resolution, verification of governance graph completeness |
| **ReportingLead** | Merging cross-document findings from all agents, deduplication of findings about the same cross-document issue reported by multiple agents, populating governance-related Excel sheets |

### 8.2 Agent Prompt Integration

Cross-document analysis instructions are injected into agent prompts via the prompt builder (`agents/prompt_builder.py`). Each agent receives:

1. **Governance graph summary**: For each customer, a text summary of the known governance relationships, generated from the NetworkX graph at step 14 (PREPARE_PROMPTS).
2. **Cross-reference index**: All detected cross-references with resolution status.
3. **Override alerts**: Known overrides from previous agents (for Judge) or from governance graph analysis (for specialists).
4. **Missing document context**: Any already-detected missing documents, so agents do not duplicate gap findings.

```python
def build_cross_document_context(
    customer_safe_name: str,
    governance_graph: nx.DiGraph,
    cross_references: list[CrossReference],
) -> str:
    """Build cross-document context section for agent prompts."""
    lines = [
        f"## Cross-Document Context for {customer_safe_name}",
        "",
        "### Governance Hierarchy",
    ]

    # Topological order of documents
    try:
        order = list(nx.topological_sort(governance_graph))
        for doc in order:
            parents = list(governance_graph.predecessors(doc))
            children = list(governance_graph.successors(doc))
            parent_str = ", ".join(parents) if parents else "(root document)"
            child_str = ", ".join(children) if children else "(leaf document)"
            lines.append(f"- **{doc}**: governed by {parent_str}, governs {child_str}")
    except nx.NetworkXUnfeasible:
        lines.append("WARNING: Governance graph contains cycles. Cannot determine precedence order.")

    # Unresolved cross-references
    unresolved = [ref for ref in cross_references if not ref.is_resolved]
    if unresolved:
        lines.append("")
        lines.append("### Unresolved Cross-References")
        for ref in unresolved:
            lines.append(
                f"- {ref.source_file} references '{ref.referenced_identifier or ref.reference_text[:80]}' "
                f"-- NOT FOUND in data room"
            )

    return "\n".join(lines)
```

### 8.3 Cross-Agent Finding Merge Protocol

When multiple agents detect the same cross-document issue (e.g., Legal flags a payment term contradiction and Finance also flags it):

**Cross-document finding dedup criteria**: Two findings are considered duplicates when ALL of the following match: (1) same `customer_safe_name`, (2) same `issue_type` (from the finding taxonomy), (3) overlapping source documents (at least one document in common), and (4) semantic similarity > 0.85 (computed via normalized text comparison using rapidfuzz.fuzz.token_sort_ratio). When duplicates are found, the finding with higher severity is kept; the other is marked as `deduplicated_by: <finding_id>`.

1. **Deduplication**: Findings matching the criteria above are candidates for merge.
2. **Agent attribution**: The merged finding retains both agents' names in the `agents` field.
3. **Severity resolution**: If agents assigned different severities, the higher severity is used.
4. **Detail merge**: Both agents' details are concatenated with agent attribution headers.

This merge happens at step 24 (MERGE_DEDUP) by the Reporting Lead. See `10-reporting.md` for the full merge protocol.

---

## 9. Implementation Integration

### 9.1 Pipeline Steps for Cross-Document Analysis

Cross-document analysis is distributed across multiple pipeline steps. The following table maps each capability to its pipeline step(s) from `05-orchestrator.md`:

| Capability | Pipeline Step(s) | Implementation |
|-----------|-----------------|----------------|
| Governance graph construction (initial) | Step 7: ENTITY_RESOLUTION | `entity_resolution/matcher.py` builds initial edges from file naming patterns |
| Reference file registry | Step 8: REFERENCE_REGISTRY | `inventory/references.py` identifies shared reference documents |
| Customer mention index | Step 9: CUSTOMER_MENTIONS | `inventory/mentions.py` maps document cross-references |
| Inventory integrity check | Step 10: INVENTORY_INTEGRITY | Validates governance graph structure, detects orphans |
| Contract date reconciliation | Step 11: CONTRACT_DATE_RECONCILIATION | `reporting/contract_dates.py` builds temporal chains |
| Agent cross-document analysis | Step 16: SPAWN_SPECIALISTS | Agents receive governance context in prompts; produce override/contradiction findings |
| Coverage gate | Step 17: COVERAGE_GATE | Validates that all governance edges are covered by agent analysis |
| Finding merge + dedup | Step 24: MERGE_DEDUP | `reporting/merge.py` merges cross-agent cross-document findings |
| Gap consolidation | Step 25: MERGE_GAPS | Consolidates missing document gaps from all agents |
| Numerical audit | Step 27: NUMERICAL_AUDIT | Validates financial figures across governance chains |
| QA audit | Step 28: FULL_QA_AUDIT | Includes governance completeness in DoD checks |

### 9.2 Persistence

Cross-document artifacts are stored in the three-tier persistence model:

| Artifact | Tier | Path | Format |
|----------|------|------|--------|
| Governance graph (per-customer) | VERSIONED | `runs/{run_id}/governance/{customer_safe_name}.json` | NetworkX node-link JSON |
| Cross-reference index | VERSIONED | `runs/{run_id}/cross_references/{customer_safe_name}.json` | List of CrossReference |
| Override log | VERSIONED | `runs/{run_id}/overrides/{customer_safe_name}.json` | List of Override |
| Contradiction log | VERSIONED | `runs/{run_id}/contradictions/{customer_safe_name}.json` | List of Contradiction |
| Renewal chains | VERSIONED | `runs/{run_id}/renewal_chains/{customer_safe_name}.json` | RenewalChainAnalysis |
| Document completeness | VERSIONED | `runs/{run_id}/completeness/{customer_safe_name}.json` | DocumentCompleteness |

### 9.3 NetworkX Serialization

Governance graphs are serialized to JSON using NetworkX's node-link format for persistence and loaded back for validation:

```python
import json
import networkx as nx
from pathlib import Path


def save_governance_graph(G: nx.DiGraph, path: Path) -> None:
    """Serialize a governance graph to JSON."""
    data = nx.node_link_data(G)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def load_governance_graph(path: Path) -> nx.DiGraph:
    """Deserialize a governance graph from JSON."""
    data = json.loads(path.read_text())
    return nx.node_link_graph(data, directed=True)
```

### 9.4 Report Integration

Cross-document findings appear in these Excel sheets (defined in `10-reporting.md`):

| Sheet | Cross-Document Content |
|-------|----------------------|
| **Summary** | Governance completeness column, contradiction count per customer |
| **Wolf_Pack** | P0/P1 cross-document findings (contradictions, missing critical documents) |
| **Legal_Risks** | Override chain details, governing law conflicts, amendment analysis |
| **Missing_Docs_Gaps** | All missing document gaps with detection method and severity |
| **Data_Reconciliation** | Cross-reference integrity scores, financial contradiction details |
| **Contract_Date_Reconciliation** | Temporal chain visualization, renewal gap detection |

---

## 10. Authenticity and Consistency Checks

### 10.1 Signature Page Consistency

Related documents should have consistent party information:

| Check | What to Compare | Failure Severity |
|-------|----------------|-----------------|
| **Party names** | Counterparty name across MSA, Order Forms, Amendments | P1 if names differ (may indicate assignment without Assignment Agreement) |
| **Signing entities** | Legal entity name on signature page vs. entity in preamble | P2 if different (common for subsidiaries) |
| **Authorized signatories** | Signer authority across documents | P3 (informational -- authority verification is outside DD scope) |
| **Execution dates** | Date logic: Amendment cannot be executed before MSA | P1 if logically impossible dates detected |

### 10.2 Date Consistency Validation

```python
def validate_date_consistency(
    governance_graph: nx.DiGraph,
    document_dates: dict[str, dict],
) -> list[dict]:
    """Validate that document dates are logically consistent with governance relationships.

    Args:
        governance_graph: Per-customer governance graph.
        document_dates: Dict mapping filename to {effective_date, execution_date, expiry_date}.
    """
    issues = []

    for source, target, data in governance_graph.edges(data=True):
        relation = data.get("relation")
        source_dates = document_dates.get(source, {})
        target_dates = document_dates.get(target, {})

        source_effective = source_dates.get("effective_date")
        target_effective = target_dates.get("effective_date")

        if not source_effective or not target_effective:
            continue

        # Amendment cannot predate the document it amends
        if relation == GovernanceRelationship.AMENDS:
            if source_effective < target_effective:
                issues.append({
                    "type": "date_inconsistency",
                    "severity": "P1",
                    "detail": (
                        f"Amendment '{source}' (effective {source_effective}) "
                        f"predates the document it amends: '{target}' (effective {target_effective})"
                    ),
                    "file_a": source,
                    "file_b": target,
                })

        # Superseding document should postdate the document it replaces
        if relation == GovernanceRelationship.SUPERSEDES:
            if source_effective < target_effective:
                issues.append({
                    "type": "date_inconsistency",
                    "severity": "P2",
                    "detail": (
                        f"Document '{source}' (effective {source_effective}) claims to supersede "
                        f"'{target}' (effective {target_effective}) but predates it"
                    ),
                    "file_a": source,
                    "file_b": target,
                })

    return issues
```

### 10.3 Counterparty Consistency

The entity resolution system (`09-entity-resolution.md`) normalizes customer names. For cross-document consistency, the system also checks that the counterparty is consistent across a customer's documents:

1. Extract counterparty name from each document's preamble
2. Normalize using the entity resolution matcher
3. Flag if different canonical names appear across documents for the same customer folder
4. Distinguish between legitimate variations (subsidiary names, name changes due to acquisition) and genuine inconsistencies

This check helps detect:
- Documents misfiled in the wrong customer folder
- Assignment of contracts (Acme Corp's contract assigned to Acme Holdings after reorganization) without an Assignment Agreement
- Name changes (legal entity renamed) without corresponding documentation

### 10.4 Version Consistency

Amendment chains are constructed from document metadata (filenames containing 'amendment', 'addendum', 'modification') and from extracted text (references to prior agreement dates or document numbers). The chain is stored in the governance graph as a linked sequence of ContractNode objects.

For amendment chains, the system validates that each amendment references the correct version of the underlying agreement:

```python
def validate_amendment_chain(
    amendments: list[dict],
    base_document: str,
) -> list[dict]:
    """Validate that amendments reference the correct base document and are sequentially consistent.

    Args:
        amendments: Sorted list of dicts: {file, amendment_number, references_base, effective_date}.
        base_document: Filename of the base agreement being amended.
    """
    issues = []

    for i, amendment in enumerate(amendments):
        # Each amendment should reference the base document
        if amendment.get("references_base") != base_document:
            issues.append({
                "type": "version_inconsistency",
                "severity": "P2",
                "detail": (
                    f"Amendment '{amendment['file']}' references "
                    f"'{amendment.get('references_base')}' instead of "
                    f"expected base document '{base_document}'"
                ),
            })

        # Amendment numbers should be sequential
        if i > 0:
            prev_num = amendments[i - 1].get("amendment_number", 0)
            curr_num = amendment.get("amendment_number", 0)
            if curr_num is not None and prev_num is not None and curr_num != prev_num + 1:
                issues.append({
                    "type": "sequence_gap",
                    "severity": "P1",
                    "detail": (
                        f"Amendment sequence gap: Amendment No. {prev_num} followed by "
                        f"Amendment No. {curr_num}. Missing Amendment No. {prev_num + 1}?"
                    ),
                })

    return issues
```

---

## 11. Quality Assurance for Cross-Document Findings

### 11.1 Validation Gates

Cross-document analysis is validated at three pipeline gates:

| Gate | Step | Cross-Document Checks |
|------|------|-----------------------|
| **Coverage Gate** (Step 17) | COVERAGE_GATE | Every governance edge has been analyzed by at least one agent. No orphaned documents remain unaddressed. |
| **Numerical Audit** (Step 27) | NUMERICAL_AUDIT | Financial values in override chains are consistent. Price escalation figures match source documents. |
| **QA Audit** (Step 28) | FULL_QA_AUDIT | Cross-reference integrity score computed per customer. Contradiction findings have dual citations. Missing document gaps have detection methods. |

### 11.2 Definition of Done Checks

The following DoD checks (from `11-qa-validation.md`) apply to cross-document analysis:

- **DoD-7**: Every finding cites exact_quote from source file (enforced by verify_citation hook)
- **DoD-9**: Governance graph is a DAG (no cycles) per customer
- **DoD-10**: All cross-references are either resolved or flagged as Missing_Doc gaps
- **DoD-11**: Contradictions have dual citations (both conflicting documents)
- **DoD-12**: Override chains are temporally consistent (no date contradictions)
- **DoD-14**: Amendment numbering sequence has no unaccounted gaps

### 11.3 Judge Spot-Checks for Cross-Document Findings

The Judge agent (`06-agents.md`, Section 7) applies targeted spot-checks to cross-document findings:

1. **Citation verification**: For each contradiction finding, verify that both exact_quotes exist in their claimed source files
2. **Governance graph validation**: For a sample of customers, independently verify that the governance edges match the document contents
3. **Override correctness**: For P0/P1 overrides, verify that the overriding document actually contains override language and that the governance chain supports the override
4. **Cross-agent consistency**: When Legal and Finance both analyze the same cross-document issue, verify their findings are consistent

---

## 12. Edge Cases and Special Patterns

### 12.1 Documents with No Clear Governance

Some documents in data rooms defy standard governance patterns:

| Pattern | Handling |
|---------|---------|
| **Standalone NDA** | NDAs often predate the MSA and operate independently. Treat as parallel to (not governed by) the MSA. |
| **Informal email agreements** | Exported emails confirming terms. Flag as P2 gap (no formal contract) but extract terms. |
| **Board resolutions** | Approve contract execution. Reference from governance graph but do not treat as contract. |
| **Redacted documents** | Document exists but content is partially or fully redacted. Flag as `GapType.UNREADABLE` if critical sections are redacted. |
| **Draft agreements** | Unsigned drafts in the data room. Flag as informational (P3). Do not include in governance graph unless no signed version exists. |

### 12.2 Multi-Entity Customers

Some customers appear under multiple legal entities (subsidiary, parent, acquired name). The entity resolution system handles name normalization, but cross-document analysis must also consider:

- An MSA signed with "Acme Corp" and an Order Form signed with "Acme Holdings" (parent company)
- An Assignment Agreement transferring contracts from "Acme Corp" to "Acme International" after a corporate restructuring
- Joint ventures where two entities co-sign different documents

The system groups these under a single customer using the entity resolution cache (`09-entity-resolution.md`), but flags the entity variation as a finding (P2 or P3 depending on whether an Assignment Agreement exists).

### 12.3 Conflicting Governance Claims

Rare but possible: two documents both claim to govern the same child document.

Example: Order Form states "This Order Form is governed by MSA-2023-001" but also states "subject to the terms of the Framework Agreement dated March 1, 2023." If both MSA-2023-001 and the Framework Agreement exist and contain different terms, this creates a multi-parent governance conflict.

The system detects this via the multi-parent check in `validate_governance_graph()` (Section 2.3) and escalates to P1 severity.

---

## Appendix A: Cross-Document Data Flow Diagram

```
Step 7-10: Inventory Phase
    File Discovery → Entity Resolution → Reference Registry → Customer Mentions
    ↓
    Initial governance graph (from file names, folder structure)
    Initial cross-reference index (from document text patterns)
    ↓

Step 11: Contract Date Reconciliation
    Extract dates from all documents
    Build temporal chains per customer
    Detect date gaps and anomalies
    ↓

Step 14: Prepare Prompts
    Serialize governance graph to text summaries
    Include cross-reference index in agent context
    Include known overrides and gaps
    ↓

Step 16: Specialist Analysis
    Legal: governance refinement, override detection, amendment analysis
    Finance: financial contradiction detection, price escalation
    Commercial: scope contradiction detection, renewal pattern analysis
    ProductTech: SLA/DPA chaining, technology scope tracking
    ↓
    Each agent writes:
      _findings/{agent}/{customer}.json  (with cross-document findings)
      _findings/{agent}/governance_updates/{customer}.json  (graph edges to add/update)
    ↓

Step 17: Coverage Gate
    Merge governance updates from all agents
    Validate final governance graph (DAG check, isolate check)
    Verify all customers have governance analysis
    ↓

Steps 24-25: Merge + Gap Consolidation
    Merge cross-document findings from 4 agents
    Deduplicate contradiction findings
    Consolidate missing document gaps
    Build final cross-reference integrity scores
    ↓

Steps 27-28: Validation
    Numerical audit: financial consistency across governance chains
    QA audit: governance DoD checks, cross-reference validation
    ↓

Step 30: Excel Generation
    Populate cross-document columns in Summary, Legal_Risks, Missing_Docs_Gaps
    Build Contract_Date_Reconciliation sheet
    Include governance completeness metrics
```

---

## Appendix B: Summary of New Pydantic Models

All models defined in this document belong in `src/dd_agents/models/cross_document.py`:

| Model | Purpose |
|-------|---------|
| `Override` | Records an override relationship between two documents with citation evidence |
| `SupersessionChain` | Tracks a chain of documents where each supersedes the previous |
| `CrossReference` | Records a reference from one document to another with resolution status |
| `CrossReferenceIntegrity` | Per-customer summary of cross-reference resolution quality |
| `Contradiction` | Records a detected contradiction between two documents with dual citations |
| `DocumentCompleteness` | Per-customer document completeness assessment |
| `RenewalChainAnalysis` | Analysis of a customer's renewal chain with price tracking |

These models extend the existing model hierarchy in `04-data-models.md`. They are validated by the orchestrator at steps 24-28 and serialized to the VERSIONED tier.
