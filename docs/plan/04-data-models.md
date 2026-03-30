# 04 -- Data Models (Pydantic v2)

All JSON schemas from the forensic-dd skill files are translated to Pydantic v2 models. These serve three purposes:
1. **Validation** -- `model_validate()` for deterministic agent output checking
2. **Structured output** -- `model_json_schema()` feeds SDK `output_format`
3. **Type safety** -- IDE autocomplete, mypy checking throughout the pipeline

Every model uses `model_config = ConfigDict(populate_by_name=True)` where aliases are needed, and all serialization uses `model_dump(exclude_none=True)` by default to comply with the framework rule that optional fields are omitted (not null).

---

## Enums (Shared Across Models)

```python
# src/dd_agents/models/finding.py (top section)

from enum import Enum


class Severity(str, Enum):
    """Finding severity / gap priority. From domain-definitions.md section 3."""
    P0 = "P0"  # Deal-stopper: could block or unwind the acquisition
    P1 = "P1"  # Critical: material risk requiring pre-close negotiation
    P2 = "P2"  # Important: post-close attention needed
    P3 = "P3"  # Minor: informational, admin gaps, domain_reviewed_no_issues


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceType(str, Enum):
    FILE = "file"
    URL = "url"
    REFERENCE_FILE = "reference_file"
    DATABASE = "database"
    WEB_RESEARCH = "web_research"


class AgentName(str, Enum):
    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"


class GapType(str, Enum):
    """Gap type enum. From domain-definitions.md section 6d."""
    MISSING_DOC = "Missing_Doc"         # Referenced/expected document absent
    MISSING_DATA = "Missing_Data"       # Doc exists but key fields blank/redacted
    AMBIGUOUS_LINK = "Ambiguous_Link"   # Governance unresolvable
    UNREADABLE = "Unreadable"           # OCR and Read both failed
    CONTRADICTION = "Contradiction"     # Conflicting terms across docs
    DATA_MISMATCH = "Data_Mismatch"     # Contract terms contradict reference data


class DetectionMethod(str, Enum):
    """How a gap was detected. From domain-definitions.md section 6d."""
    CROSS_REFERENCE = "cross_reference"
    CROSS_REFERENCE_GHOST = "cross_reference_ghost"
    CROSS_REFERENCE_PHANTOM = "cross_reference_phantom"
    CROSS_REFERENCE_MISMATCH = "cross_reference_mismatch"
    PATTERN_CHECK = "pattern_check"
    CHECKLIST = "checklist"
    GOVERNANCE_RESOLUTION = "governance_resolution"


class AuditAction(str, Enum):
    """Audit log action enum. From audit-entry.schema.json."""
    FILE_READ = "file_read"
    FINDING_CREATED = "finding_created"
    FINDING_UPDATED = "finding_updated"
    FINDING_DELETED = "finding_deleted"
    GAP_CREATED = "gap_created"
    WEB_RESEARCH = "web_research"
    CALCULATION = "calculation"
    CROSS_REFERENCE = "cross_reference"
    ENTITY_RESOLUTION = "entity_resolution"
    SKIP = "skip"
    ERROR = "error"
    VALIDATION_CHECK = "validation_check"
    HANDOFF_RECEIVED = "handoff_received"
    PHASE_COMPLETE = "phase_complete"


class SpotCheckDimension(str, Enum):
    """Judge spot-check dimensions. From quality-score.schema.json."""
    CITATION_VERIFICATION = "citation_verification"
    CONTEXTUAL_VALIDATION = "contextual_validation"
    FINANCIAL_ACCURACY = "financial_accuracy"
    CROSS_AGENT_CONSISTENCY = "cross_agent_consistency"
    COMPLETENESS = "completeness"


class SpotCheckResult(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class CustomerClassificationStatus(str, Enum):
    """Incremental mode classification. From SKILL.md section 0e."""
    NEW = "NEW"
    CHANGED = "CHANGED"
    STALE_REFRESH = "STALE_REFRESH"
    UNCHANGED = "UNCHANGED"
    DELETED = "DELETED"


class ExtractionQualityMethod(str, Enum):
    """Extraction method used for a file."""
    PRIMARY = "primary"                       # markitdown succeeded
    FALLBACK_PDFTOTEXT = "fallback_pdftotext"
    FALLBACK_OCR = "fallback_ocr"
    FALLBACK_READ = "fallback_read"
    DIRECT_READ = "direct_read"               # Plaintext read directly
    FAILED = "failed"                         # All methods failed


class FileSkipReason(str, Enum):
    """Reasons for skipping a file in the manifest."""
    OUTSIDE_AGENT_SCOPE = "outside_agent_scope"
    DUPLICATE_CONTENT = "duplicate_content"
    NON_CONTRACT_MATERIAL = "non_contract_material"
    AGENT_CAPACITY_LIMIT = "agent_capacity_limit"
    OTHER = "other"


class GovernanceRelationship(str, Enum):
    """Types of governance relationships between documents."""
    GOVERNS = "governs"
    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"


class DealType(str, Enum):
    """Deal type enum from deal-config.schema.json."""
    ACQUISITION = "acquisition"
    MERGER = "merger"
    DIVESTITURE = "divestiture"
    INVESTMENT = "investment"
    JOINT_VENTURE = "joint_venture"
    OTHER = "other"


class ExecutionMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ReferenceFileCategory(str, Enum):
    FINANCIAL = "Financial"
    PRICING = "Pricing"
    CORPORATE_LEGAL = "Corporate/Legal"
    OPERATIONAL = "Operational"
    SALES = "Sales"
    COMPLIANCE = "Compliance"
    HR = "HR"
    OTHER = "Other"
```

---

## Configuration Models

Source: `deal-config.template.json` + `deal-config.schema.json`

```python
# src/dd_agents/models/config.py

from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional


class BuyerInfo(BaseModel):
    """Buyer entity information."""
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    ticker: str = ""
    exchange: str = ""
    notes: str = ""


class PreviousName(BaseModel):
    """Historical name of the target entity."""
    name: str
    period: str = ""
    notes: str = ""


class AcquiredEntity(BaseModel):
    """Entity previously acquired by the target."""
    name: str
    acquisition_date: str = ""  # YYYY-MM-DD
    deal_type: str = ""
    notes: str = ""

    @field_validator("acquisition_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if v and not __import__("re").match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("acquisition_date must be YYYY-MM-DD format")
        return v


class TargetInfo(BaseModel):
    """Target entity information."""
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    subsidiaries: list[str] = Field(default_factory=list)
    previous_names: list[PreviousName] = Field(default_factory=list)
    acquired_entities: list[AcquiredEntity] = Field(default_factory=list)
    entity_name_variants_for_contract_matching: list[str] = Field(
        default_factory=list
    )
    notes: str = ""


class EntityAliases(BaseModel):
    """Entity resolution alias configuration. From entity-resolution-protocol.md."""
    model_config = ConfigDict(extra="allow")

    canonical_to_variants: dict[str, list[str]] = Field(default_factory=dict)
    short_name_guard: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    parent_child: dict[str, list[str]] = Field(default_factory=dict)


class ActiveFilter(BaseModel):
    """Filter criteria for identifying active customers in the database."""
    arr_column: int | None = None
    arr_condition: str = ""
    end_date_condition: str = ""


class CustomerDatabaseColumns(BaseModel):
    """Column index mapping for the customer database spreadsheet."""
    model_config = ConfigDict(extra="allow")

    customer_name: int = Field(ge=1)
    parent_account: int | None = None
    entity: int | None = None
    platform: int | None = None
    contract_start: int | None = None
    contract_end: int | None = None
    arr: int | None = None


class CustomerDatabase(BaseModel):
    """Customer database reference for contract date reconciliation."""
    file: str = Field(min_length=1)
    sheet: str = ""
    header_row: int = Field(default=1, ge=1)
    columns: CustomerDatabaseColumns
    active_filter: ActiveFilter | None = None


class SourceOfTruth(BaseModel):
    """Authoritative data source configuration. From SKILL.md section 5."""
    model_config = ConfigDict(extra="allow")

    customer_database: CustomerDatabase | None = None


class KeyExecutive(BaseModel):
    """Key executive of the target company."""
    name: str
    title: str
    company: str
    notes: str = ""


class DealInfo(BaseModel):
    """Deal parameters and focus areas."""
    model_config = ConfigDict(extra="allow")

    type: DealType
    focus_areas: list[str] = Field(min_length=1)
    notes: str = ""


class SamplingRates(BaseModel):
    """Judge sampling rates per severity level."""
    p0: float = Field(default=1.0, ge=0.0, le=1.0)
    p1: float = Field(default=0.20, ge=0.0, le=1.0)
    p2: float = Field(default=0.10, ge=0.0, le=1.0)
    p3: float = Field(default=0.0, ge=0.0, le=1.0)


class JudgeConfig(BaseModel):
    """Judge agent configuration. From agent-prompts.md section 6."""
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    max_iteration_rounds: int = Field(default=2, ge=1, le=5)
    score_threshold: int = Field(default=70, ge=0, le=100)
    sampling_rates: SamplingRates = Field(default_factory=SamplingRates)
    ocr_completeness_check: bool = True
    cross_agent_contradiction_check: bool = True


class ExecutionConfig(BaseModel):
    """Pipeline execution configuration. From SKILL.md section 0e."""
    model_config = ConfigDict(extra="allow")

    execution_mode: ExecutionMode = ExecutionMode.FULL
    staleness_threshold: int = Field(default=3, ge=1, le=100)
    force_full_on_config_change: bool = True


class ReportingConfig(BaseModel):
    """Report generation configuration. From reporting-protocol.md section 3."""
    model_config = ConfigDict(extra="allow")

    report_schema_override: str | None = None
    include_diff_sheet: bool = True
    include_metadata_sheet: bool = True


class CustomDomain(BaseModel):
    """Custom analysis domain definition."""
    id: str = Field(pattern=r"^[a-z_]+$")
    name: str
    description: str = ""
    agent_assignment: AgentName
    expected_finding_categories: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    weight: int = Field(default=3, ge=1, le=3)


class DomainConfig(BaseModel):
    """Analysis domain configuration for forensic-dd."""
    disabled: list[str] = Field(default_factory=list)
    custom: list[CustomDomain] = Field(default_factory=list)


class ForensicDDConfig(BaseModel):
    """Forensic DD skill-specific configuration."""
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    domains: DomainConfig = Field(default_factory=DomainConfig)


class DealConfig(BaseModel):
    """
    Root configuration model. Validated from deal-config.json.
    Source: deal-config.schema.json + deal-config.template.json
    """
    model_config = ConfigDict(extra="allow")

    config_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    buyer: BuyerInfo
    target: TargetInfo
    entity_aliases: EntityAliases = Field(default_factory=EntityAliases)
    source_of_truth: SourceOfTruth = Field(default_factory=SourceOfTruth)
    key_executives: list[KeyExecutive] = Field(default_factory=list)
    deal: DealInfo
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    forensic_dd: ForensicDDConfig = Field(default_factory=ForensicDDConfig)

    @field_validator("config_version")
    @classmethod
    def check_minimum_version(cls, v: str) -> str:
        parts = [int(x) for x in v.split(".")]
        if parts < [1, 0, 0]:
            raise ValueError("config_version must be >= 1.0.0")
        return v
```

---

## Finding and Citation Models

Source: `domain-definitions.md` sections 2-3, `finding.schema.json`

```python
# src/dd_agents/models/finding.py (continued after enums)

from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional
from datetime import datetime


class Citation(BaseModel):
    """
    Citation attached to a finding. From domain-definitions.md section 2.

    IMPORTANT: exact_quote is typed as str (not Optional). For clean-result
    findings (domain_reviewed_no_issues), OMIT the exact_quote field entirely
    rather than setting it to null. Serialize with exclude_none=True.
    """
    model_config = ConfigDict(populate_by_name=True)

    source_type: SourceType
    source_path: str
    location: str = ""                          # "Section X.Y" or page number
    exact_quote: str | None = Field(
        default=None,
        description="Verbatim text from the document. OMIT (do not set to null) "
                    "for clean-result findings. Serialize with exclude_none=True."
    )
    # NOTE: exact_quote is stored as a plain string. When the quote contains
    # special characters (newlines, quotes), they are escaped using standard
    # JSON string escaping. No custom serializer needed -- Pydantic v2 handles
    # this natively via model_dump_json().
    access_date: str | None = None              # Required when source_type == web_research

    @model_validator(mode="after")
    def web_research_needs_access_date(self) -> Citation:
        if self.source_type == SourceType.WEB_RESEARCH and not self.access_date:
            raise ValueError(
                "access_date is required when source_type is 'web_research'"
            )
        return self


class Finding(BaseModel):
    """
    Full framework-schema-compliant finding.
    Conforms to dd-framework/schemas/finding.schema.json.
    Produced by the Reporting Lead during merge (not by specialist agents directly).
    """
    id: str = Field(
        pattern=r"^[a-z][a-z0-9-]*_[a-z][a-z0-9_-]*_\d{4,}$",
        description="Format: {skill}_{agent}_{sequential_number} e.g. forensic-dd_legal_0001"
    )
    severity: Severity
    category: str
    title: str = Field(max_length=120)
    description: str
    citations: list[Citation] = Field(min_length=1)
    confidence: Confidence
    agent: AgentName
    skill: str = "forensic-dd"
    run_id: str
    timestamp: str                              # ISO-8601
    analysis_unit: str                          # customer name
    metadata: dict = Field(default_factory=dict)

    @field_validator("citations")
    @classmethod
    def p0_p1_require_exact_quote(cls, v: list[Citation], info) -> list[Citation]:
        severity = info.data.get("severity")
        if severity in (Severity.P0, Severity.P1):
            for cit in v:
                if not cit.exact_quote:
                    raise ValueError(
                        f"{severity.value} finding must have exact_quote "
                        f"in all citations"
                    )
        return v


class AgentFinding(BaseModel):
    """
    Agent-internal finding format (pre-transformation).
    Missing id/agent/skill/run_id/timestamp/analysis_unit fields.
    These are added by the Reporting Lead during merge.
    From agent-prompts.md section 4c.
    """
    severity: Severity
    category: str
    title: str = Field(max_length=120)
    description: str
    citations: list[Citation] = Field(min_length=1)
    confidence: Confidence


class Gap(BaseModel):
    """
    Missing document or data gap. From domain-definitions.md section 6d.
    Every gap MUST have all required fields -- missing fields cause QA failure.
    """
    customer: str
    priority: Severity
    gap_type: GapType
    missing_item: str = Field(max_length=200)
    why_needed: str
    risk_if_missing: str
    request_to_company: str
    evidence: str
    detection_method: DetectionMethod
    source_file: str | None = None              # Recommended
    agent: AgentName | None = None              # Recommended
    run_id: str | None = None                   # Recommended
```

---

## Inventory Models

Source: `SKILL.md` sections 1-2, `agent-prompts.md` section 2

```python
# src/dd_agents/models/inventory.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class FileEntry(BaseModel):
    """Individual file in the data room."""
    path: str
    text_path: str | None = None                # Path to extracted text, or None
    mime_type: str = ""
    size: int = 0
    checksum: str = ""                          # SHA-256


class CustomerEntry(BaseModel):
    """One customer in the customer registry (customers.csv row)."""
    group: str                                  # Group folder name
    name: str                                   # Customer display name
    safe_name: str                              # customer_safe_name convention
    path: str                                   # Customer directory path
    file_count: int = 0
    files: list[str] = Field(default_factory=list)  # List of file paths


class ReferenceFile(BaseModel):
    """
    Global reference file (not under a customer directory).
    From SKILL.md section 2b.
    """
    file_path: str                              # Original file path (REQUIRED)
    text_path: str | None = None                # Extracted text path, or None
    category: str                               # Financial, Pricing, Corporate/Legal, etc.
    subcategory: str                            # Finer classification
    description: str                            # 1-2 sentence description
    customers_mentioned: list[str] = Field(default_factory=list)
    customers_mentioned_count: int = 0
    data_points_extractable: list[str] = Field(default_factory=list)
    assigned_to_agents: list[str] = Field(
        min_length=1,
        description="Every reference file must be assigned to at least one agent"
    )


class CountsJson(BaseModel):
    """Aggregate inventory counts. From SKILL.md section 2a."""
    total_files: int = 0
    total_customers: int = 0
    total_reference_files: int = 0
    files_by_extension: dict[str, int] = Field(default_factory=dict)
    files_by_group: dict[str, int] = Field(default_factory=dict)
    customers_by_group: dict[str, int] = Field(default_factory=dict)


class CustomerMention(BaseModel):
    """
    Customer-mention index entry. From SKILL.md section 2c.
    Records which customers are mentioned in which reference files.
    """
    customer_name: str
    customer_safe_name: str
    reference_files: list[str] = Field(default_factory=list)
    mention_count: int = 0


class CustomerMentionIndex(BaseModel):
    """Complete customer-mention index. Written to customer_mentions.json."""
    matches: list[CustomerMention] = Field(default_factory=list)
    unmatched_in_reference: list[str] = Field(
        default_factory=list,
        description="Names in reference files not matching any customer folder (ghost customers)"
    )
    customers_without_reference_data: list[str] = Field(
        default_factory=list,
        description="Customer folders with no mentions in any reference file (phantom contracts)"
    )


class ExtractionQualityEntry(BaseModel):
    """Extraction quality record for a single file. From SKILL.md section 1b."""
    file_path: str
    method: str                                 # ExtractionQualityMethod value
    bytes_extracted: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_chain: list[str] = Field(
        default_factory=list,
        description="Methods attempted in order"
    )
    failure_reasons: list[str] = Field(
        default_factory=list,
        description="Diagnostic strings for each gate failure in the chain"
    )
```

---

## Manifest Models

Source: `agent-prompts.md` section 4

```python
# src/dd_agents/models/manifest.py

from __future__ import annotations
from pydantic import BaseModel, Field


class FileRead(BaseModel):
    """File successfully read by an agent."""
    path: str
    extraction_quality: str                     # primary, fallback_pdftotext, etc.
    pages_read: str = "all"
    bytes_analyzed: int = 0


class FileSkipped(BaseModel):
    """File skipped by an agent with reason."""
    path: str
    reason: str                                 # FileSkipReason value
    reason_detail: str


class FileFailed(BaseModel):
    """File that failed extraction after full fallback chain."""
    path: str
    reason: str
    fallback_attempted: bool = True             # MUST be true; false = QA failure
    fallback_result: str = ""


class ManifestCustomer(BaseModel):
    """Per-customer tracking within the coverage manifest."""
    name: str
    files_assigned: list[str] = Field(default_factory=list)
    files_processed: list[str] = Field(default_factory=list)
    files_skipped: list[str] = Field(default_factory=list)
    status: str = "complete"                    # "complete" or "partial"


class CoverageManifest(BaseModel):
    """
    Agent coverage manifest. From agent-prompts.md section 4.
    Conforms to dd-framework/schemas/coverage-manifest.schema.json
    with forensic-dd customer-centric extensions.
    """
    agent: str                                  # AgentName value
    skill: str = "forensic-dd"
    run_id: str
    files_assigned: list[str] = Field(default_factory=list)
    files_read: list[FileRead] = Field(default_factory=list)
    files_skipped: list[FileSkipped] = Field(default_factory=list)
    files_failed: list[FileFailed] = Field(default_factory=list)
    coverage_pct: float = Field(ge=0.0, le=1.0)
    analysis_units_assigned: int = 0
    analysis_units_completed: int = 0
    customers: list[ManifestCustomer] = Field(default_factory=list)
    reference_files_processed: list[str] = Field(
        default_factory=list,
        description="Forensic-dd extension: reference file paths the agent analyzed"
    )
```

---

## File Header and Customer Output Models

Source: `domain-definitions.md` section 1, `agent-prompts.md` section 4c

```python
# src/dd_agents/models/finding.py (additional models in same file)


class CrossReferenceData(BaseModel):
    """Per-file cross-reference data extracted from document. From domain-definitions.md section 1."""
    contract_value: str | None = None
    pricing_terms: str | None = None
    term_dates: dict[str, str] | None = None    # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    payment_terms: str | None = None
    discount_pct: str | None = None


class FileHeader(BaseModel):
    """
    Per-file extraction header. From domain-definitions.md section 1.
    Recorded in the customer JSON for every file processed.
    """
    file_path: str
    text_path: str | None = None
    doc_type_guess: str                         # MSA, Order Form, SOW, Amendment, etc.
    effective_date_guess: str | None = None      # YYYY-MM-DD or None
    expiry_date_guess: str | None = None         # YYYY-MM-DD or None
    parties: list[str] = Field(default_factory=list)
    governed_by: str                            # File path, "SELF", or "UNRESOLVED"
    references_found: list[str] = Field(default_factory=list)
    content_summary: str = ""
    cross_reference_data: CrossReferenceData = Field(
        default_factory=CrossReferenceData
    )

    @field_validator("governed_by")
    @classmethod
    def validate_governed_by(cls, v: str) -> str:
        """
        Ensures governed_by is either a valid file path (contains '/' or '.'),
        "SELF", or "UNRESOLVED".
        """
        if v in ("SELF", "UNRESOLVED"):
            return v
        if "/" in v or "." in v:
            return v
        raise ValueError(
            f"governed_by must be a file path (contains '/' or '.'), "
            f"'SELF', or 'UNRESOLVED'. Got: '{v}'"
        )


class CrossReferenceSource(BaseModel):
    """Source location for a cross-reference data point."""
    file: str = ""
    page: int | str | None = None
    quote: str = ""
    tab: str | None = None
    row: str | None = None


class CrossReference(BaseModel):
    """
    Cross-reference entry comparing contract data vs reference data.
    From domain-definitions.md section 7a.
    """
    data_type: str = ""                         # financial, pricing, entity, operational
    data_point: str                             # "ARR", "Payment Terms", etc.
    contract_value: str = ""
    contract_source: CrossReferenceSource = Field(
        default_factory=CrossReferenceSource
    )
    reference_value: str = ""
    reference_source: CrossReferenceSource = Field(
        default_factory=CrossReferenceSource
    )
    match_status: str = ""                      # match, mismatch, not_available
    variance: str = ""                          # e.g., "-20.8%"
    severity: Severity | None = None
    interpretation: str = ""


class CrossReferenceSummary(BaseModel):
    """Per-customer cross-reference summary. From domain-definitions.md section 7f."""
    reference_files_checked: list[str] = Field(default_factory=list)
    data_points_compared: int = 0
    matches: int = 0
    mismatches: int = 0
    not_available: int = 0
    findings_generated: int = 0
    gaps_generated: int = 0
```

---

## Governance Models

Source: `domain-definitions.md` section 5

```python
# src/dd_agents/models/governance.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class GovernanceCitation(BaseModel):
    """Citation proving a governance relationship."""
    source_path: str = ""
    location: str = ""
    exact_quote: str = ""


class GovernanceEdge(BaseModel):
    """
    A directed edge in the governance graph.
    From domain-definitions.md section 5b.
    """
    from_file: str = Field(
        description="Source file path (the governed document)"
    )
    to_file: str = Field(
        description="Target file path (the governing document)"
    )
    link_reason: str = ""                       # "explicit reference", etc.
    relationship: str = ""                      # governs, amends, supersedes, references
    citation: GovernanceCitation = Field(default_factory=GovernanceCitation)


class GovernanceGraph(BaseModel):
    """
    Structured governance graph for a customer.
    From domain-definitions.md section 5b.

    IMPORTANT: This is a structured Pydantic model with an edges list,
    NOT a plain dict. This ensures type safety and validation throughout
    the pipeline.
    """
    edges: list[GovernanceEdge] = Field(default_factory=list)

    def get_governing_doc(self, file_path: str) -> str | None:
        """Return the governing document for a given file, or None."""
        for edge in self.edges:
            if edge.from_file == file_path:
                return edge.to_file
        return None

    def get_governed_docs(self, file_path: str) -> list[str]:
        """Return all documents governed by the given file."""
        return [edge.from_file for edge in self.edges if edge.to_file == file_path]

    def get_unresolved_files(self, all_files: list[str]) -> list[str]:
        """Return files that have no governance edge (not in any from_file)."""
        governed = {edge.from_file for edge in self.edges}
        # Files that are targets (governing docs) or self-governing don't need edges
        targets = {edge.to_file for edge in self.edges}
        return [f for f in all_files if f not in governed and f not in targets]

    def has_cycles(self) -> list[list[str]]:
        """Detect governance cycles. Returns list of cycle paths.

        NOTE: The production implementation should use
        networkx.simple_cycles() instead of this inline DFS. simple_cycles()
        handles disconnected components correctly (it finds cycles in all
        components, not just the largest connected component) and is more
        thoroughly tested for edge cases.
        """
        import networkx as nx

        G = nx.DiGraph()
        for edge in self.edges:
            G.add_edge(edge.from_file, edge.to_file)
        return [list(c) for c in nx.simple_cycles(G)]
```

---

## Customer Analysis Output Model

Source: `agent-prompts.md` section 4c

```python
# This is part of src/dd_agents/models/finding.py or a dedicated customer_output.py
# For organizational clarity, it lives alongside Finding models.


class CustomerAnalysis(BaseModel):
    """
    Per-customer output from each specialist agent.
    From agent-prompts.md section 4c.
    Written to {RUN_DIR}/findings/{agent}/{customer_safe_name}.json
    """
    customer: str                               # Canonical customer name
    customer_safe_name: str                     # Safe name per SKILL.md 1b convention
    agent: AgentName
    run_id: str
    timestamp: str                              # ISO-8601 completion timestamp
    files_analyzed: int                         # Count of files processed
    file_headers: list[FileHeader] = Field(default_factory=list)
    governance_graph: GovernanceGraph = Field(default_factory=GovernanceGraph)
    findings: list[AgentFinding] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    cross_reference_summary: CrossReferenceSummary | None = None
    diagrams: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    # Incremental mode fields in metadata:
    # _carried_forward: bool
    # _original_run_id: str
    # _consecutive_unchanged_runs: int
```

---

## Audit Models

Source: `SKILL.md` section 8, `agent-prompts.md` section 6e

```python
# src/dd_agents/models/audit.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class AuditEntry(BaseModel):
    """
    Single audit log entry (one JSONL line).
    From dd-framework/schemas/audit-entry.schema.json.
    """
    ts: str                                     # ISO-8601 timestamp
    agent: str                                  # Agent name
    skill: str = "forensic-dd"
    action: AuditAction
    target: str                                 # What was acted upon
    result: str                                 # Outcome
    details: str = ""


class AuditCheck(BaseModel):
    """
    Individual QA check result within the consolidated audit.
    Each check maps to one or more DoD items from section 9.
    """
    passed: bool
    dod_checks: list[int] = Field(default_factory=list)  # DoD check numbers
    details: dict = Field(default_factory=dict)
    rule: str = Field(
        default="",
        alias="_rule",
        description="Human-readable rule description"
    )

    model_config = ConfigDict(populate_by_name=True)


class AuditSummary(BaseModel):
    """Summary statistics within audit.json."""
    total_customers: int = 0
    total_files: int = 0
    total_findings: int = 0
    total_gaps: int = 0
    findings_by_severity: dict[str, int] = Field(
        default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    )
    gaps_by_priority: dict[str, int] = Field(
        default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    )
    clean_result_count: int = 0
    agents_producing_gaps: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    """
    Consolidated audit output. Written to {RUN_DIR}/audit.json.
    From SKILL.md section 8h.
    """
    audit_passed: bool
    timestamp: str                              # ISO-8601
    run_id: str
    checks: dict[str, AuditCheck] = Field(default_factory=dict)
    summary: AuditSummary = Field(default_factory=AuditSummary)


# --- Quality / Judge Models ---
# From agent-prompts.md section 6e, quality-score.schema.json


class SpotCheck(BaseModel):
    """
    Individual spot-check result from the Judge.
    From agent-prompts.md section 6e.
    """
    finding_id: str
    agent: str                                  # AgentName value
    analysis_unit: str                          # Customer name
    severity: str                               # Severity value
    dimension: SpotCheckDimension
    result: SpotCheckResult
    notes: str = ""


class Contradiction(BaseModel):
    """
    Inter-agent factual contradiction identified by the Judge.
    From agent-prompts.md section 6e.
    """
    analysis_unit: str                          # Customer name
    agents: list[str]                           # AgentName values
    fact_in_dispute: str
    resolution: str
    winning_agent: str                          # AgentName value


class AgentScoreDimensions(BaseModel):
    """Per-dimension scores for an agent. From agent-prompts.md section 6d."""
    citation_verification: int = Field(ge=0, le=100)
    contextual_validation: int = Field(ge=0, le=100)
    financial_accuracy: int = Field(ge=0, le=100)
    cross_agent_consistency: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)


class AgentScore(BaseModel):
    """
    Judge quality score for one agent.
    From agent-prompts.md section 6e.
    """
    model_config = ConfigDict(populate_by_name=True)

    score: int = Field(ge=0, le=100)
    findings_reviewed: int = 0
    findings_total: int = 0
    pass_count: int = Field(default=0, alias="pass")
    # NOTE: Using "pass" as a Pydantic alias is safe. Pydantic aliases are
    # string keys for serialization/deserialization, not Python identifiers.
    # The Python field name is `pass_count`; "pass" is only used in JSON I/O.
    partial: int = 0
    fail: int = 0
    dimensions: AgentScoreDimensions = Field(
        default_factory=AgentScoreDimensions
    )


class UnitScore(BaseModel):
    """Per-customer (analysis unit) quality score."""
    score: int = Field(ge=0, le=100)
    agents_reviewed: int = 0
    contradictions: int = 0


class QualityScores(BaseModel):
    """
    Complete Judge output file. Written to {RUN_DIR}/judge/quality_scores.json.
    Single file containing spot_checks and contradictions inline
    (NOT as separate files). From agent-prompts.md section 6e.
    """
    run_id: str
    skill: str = "forensic-dd"
    judge_config: dict = Field(default_factory=dict)
    agent_scores: dict[str, AgentScore] = Field(default_factory=dict)
    unit_scores: dict[str, UnitScore] = Field(default_factory=dict)
    overall_quality: int = Field(ge=0, le=100)
    iteration_round: int = 1
    agents_below_threshold: list[str] = Field(default_factory=list)
    spot_checks: list[SpotCheck] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
```

---

## Persistence Models

Source: `SKILL.md` sections 0c, 0e

```python
# src/dd_agents/models/persistence.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class RunMetadata(BaseModel):
    """
    Run metadata. Written to {RUN_DIR}/metadata.json.
    From SKILL.md step 3 (initialization) and step 32 (finalization).
    """
    run_id: str
    timestamp: str                              # ISO-8601
    skill: str = "forensic-dd"
    execution_mode: str                         # "full" or "incremental"
    config_hash: str                            # SHA-256 of deal-config.json
    framework_version: str = "unknown"
    cross_skill_run_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Map of skill name to run_id for cross-skill data"
    )
    # Finalization fields (added at step 32):
    file_checksums: dict[str, str] = Field(
        default_factory=dict,
        description="Per-customer SHA-256 map"
    )
    customer_assignments: dict[str, list[str]] = Field(
        default_factory=dict
    )
    finding_counts: dict[str, int] = Field(default_factory=dict)
    gap_counts: dict[str, int] = Field(default_factory=dict)
    agent_scores: dict[str, int] = Field(default_factory=dict)
    completion_status: str = "in_progress"      # in_progress, completed, failed
    batch_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of batch instances spawned per agent type"
    )


class CustomerClassEntry(BaseModel):
    """
    Per-customer classification for incremental mode.
    From SKILL.md section 0e.
    """
    customer: str
    customer_safe_name: str
    classification: CustomerClassificationStatus
    reason: str
    files_added: list[str] = Field(default_factory=list)
    files_removed: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    prior_checksum: str | None = None           # Required for all non-NEW
    current_checksum: str | None = None         # Required for all non-NEW
    consecutive_unchanged_runs: int = 0


class ClassificationSummary(BaseModel):
    """Summary counts by classification status."""
    new: int = 0
    changed: int = 0
    stale_refresh: int = 0
    unchanged: int = 0
    deleted: int = 0


class Classification(BaseModel):
    """
    Customer classification document for incremental mode.
    Written to {RUN_DIR}/classification.json.
    From SKILL.md section 0e.
    """
    run_id: str
    execution_mode: str                         # "incremental"
    prior_run_id: str | None = None
    classification_summary: ClassificationSummary = Field(
        default_factory=ClassificationSummary
    )
    customers: list[CustomerClassEntry] = Field(default_factory=list)


class AnalysisUnitCounts(BaseModel):
    """Analysis unit counts for run history."""
    total: int = 0
    analyzed: int = 0
    carried_forward: int = 0
    new: int = 0
    changed: int = 0
    stale_refresh: int = 0
    deleted: int = 0


class FindingCounts(BaseModel):
    """Finding counts for run history."""
    p0: int = 0
    p1: int = 0
    p2: int = 0
    p3: int = 0
    total: int = 0


class RunHistoryEntry(BaseModel):
    """
    Entry in _dd/run_history.json (shared across all DD skills).
    From SKILL.md step 33.
    """
    run_id: str
    skill: str = "forensic-dd"
    timestamp: str                              # ISO-8601
    execution_mode: str                         # "full" or "incremental"
    analysis_unit_counts: AnalysisUnitCounts = Field(
        default_factory=AnalysisUnitCounts
    )
    finding_counts: FindingCounts = Field(default_factory=FindingCounts)
    agent_scores: dict[str, int] = Field(default_factory=dict)
    judge_enabled: bool = False
    iteration_rounds: int = 0
```

---

## Entity Resolution Models

Source: `entity-resolution-protocol.md`

```python
# src/dd_agents/models/entity.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


class EntityMatch(BaseModel):
    """
    A confirmed entity match. From entity-resolution-protocol.md section 5.
    """
    source_name: str                            # Name as found in source
    source: str                                 # "database", "directory", "reference_file"
    matched_name: str                           # Name as found in target
    target: str                                 # "directory", "database", "reference_file"
    match_pass: int                             # 1-6 (which pass matched)
    match_method: str                           # "preprocessing", "exact", "alias_lookup",
                                                # "fuzzy", "tfidf", "parent_child"
    confidence: float = Field(ge=0.0, le=1.0)
    canonical_name: str                         # Resolved canonical name


class MatchAttempt(BaseModel):
    """Record of a single match pass attempt for an unmatched entity."""
    pass_num: int = Field(alias="pass")  # "pass" alias is safe; see AgentScore note
    method: str
    result: str                                 # "no_match", "below_threshold"
    best_candidate: str | None = None
    score: float | None = None

    model_config = ConfigDict(populate_by_name=True)


class UnmatchedEntity(BaseModel):
    """An entity that could not be matched after all 6 passes."""
    source_name: str
    source: str
    match_attempts: list[MatchAttempt] = Field(default_factory=list)
    resolution: str = "unmatched_gap_logged"


class RejectedMatch(BaseModel):
    """A match that was rejected (below threshold or on exclusion list)."""
    source_name: str
    source: str
    rejected_match: str
    match_pass: int
    score: float
    reason: str                                 # "below_threshold", "exclusion_list"


class EntityMatchLog(BaseModel):
    """
    Complete entity match log. Written to entity_matches.json.
    From entity-resolution-protocol.md section 5.
    """
    matches: list[EntityMatch] = Field(default_factory=list)
    unmatched: list[UnmatchedEntity] = Field(default_factory=list)
    rejected: list[RejectedMatch] = Field(default_factory=list)


class EntityCacheEntry(BaseModel):
    """
    Single entry in the PERMANENT entity resolution cache.
    From entity-resolution-protocol.md section 7.
    """
    canonical: str
    match_pass: int
    match_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    entity_type: str = "customer"
    first_seen_run: str
    last_confirmed_run: str
    confirmation_count: int = 1


class UnmatchedCacheEntry(BaseModel):
    """An unmatched entity persisted in the cache."""
    name: str
    context: str = ""
    first_seen_run: str


class EntityCacheConfigSnapshot(BaseModel):
    """Snapshot of entity_aliases config for per-entry invalidation diff."""
    canonical_to_variants: dict[str, list[str]] = Field(default_factory=dict)
    short_name_guard: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    parent_child: dict[str, list[str]] = Field(default_factory=dict)


class EntityCache(BaseModel):
    """
    PERMANENT tier entity resolution cache.
    Written to _dd/entity_resolution_cache.json.
    From entity-resolution-protocol.md section 7.
    """
    version: int = 1
    last_updated: str                           # ISO-8601
    last_updated_by: str = "forensic-dd"
    last_updated_run_id: str
    config_hash: str                            # SHA-256 of entity_aliases section
    prior_config_snapshot: EntityCacheConfigSnapshot = Field(
        default_factory=EntityCacheConfigSnapshot
    )
    entries: dict[str, EntityCacheEntry] = Field(default_factory=dict)
    unmatched: list[UnmatchedCacheEntry] = Field(default_factory=list)
```

---

## Numerical Validation Models

Source: `numerical-validation.md`

```python
# src/dd_agents/models/numerical.py

from __future__ import annotations
from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    """
    A single traceable number in the numerical manifest.
    From numerical-validation.md section 1.
    """
    id: str                                     # N001, N002, ...
    label: str                                  # total_customers, total_files, etc.
    value: int | float
    source_file: str                            # Path to source data
    derivation: str                             # How the number was computed
    used_in: list[str] = Field(default_factory=list)  # Where it appears in outputs
    cross_check: str = ""                       # Cross-source validation expression
    verified: bool = False                      # Set to True after validation passes


class NumericalManifest(BaseModel):
    """
    Complete numerical manifest. Written to {RUN_DIR}/numerical_manifest.json.
    From numerical-validation.md section 1.
    Must contain at minimum entries N001-N010.
    """
    manifest_version: str = "1.0"
    generated_at: str                           # ISO-8601
    numbers: list[ManifestEntry] = Field(
        default_factory=list,
        min_length=10,
        description="Must contain at minimum N001-N010"
    )
```

---

## Reporting Models

Source: `report_schema.json`

```python
# src/dd_agents/models/reporting.py

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Any


class SeverityColor(BaseModel):
    """Color definition for a severity level."""
    bg: str                                     # Hex color code
    font: str                                   # Hex color code


class GlobalFormatting(BaseModel):
    """Global Excel formatting settings. From report_schema.json."""
    header_bold: bool = True
    header_bg_color: str = "#4472C4"
    header_font_color: str = "#FFFFFF"
    header_font_size: int = 11
    body_font_size: int = 10
    freeze_panes: bool = True
    freeze_row: int = 1
    auto_filter: bool = True
    auto_fit_widths: bool = True
    max_column_width: int = 80
    severity_colors: dict[str, SeverityColor] = Field(default_factory=dict)
    status_colors: dict[str, SeverityColor] = Field(default_factory=dict)


class ColumnDef(BaseModel):
    """Single column definition within a sheet. From report_schema.json."""
    name: str
    key: str
    type: str                                   # string, integer, date, currency, percentage, etc.
    width: int = 20
    format: str | None = None                   # Excel format string
    activation_condition: str | None = None
    field_mapping: str | None = Field(
        default=None, alias="_field_mapping"
    )
    note: str | None = Field(default=None, alias="_note")
    algorithm: str | None = Field(default=None, alias="_algorithm")
    derivation: str | None = Field(default=None, alias="_derivation")

    model_config = ConfigDict(populate_by_name=True)


class SortOrder(BaseModel):
    """Sort specification for a sheet."""
    column: str
    direction: str = "asc"                      # "asc" or "desc"


class ConditionalFormat(BaseModel):
    """Conditional formatting rule for a column."""
    column: str
    rule: str                                   # e.g., "> 0", "== P0", "contains active"
    format: SeverityColor


class SummaryFormulaEntry(BaseModel):
    """Individual formula entry within a summary row."""
    column: str
    value: str | None = None                    # Static text value
    formula: str | None = None                  # Pseudo-formula (SUM, COUNTIF, etc.)


class SheetDef(BaseModel):
    """
    Complete sheet definition. From report_schema.json.
    Each sheet has columns, sort order, conditional formatting, and activation rules.
    """
    name: str
    required: bool = True
    activation_condition: str = "always"
    description: str = ""
    source: str = ""
    source_note: str | None = Field(default=None, alias="_source_note")
    field_mapping: str | None = Field(default=None, alias="_field_mapping")
    row_rule: str = ""
    columns: list[ColumnDef] = Field(default_factory=list)
    sort_order: list[SortOrder] = Field(default_factory=list)
    conditional_formatting: list[ConditionalFormat] = Field(default_factory=list)
    summary_formulas: dict[str, list[SummaryFormulaEntry]] = Field(
        default_factory=dict
    )

    model_config = ConfigDict(populate_by_name=True)


class ReportSchema(BaseModel):
    """
    Machine-readable report schema. Loaded from report_schema.json.
    From reporting-protocol.md section 3.
    """
    schema_version: str                         # Semver
    description: str = ""
    global_formatting: GlobalFormatting = Field(default_factory=GlobalFormatting)
    sheets: list[SheetDef] = Field(default_factory=list)


class ReportDiffChange(BaseModel):
    """Single change entry in the report diff. From reporting-protocol.md section 4."""
    change_type: str                            # new_finding, resolved_finding,
                                                # changed_severity, new_gap, resolved_gap,
                                                # new_customer, removed_customer
    customer: str
    finding_summary: str = ""
    prior_severity: str | None = None
    current_severity: str | None = None
    details: str = ""


class ReportDiffSummary(BaseModel):
    """Summary counts for the report diff."""
    new_findings: int = 0
    resolved_findings: int = 0
    changed_severity: int = 0
    new_gaps: int = 0
    resolved_gaps: int = 0
    new_customers: int = 0
    removed_customers: int = 0


class ReportDiff(BaseModel):
    """
    Report diff comparing current vs prior run.
    Written to {RUN_DIR}/report_diff.json.
    From reporting-protocol.md section 4.

    Both current_run_id and prior_run_id are required so that diffs
    can be traced back to specific runs in the run history.
    """
    current_run_id: str = Field(
        description="Run ID of the current (newer) run"
    )
    prior_run_id: str = Field(
        description="Run ID of the prior (older) run being compared against"
    )
    summary: ReportDiffSummary = Field(default_factory=ReportDiffSummary)
    changes: list[ReportDiffChange] = Field(default_factory=list)


class ContractDateReconciliationEntry(BaseModel):
    """
    Single customer entry in contract date reconciliation.
    From reporting-protocol.md section 5.
    """
    customer: str
    database_end_date: str = ""                 # YYYY-MM-DD
    actual_end_date: str = ""                   # YYYY-MM-DD
    arr: float = 0.0
    status: str = ""                            # Active-Database Stale, Active-Auto-Renewal,
                                                # Likely Active-Needs Confirmation,
                                                # Expired-Confirmed, Expired-No Contracts
    evidence: str = ""
    evidence_file: str = ""


class ContractDateReconciliation(BaseModel):
    """
    Complete contract date reconciliation document.
    Written to {RUN_DIR}/contract_date_reconciliation.json.
    From SKILL.md section 5.
    """
    run_id: str
    generated_at: str                           # ISO-8601
    entries: list[ContractDateReconciliationEntry] = Field(default_factory=list)
    total_reclassified_arr: float = 0.0
    total_expired_arr: float = 0.0
```

---

## Merged Customer Output Model

Used by the Reporting Lead after merging findings from all 4 agents.

```python
# This model can live in src/dd_agents/models/finding.py or reporting section


class MergedCustomerOutput(BaseModel):
    """
    Merged per-customer output. Written to {RUN_DIR}/findings/merged/{customer_safe_name}.json.
    From reporting-protocol.md section 1.
    """
    customer: str
    customer_safe_name: str
    findings: list[Finding] = Field(
        default_factory=list,
        description="Fully transformed findings conforming to finding.schema.json"
    )
    cross_references: list[CrossReference] = Field(default_factory=list)
    cross_reference_summary: CrossReferenceSummary | None = None
    governance_graph: GovernanceGraph = Field(default_factory=GovernanceGraph)
    governance_resolved_pct: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="(files with governed_by in [file_path, SELF]) / total_customer_files"
    )
```

---

## Model Validation Summary

| Model | Key Validators |
|-------|---------------|
| `DealConfig.config_version` | Pattern `^\d+\.\d+\.\d+$`, minimum version >= 1.0.0 |
| `Finding.id` | Pattern `^[a-z][a-z0-9-]*_[a-z][a-z0-9_-]*_\d{4,}$` |
| `Finding.citations` | P0/P1 require `exact_quote` on all citations |
| `Finding.title` | Max length 120 characters |
| `Gap.missing_item` | Max length 200 characters |
| `Citation` | `web_research` source_type requires `access_date` |
| `Citation.exact_quote` | Typed as `str \| None`. OMIT entirely for clean-result findings (do not set to null). Serialize with `exclude_none=True`. |
| `FileHeader.governed_by` | Must be a file path (contains `/` or `.`), `"SELF"`, or `"UNRESOLVED"` |
| `GovernanceGraph` | Structured Pydantic model with `edges: list[GovernanceEdge]`, NOT a plain dict |
| `CoverageManifest.coverage_pct` | `ge=0.0, le=1.0` |
| `AgentScore.score` | `ge=0, le=100` |
| `EntityCacheEntry.confidence` | `ge=0.0, le=1.0` |
| `NumericalManifest.numbers` | `min_length=10` (entries N001-N010 required) |
| `AcquiredEntity.acquisition_date` | YYYY-MM-DD regex pattern |
| `ReferenceFile.assigned_to_agents` | `min_length=1` (every ref file must have at least one agent) |

---

## Serialization Conventions

1. **`exclude_none=True`** is the default serialization mode for all models that produce JSON output files. This ensures optional fields are omitted rather than set to null, which is critical for `Citation.exact_quote` in clean-result findings.

2. **`populate_by_name=True`** is set on models that use `Field(alias=...)` (e.g., `AgentScore.pass_count` aliased from `"pass"`, `AuditCheck.rule` aliased from `"_rule"`).

3. **`extra="allow"`** is set on configuration models (`DealConfig`, `BuyerInfo`, `TargetInfo`, etc.) to permit future config fields without breaking deserialization.

4. **All enum values are strings.** Every enum inherits from `(str, Enum)` for JSON compatibility.

5. **Dates are ISO-8601 strings**, not `datetime` objects. This matches the source JSON schemas and avoids timezone ambiguity.
