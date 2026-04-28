"""dd_agents.models subpackage -- re-exports all model classes for convenient imports."""

from __future__ import annotations

# Audit
from dd_agents.models.audit import (
    AgentScore,
    AgentScoreDimensions,
    AuditCheck,
    AuditEntry,
    AuditReport,
    AuditSummary,
    Contradiction,
    QualityScores,
    SpotCheck,
    UnitScore,
)

# Config
from dd_agents.models.config import (
    AcquiredEntity,
    ActiveFilter,
    AgentCustomization,
    BuyerInfo,
    BuyerStrategy,
    DealConfig,
    DealInfo,
    EntityAliases,
    ExecutionConfig,
    ExtractionConfig,
    ForensicDDConfig,
    JudgeConfig,
    KeyExecutive,
    PreviousName,
    ReportingConfig,
    SamplingRates,
    SourceOfTruth,
    SpecialistsConfig,
    SubjectDatabase,
    SubjectDatabaseColumns,
    TargetInfo,
)

# Entity
from dd_agents.models.entity import (
    EntityCache,
    EntityCacheConfigSnapshot,
    EntityCacheEntry,
    EntityMatch,
    EntityMatchLog,
    MatchAttempt,
    RejectedMatch,
    UnmatchedCacheEntry,
    UnmatchedEntity,
)

# Enums
from dd_agents.models.enums import (
    AgentName,
    AuditAction,
    CompletionStatus,
    Confidence,
    DealType,
    DetectionMethod,
    ExecutionMode,
    ExtractionQualityMethod,
    FileSkipReason,
    GapType,
    GovernanceRelationship,
    MatchStatus,
    ReferenceFileCategory,
    Severity,
    SourceType,
    SpotCheckDimension,
    SpotCheckResult,
    SubjectClassificationStatus,
)

# Finding
from dd_agents.models.finding import (
    AgentFinding,
    BoundingBox,
    Citation,
    CrossReference,
    CrossReferenceData,
    CrossReferenceSource,
    CrossReferenceSummary,
    FileHeader,
    Finding,
    Gap,
    MergedSubjectOutput,
    SubjectAnalysis,
)

# Governance
from dd_agents.models.governance import (
    GovernanceCitation,
    GovernanceEdge,
    GovernanceGraph,
)

# Inventory
from dd_agents.models.inventory import (
    CountsJson,
    ExtractionQualityEntry,
    FileEntry,
    ReferenceFile,
    SubjectEntry,
    SubjectMention,
    SubjectMentionIndex,
)

# Manifest
from dd_agents.models.manifest import (
    CoverageManifest,
    FileFailed,
    FileRead,
    FileSkipped,
    ManifestSubject,
)

# Numerical
from dd_agents.models.numerical import (
    ManifestEntry,
    NumericalManifest,
)

# Persistence
from dd_agents.models.persistence import (
    AnalysisUnitCounts,
    Classification,
    ClassificationSummary,
    FindingCounts,
    RunHistoryEntry,
    RunMetadata,
    SubjectClassEntry,
)

# Reporting
from dd_agents.models.reporting import (
    ColumnDef,
    ConditionalFormat,
    ContractDateReconciliation,
    ContractDateReconciliationEntry,
    GlobalFormatting,
    ReportDiff,
    ReportDiffChange,
    ReportDiffSummary,
    ReportSchema,
    SeverityColor,
    SheetDef,
    SortOrder,
    SummaryFormulaEntry,
)

# Search
from dd_agents.models.search import (
    SearchCitation,
    SearchColumn,
    SearchColumnResult,
    SearchPrompts,
    SearchSubjectResult,
)

__all__ = [
    # Enums
    "AgentName",
    "AuditAction",
    "CompletionStatus",
    "Confidence",
    "SubjectClassificationStatus",
    "DealType",
    "DetectionMethod",
    "ExecutionMode",
    "ExtractionQualityMethod",
    "FileSkipReason",
    "GapType",
    "GovernanceRelationship",
    "MatchStatus",
    "ReferenceFileCategory",
    "Severity",
    "SourceType",
    "SpotCheckDimension",
    "SpotCheckResult",
    # Config
    "ActiveFilter",
    "AcquiredEntity",
    "AgentCustomization",
    "BuyerInfo",
    "BuyerStrategy",
    "SubjectDatabase",
    "SubjectDatabaseColumns",
    "DealConfig",
    "DealInfo",
    "SpecialistsConfig",
    "EntityAliases",
    "ExecutionConfig",
    "ExtractionConfig",
    "ForensicDDConfig",
    "JudgeConfig",
    "KeyExecutive",
    "PreviousName",
    "ReportingConfig",
    "SamplingRates",
    "SourceOfTruth",
    "TargetInfo",
    # Governance
    "GovernanceCitation",
    "GovernanceEdge",
    "GovernanceGraph",
    # Finding
    "AgentFinding",
    "BoundingBox",
    "Citation",
    "CrossReference",
    "CrossReferenceData",
    "CrossReferenceSource",
    "CrossReferenceSummary",
    "SubjectAnalysis",
    "FileHeader",
    "Finding",
    "Gap",
    "MergedSubjectOutput",
    # Inventory
    "CountsJson",
    "SubjectEntry",
    "SubjectMention",
    "SubjectMentionIndex",
    "ExtractionQualityEntry",
    "FileEntry",
    "ReferenceFile",
    # Manifest
    "CoverageManifest",
    "FileFailed",
    "FileRead",
    "FileSkipped",
    "ManifestSubject",
    # Audit
    "AgentScore",
    "AgentScoreDimensions",
    "AuditCheck",
    "AuditEntry",
    "AuditReport",
    "AuditSummary",
    "Contradiction",
    "QualityScores",
    "SpotCheck",
    "UnitScore",
    # Persistence
    "AnalysisUnitCounts",
    "Classification",
    "ClassificationSummary",
    "SubjectClassEntry",
    "FindingCounts",
    "RunHistoryEntry",
    "RunMetadata",
    # Entity
    "EntityCache",
    "EntityCacheConfigSnapshot",
    "EntityCacheEntry",
    "EntityMatch",
    "EntityMatchLog",
    "MatchAttempt",
    "RejectedMatch",
    "UnmatchedCacheEntry",
    "UnmatchedEntity",
    # Numerical
    "ManifestEntry",
    "NumericalManifest",
    # Reporting
    "ColumnDef",
    "ConditionalFormat",
    "ContractDateReconciliation",
    "ContractDateReconciliationEntry",
    "GlobalFormatting",
    "ReportDiff",
    "ReportDiffChange",
    "ReportDiffSummary",
    "ReportSchema",
    "SeverityColor",
    "SheetDef",
    "SortOrder",
    "SummaryFormulaEntry",
    # Search
    "SearchCitation",
    "SearchColumn",
    "SearchColumnResult",
    "SearchSubjectResult",
    "SearchPrompts",
]
