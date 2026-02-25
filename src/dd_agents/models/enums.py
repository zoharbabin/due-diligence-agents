from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Finding severity / gap priority. From domain-definitions.md section 3."""

    P0 = "P0"  # Deal-stopper: could block or unwind the acquisition
    P1 = "P1"  # Critical: material risk requiring pre-close negotiation
    P2 = "P2"  # Important: post-close attention needed
    P3 = "P3"  # Minor: informational, admin gaps, domain_reviewed_no_issues


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceType(StrEnum):
    FILE = "file"
    URL = "url"
    REFERENCE_FILE = "reference_file"
    DATABASE = "database"
    WEB_RESEARCH = "web_research"


class AgentName(StrEnum):
    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"


class GapType(StrEnum):
    """Gap type enum. From domain-definitions.md section 6d."""

    MISSING_DOC = "Missing_Doc"  # Referenced/expected document absent
    MISSING_DATA = "Missing_Data"  # Doc exists but key fields blank/redacted
    AMBIGUOUS_LINK = "Ambiguous_Link"  # Governance unresolvable
    UNREADABLE = "Unreadable"  # OCR and Read both failed
    CONTRADICTION = "Contradiction"  # Conflicting terms across docs
    DATA_MISMATCH = "Data_Mismatch"  # Contract terms contradict reference data


class DetectionMethod(StrEnum):
    """How a gap was detected. From domain-definitions.md section 6d."""

    CROSS_REFERENCE = "cross_reference"
    CROSS_REFERENCE_GHOST = "cross_reference_ghost"
    CROSS_REFERENCE_PHANTOM = "cross_reference_phantom"
    CROSS_REFERENCE_MISMATCH = "cross_reference_mismatch"
    PATTERN_CHECK = "pattern_check"
    CHECKLIST = "checklist"
    GOVERNANCE_RESOLUTION = "governance_resolution"


class AuditAction(StrEnum):
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


class SpotCheckDimension(StrEnum):
    """Judge spot-check dimensions. From quality-score.schema.json."""

    CITATION_VERIFICATION = "citation_verification"
    CONTEXTUAL_VALIDATION = "contextual_validation"
    FINANCIAL_ACCURACY = "financial_accuracy"
    CROSS_AGENT_CONSISTENCY = "cross_agent_consistency"
    COMPLETENESS = "completeness"


class SpotCheckResult(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class CustomerClassificationStatus(StrEnum):
    """Incremental mode classification. From SKILL.md section 0e."""

    NEW = "NEW"
    CHANGED = "CHANGED"
    STALE_REFRESH = "STALE_REFRESH"
    UNCHANGED = "UNCHANGED"
    DELETED = "DELETED"


class ExtractionQualityMethod(StrEnum):
    """Extraction method used for a file."""

    PRIMARY = "primary"  # markitdown succeeded
    FALLBACK_PDFTOTEXT = "fallback_pdftotext"
    FALLBACK_OCR = "fallback_ocr"
    FALLBACK_READ = "fallback_read"
    DIRECT_READ = "direct_read"  # Plaintext read directly
    FAILED = "failed"  # All methods failed


class FileSkipReason(StrEnum):
    """Reasons for skipping a file in the manifest."""

    OUTSIDE_AGENT_SCOPE = "outside_agent_scope"
    DUPLICATE_CONTENT = "duplicate_content"
    NON_CONTRACT_MATERIAL = "non_contract_material"
    AGENT_CAPACITY_LIMIT = "agent_capacity_limit"
    OTHER = "other"


class GovernanceRelationship(StrEnum):
    """Types of governance relationships between documents."""

    GOVERNS = "governs"
    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"


class DealType(StrEnum):
    """Deal type enum from deal-config.schema.json."""

    ACQUISITION = "acquisition"
    MERGER = "merger"
    DIVESTITURE = "divestiture"
    INVESTMENT = "investment"
    JOINT_VENTURE = "joint_venture"
    OTHER = "other"


class ExecutionMode(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class CompletionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ReferenceFileCategory(StrEnum):
    FINANCIAL = "Financial"
    PRICING = "Pricing"
    CORPORATE_LEGAL = "Corporate/Legal"
    OPERATIONAL = "Operational"
    SALES = "Sales"
    COMPLIANCE = "Compliance"
    HR = "HR"
    OTHER = "Other"
