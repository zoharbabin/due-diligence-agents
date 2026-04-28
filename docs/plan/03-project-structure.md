# 03 -- Project Structure

> **Historical note**: This document references `agents/reporting_lead.py` which was removed in v0.4.0. Step 23 is now deterministic pre-merge validation (`validation/pre_merge.py`). See `06-agents.md` §11.

## Repository Layout

```
due-diligence-agents/
├── pyproject.toml
├── README.md
├── CLAUDE.md                         # Claude Code instructions
├── CONTRIBUTING.md                   # Development setup, code style, PR process
├── CHANGELOG.md                      # Version history
├── docs/history/                     # Archived planning docs (build complete)
├── Dockerfile                        # Multi-stage Docker build
├── .github/workflows/
│   ├── ci.yml                        # CI pipeline (lint, types, tests, build)
│   └── release.yml                   # Release pipeline (PyPI, Docker, GitHub Release)
├── src/
│   └── dd_agents/
│       ├── __init__.py
│       ├── cli.py                    # Click CLI entry point (15 commands)
│       ├── cli_auto_config.py        # Auto-config command implementation
│       ├── cli_init.py               # Interactive init command implementation
│       ├── cli_logging.py            # Logging configuration for CLI
│       ├── config.py                 # DealConfig loader + validation
│       ├── errors.py                 # Custom exceptions + error taxonomy
│       ├── assessment.py             # Quick-assess data room analysis
│       ├── net_safety.py             # Network safety checks
│       ├── models/
│       │   ├── __init__.py
│       │   ├── enums.py              # Shared enums (Severity, Confidence, AgentName, etc.)
│       │   ├── config.py             # DealConfig, BuyerInfo, TargetInfo, etc.
│       │   ├── finding.py            # Finding, Citation, Gap models
│       │   ├── inventory.py          # SubjectEntry, FileEntry, ReferenceFile
│       │   ├── manifest.py           # CoverageManifest, FileRead, FileSkipped
│       │   ├── audit.py              # AuditEntry, AuditReport, QualityScores
│       │   ├── persistence.py        # RunMetadata, Classification, RunHistory
│       │   ├── reporting.py          # ReportSchema, SheetDef, ColumnDef
│       │   ├── entity.py             # EntityMatch, EntityCache, MatchLog
│       │   ├── governance.py         # GovernanceEdge, GovernanceGraph
│       │   ├── numerical.py          # NumericalManifest, ManifestEntry
│       │   ├── ontology.py           # Contract ontology (ClauseNode, Obligation, etc.)
│       │   ├── project.py            # ProjectEntry, ProjectRegistry (multi-project)
│       │   └── search.py             # SearchPrompts, SearchColumnResult, SearchCitation
│       ├── orchestrator/
│       │   ├── __init__.py
│       │   ├── engine.py             # Main pipeline engine (35 steps)
│       │   ├── steps.py              # PipelineStep enum (all 35 steps)
│       │   ├── state.py              # PipelineState dataclass
│       │   ├── checkpoints.py        # Checkpoint save/restore
│       │   ├── team.py               # Agent team management
│       │   ├── batch_scheduler.py    # Subject batching by complexity
│       │   ├── precedence.py         # Document precedence index builder
│       │   └── progress.py           # Progress tracking utilities
│       │   # NOTE: Steps are implemented as async methods on the PipelineEngine
│       │   # class in engine.py, not as individual files.
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py               # BaseAgentRunner (common spawn logic)
│       │   ├── prompt_builder.py     # Prompt builder (assembles from templates)
│       │   ├── prompt_templates.py   # Prompt template strings
│       │   ├── specialists.py        # Legal, Finance, Commercial, ProductTech
│       │   ├── judge.py              # Judge agent with iteration loop
│       │   ├── executive_synthesis.py # Executive Synthesis agent
│       │   ├── red_flag_scanner.py   # Red Flag Scanner agent
│       │   ├── acquirer_intelligence.py # Acquirer Intelligence agent
│       │   └── cost_tracker.py       # Model profiles + cost tracking
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── _constants.py         # Shared extension sets + confidence constants
│       │   ├── _helpers.py           # Shared read_text() helper
│       │   ├── pipeline.py           # Extraction orchestrator (pre-inspection + fallback chains)
│       │   ├── backend.py            # Backend selection logic
│       │   ├── markitdown.py         # markitdown wrapper (Office + PDF)
│       │   ├── ocr.py                # OCR fallback (pytesseract)
│       │   ├── ocr_registry.py       # OCR backend registry
│       │   ├── glm_ocr.py            # GLM-OCR vision-language model (mlx-vlm / Ollama)
│       │   ├── layout_pdf.py         # PDF layout analysis
│       │   ├── coordinates.py        # TextBlock coordinate model
│       │   ├── language_detect.py    # Document language detection
│       │   ├── cache.py              # Checksum-based cache
│       │   ├── quality.py            # ExtractionQuality tracker
│       │   └── reference_downloader.py  # External T&C URL download
│       ├── entity_resolution/
│       │   ├── __init__.py
│       │   ├── matcher.py            # 6-pass cascading matcher
│       │   ├── cache.py              # PERMANENT tier cache
│       │   ├── safe_name.py          # subject_safe_name convention
│       │   ├── dedup.py              # Entity deduplication
│       │   └── logging.py            # Match logging (entity_matches.json)
│       ├── inventory/
│       │   ├── __init__.py
│       │   ├── discovery.py          # File discovery (tree, files, file_types)
│       │   ├── subjects.py          # Subject registry builder
│       │   ├── reference_files.py    # Reference file classifier + router
│       │   ├── mentions.py           # Subject-mention index
│       │   └── integrity.py          # Inventory integrity verifier
│       ├── validation/
│       │   ├── __init__.py
│       │   ├── coverage.py           # Coverage gate (step 17)
│       │   ├── numerical_audit.py    # 6-layer numerical audit
│       │   ├── qa_audit.py           # Full QA audit (18 checks, step 28 blocking gate)
│       │   ├── dod.py                # 31 Definition of Done checks (step 35 non-blocking)
│       │   ├── pre_merge.py          # Pre-merge validation (step 23)
│       │   └── schema_validator.py   # Report schema validation
│       ├── reporting/
│       │   ├── __init__.py
│       │   ├── merge.py              # Finding merge + dedup
│       │   ├── diff.py               # Report diff (vs prior run)
│       │   ├── excel.py              # Excel generation from schema
│       │   ├── contract_dates.py     # Contract date reconciliation
│       │   ├── computed_metrics.py   # Derived analytics (noise/DQ classification, trends)
│       │   ├── templates.py          # Configurable report templates
│       │   ├── clause_library.py     # Clause library analysis
│       │   ├── export.py             # Report export utilities
│       │   ├── pdf_export.py         # HTML-to-PDF export (playwright/weasyprint)
│       │   ├── html.py               # HTML report orchestrator
│       │   ├── html_base.py          # SectionRenderer base class + shared helpers
│       │   ├── html_dashboard.py     # Executive dashboard section
│       │   ├── html_executive.py     # Executive summary section
│       │   ├── html_findings_table.py # Sortable findings table
│       │   ├── html_subjects.py     # Per-entity detail section
│       │   ├── html_gaps.py          # Missing documents / gaps section
│       │   ├── html_cross.py         # Cross-reference section
│       │   ├── html_cross_domain.py  # Cross-domain correlation section
│       │   ├── html_governance.py    # Governance graph section
│       │   ├── html_financial.py     # Financial analysis section
│       │   ├── html_risk.py          # Risk matrix section
│       │   ├── html_analysis.py      # Deep analysis section
│       │   ├── html_compliance.py    # Compliance section
│       │   ├── html_domains.py       # Domain coverage section
│       │   ├── html_entity.py        # Entity resolution section
│       │   ├── html_quality.py       # Quality metrics section
│       │   ├── html_methodology.py   # Methodology section
│       │   ├── html_diff.py          # Run-over-run diff section
│       │   ├── html_timeline.py      # Contract timeline section
│       │   ├── html_renewal.py       # Renewal analysis section
│       │   ├── html_discount.py      # Discount analysis section
│       │   ├── html_liability.py     # Liability section
│       │   ├── html_ip_risk.py       # IP risk section
│       │   ├── html_key_employee.py  # Key employee risk section
│       │   ├── html_product_adoption.py # Product adoption section
│       │   ├── html_saas_metrics.py  # SaaS metrics section
│       │   ├── html_tech_stack.py    # Tech stack section
│       │   ├── html_valuation.py     # Valuation section
│       │   ├── html_strategy.py      # Buyer strategy section
│       │   ├── html_red_flags.py     # Red flags summary section
│       │   ├── html_recommendations.py # Recommendations section
│       │   ├── html_clause_library.py # Clause library section
│       │   └── html_integration_playbook.py # Integration playbook section
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── tiers.py              # Three-tier lifecycle manager
│       │   ├── run_manager.py        # Run initialization + finalization
│       │   ├── incremental.py        # Subject classification + carry-forward
│       │   ├── concurrency.py        # File locking utilities
│       │   └── project_registry.py   # Multi-project registry manager
│       ├── hooks/
│       │   ├── __init__.py
│       │   ├── factory.py            # Hook builder factory
│       │   ├── pre_tool.py           # PreToolUse hooks
│       │   ├── post_tool.py          # PostToolUse hooks (JSON validation)
│       │   └── stop.py               # Stop hooks (coverage gate)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── server.py             # Legacy MCP server setup
│       │   ├── mcp_server.py         # MCP server with @tool decorator wrappers
│       │   ├── validate_finding.py   # validate_finding tool
│       │   ├── validate_gap.py       # validate_gap tool
│       │   ├── validate_manifest.py  # validate_manifest tool
│       │   ├── verify_citation.py    # verify_citation tool
│       │   ├── get_subject_files.py # get_subject_files tool
│       │   ├── resolve_entity.py     # resolve_entity tool
│       │   ├── report_progress.py    # report_progress tool
│       │   ├── read_office.py        # read_office tool (Office doc extraction)
│       │   ├── search_similar.py     # search_similar tool (vector search)
│       │   └── web_research.py       # web_research tool (google-researcher-mcp)
│       ├── search/
│       │   ├── __init__.py
│       │   ├── runner.py             # Search orchestration (CLI entry point)
│       │   ├── analyzer.py           # Multi-phase search analyzer (map/merge/synthesis/validation)
│       │   ├── chunker.py            # Page-aware document chunking
│       │   ├── citation_verifier.py  # Citation accuracy verification
│       │   └── excel_writer.py       # Search results Excel export
│       ├── precedence/               # Document precedence engine (Issue #163)
│       │   ├── __init__.py
│       │   ├── folder_priority.py    # Folder tier classification
│       │   ├── version_chains.py     # Version chain detection
│       │   └── scorer.py             # Precedence score calculation
│       ├── reasoning/                # Contract knowledge graph (Issue #152)
│       │   ├── __init__.py
│       │   └── contract_graph.py     # NetworkX-based contract graph
│       ├── query/                    # Interactive findings query
│       │   ├── __init__.py
│       │   ├── indexer.py            # Finding index builder
│       │   └── engine.py             # Query engine
│       ├── testing/                  # Test utilities
│       │   ├── __init__.py
│       │   └── data_generator.py     # Synthetic data room generator
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── constants.py          # Path constants, severity enums, shared config
│       │   └── naming.py             # subject_safe_name + Unicode transliteration
│       └── vector_store/
│           ├── __init__.py
│           ├── store.py              # ChromaDB wrapper (optional)
│           └── embeddings.py         # Embedding generation
├── tests/
│   ├── conftest.py
│   ├── fixtures/                     # Test data room, sample configs
│   ├── unit/                         # ~3,267 unit tests
│   ├── integration/                  # ~17 integration tests
│   └── e2e/                          # E2E tests (requires API key)
├── config/
│   ├── deal-config.template.json     # Template (copy from skill)
│   ├── deal-config.schema.json       # JSON Schema (copy from skill)
│   └── report_schema.json            # Report schema (copy from skill)
└── docs/
    ├── plan/                         # 24 spec docs
    ├── user-guide/                   # End-user documentation
    └── search-guide.md               # Search module guide
```

---

## Module Descriptions

### Top-Level Package (`src/dd_agents/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Package root. Exports version string and key public classes. |
| `cli.py` | Click CLI entry point. 15 commands: run, validate, version, init, auto-config, search, assess, export-pdf, query, portfolio (group), templates (group), log, annotate, lineage, health. |
| `cli_auto_config.py` | Auto-config command implementation. Uses Claude to analyze data room structure and generate deal config. |
| `cli_init.py` | Interactive init command implementation. Walks through config fields with prompts. |
| `cli_logging.py` | Logging configuration for CLI (log levels, formatting, file handlers). |
| `config.py` | Loads `deal-config.json`, validates against Pydantic `DealConfig` model, and provides a typed `DealConfig` object to the rest of the system. |
| `errors.py` | Custom exceptions and error taxonomy: `ErrorSeverity`, `ErrorCategory`, `PipelineErrorRecord`, `ConfigurationError`, `ExtractionError`, `AgentOutputParseError`, `PipelineValidationError`. |
| `assessment.py` | Quick-assess data room analysis for the `dd-agents assess` command. |
| `net_safety.py` | Network safety checks for external URL access. |

### Models (`src/dd_agents/models/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Re-exports all model classes for convenient `from dd_agents.models import ...` imports. |
| `config.py` | Pydantic v2 models for the deal configuration hierarchy: `DealConfig`, `BuyerInfo`, `TargetInfo`, `PreviousName`, `AcquiredEntity`, `EntityAliases`, `SourceOfTruth`, `SubjectDatabase`, `KeyExecutive`, `DealInfo`, `JudgeConfig`, `ExecutionConfig`, `ReportingConfig`, `ForensicDDConfig`, `DomainConfig`. |
| `finding.py` | Core analysis output models: `Finding` (full framework-schema-compliant), `AgentFinding` (agent-internal pre-transformation), `Citation`, `Gap`. Includes `Severity`, `Confidence`, `SourceType`, `AgentName`, `GapType`, `DetectionMethod` enums. |
| `inventory.py` | Data room inventory models: `SubjectEntry` (one row per subject in registry), `FileEntry` (individual file metadata), `ReferenceFile` (global reference file with category, routing, and subject mentions), `CountsJson` (aggregate counts), `SubjectMention` (subject-mention index entry). |
| `manifest.py` | Agent coverage tracking: `CoverageManifest`, `FileRead`, `FileSkipped`, `FileFailed`, `ManifestCustomer`. Enforces `coverage_pct >= 0.0` and `fallback_attempted` constraints. |
| `audit.py` | Audit trail and QA models: `AuditEntry` (single JSONL line), `AuditAction` enum (14 actions), `AuditCheck` (individual QA check result with DoD mapping), `AuditReport` (consolidated `audit.json` structure), `QualityScores`, `AgentScore`, `UnitScore`, `SpotCheck`, `Contradiction`, `SpotCheckDimension`, `SpotCheckResult` enums. |
| `persistence.py` | Run lifecycle models: `RunMetadata`, `Classification`, `CustomerClassification` enum, `SubjectClassEntry`, `RunHistoryEntry`. |
| `reporting.py` | Report schema models: `ReportSchema`, `SheetDef`, `ColumnDef`, `SortOrder`, `ConditionalFormat`, `SummaryFormula`, `GlobalFormatting`, `SeverityColor`. Models for machine-readable report_schema.json parsing. |
| `entity.py` | Entity resolution models: `EntityMatch`, `EntityMatchLog`, `EntityCache`, `EntityCacheEntry`, `UnmatchedEntity`, `RejectedMatch`, `MatchAttempt`. |
| `governance.py` | Governance graph models: `GovernanceEdge` (source, target, relationship, citation), `GovernanceGraph` (structured model with `edges: list[GovernanceEdge]` and graph utility methods). |
| `numerical.py` | Numerical audit models: `NumericalManifest`, `ManifestEntry` (id, label, value, source_file, derivation, used_in, cross_check, verified). |
| `enums.py` | Shared enums: `Severity`, `Confidence`, `AgentName`, `DealType`, `ExecutionMode`, `CompletionStatus`, `GapType`, `DetectionMethod`, `SourceType`. |
| `ontology.py` | Contract ontology models for knowledge graph reasoning: `DocumentType`, `ClauseType`, `ClauseNode`, `DocumentRelationship`, `Obligation`, `OntologyGraph`. |
| `project.py` | Multi-project portfolio models: `ProjectEntry`, `ProjectRegistry`, `PortfolioComparison`. |
| `search.py` | Search command models: `SearchPrompts`, `SearchColumn`, `SearchCitation`, `SearchColumnResult`, `SearchCustomerResult`. |

### Orchestrator (`src/dd_agents/orchestrator/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `PipelineEngine`, `PipelineState`, `PipelineStep`. |
| `engine.py` | Main pipeline engine implementing the 35-step execution flow as an async state machine. Each step is an async method on the `PipelineEngine` class (not a separate file). Controls step transitions, error recovery, and blocking gates (config gate at step 1, extraction gate at step 5, coverage gate at step 17, numerical audit gate at step 27, QA gate at step 28, post-generation at step 31). |
| `steps.py` | `PipelineStep` enum enumerating all 35 steps with string values used in checkpoints. Properties: `step_number`, `is_blocking_gate`, `is_conditional`. Defines `_BLOCKING_GATES` and `_CONDITIONAL_STEPS` frozensets. |
| `state.py` | `PipelineState` dataclass holding all mutable pipeline state: current step, run_id, run_dir, config, inventory paths, agent results, validation results. `StepResult` and `PipelineError` dataclasses. Serializable for checkpoint save/restore. Imports `PipelineStep` from `steps.py`. |
| `checkpoints.py` | Checkpoint save and restore logic. Serializes `PipelineState` to JSON at configurable intervals. Enables crash recovery by resuming from the last completed step. |
| `team.py` | Agent team management. Spawns specialist agents in parallel, monitors liveness, detects silent context exhaustion (no output for N minutes), coordinates retry and re-spawn logic per error recovery protocol. |
| `batch_scheduler.py` | Subject batching by complexity. Estimates per-subject complexity and partitions into batches for parallel agent execution. |
| `precedence.py` | Document precedence index builder. Wires folder_priority, version_chains, and scorer into `compute_precedence_index()`. |
| `progress.py` | Progress tracking utilities for pipeline step reporting. |

### Agents (`src/dd_agents/agents/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports agent runner classes. |
| `base.py` | `BaseAgentRunner` abstract class providing common agent lifecycle: SDK client setup, `ClaudeAgentOptions` configuration, prompt injection, agent spawn via `query()`, output collection, and timeout monitoring. Subclassed by each agent type. |
| `prompt_builder.py` | Prompt builder that assembles complete agent prompts from deal config, subject lists with file paths and safe names, reference file extracted text, domain-definitions extraction/governance/gap/cross-reference rules, and manifest instructions. Implements prompt size estimation and subject batching when estimated tokens exceed 80,000. |
| `specialists.py` | Four specialist agent runner classes (`LegalAgent`, `FinanceAgent`, `CommercialAgent`, `ProductTechAgent`), each providing agent-specific focus area instructions and reference file routing configuration. |
| `prompt_templates.py` | Prompt template strings for all agent types. |
| `judge.py` | Judge agent runner implementing the full iteration loop: spawn, score calculation (weighted 30/25/20/15/10), threshold check, targeted re-spawn for failing agents, Round 2 scoring with blend formula (70% new + 30% prior), forced finalization with quality caveats. |
| `executive_synthesis.py` | Executive Synthesis agent. Produces severity overrides, ranked deal-breakers, and executive summary from merged findings. |
| `red_flag_scanner.py` | Red Flag Scanner agent. Identifies critical risks across all subjects and domains. |
| `acquirer_intelligence.py` | Acquirer Intelligence agent. Buyer-strategy-aware analysis (enabled when `buyer_strategy` config is present). |
| `cost_tracker.py` | Model profile definitions (economy/standard/premium) and per-run cost tracking. |

### Extraction (`src/dd_agents/extraction/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `ExtractionPipeline`. |
| `pipeline.py` | Extraction orchestrator that processes all non-plaintext files through the fallback chain (markitdown -> pdftotext -> pytesseract -> Read tool). Writes extracted markdown to `_dd/forensic-dd/index/text/`. Implements the blocking gate: will not proceed unless both `checksums.sha256` and `extraction_quality.json` exist and are non-empty. Detects systemic failure (>50% primary method failure). |
| `markitdown.py` | Wrapper around the `markitdown` CLI/library for primary document extraction (PDF, Word, Excel, PPT, images with OCR). |
| `ocr.py` | OCR fallback using pytesseract via `~/ocr_work/` working directory. Handles scanned PDFs and image files that markitdown cannot extract. |
| `cache.py` | SHA-256 checksum-based extraction cache. Maintains `checksums.sha256` in the PERMANENT tier. On re-runs, reuses cached extraction if hash matches. Removes stale extractions for deleted files. |
| `backend.py` | Backend selection logic for extraction pipeline. |
| `coordinates.py` | `TextBlock` coordinate model for layout-aware extraction. |
| `language_detect.py` | Document language detection heuristics. |
| `layout_pdf.py` | PDF layout analysis (table, column, and block detection). |
| `ocr_registry.py` | OCR backend registry (dispatches to pytesseract or GLM-OCR). |
| `quality.py` | Tracks extraction quality per file. Writes `extraction_quality.json` with method used (primary, fallback_pdftotext, fallback_ocr, fallback_read, direct_read, failed), bytes extracted, and confidence. |

### Entity Resolution (`src/dd_agents/entity_resolution/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `EntityResolver`, `compute_safe_name`. |
| `matcher.py` | Implements the 6-pass cascading matcher: (1) preprocessing/normalization, (2) exact match, (3) alias lookup from `entity_aliases.canonical_to_variants`, (4) fuzzy match using rapidfuzz token-sort ratio with length-dependent thresholds (>=88 for >8 chars, >=95 for 5-8 chars), (5) TF-IDF cosine similarity on character n-grams for large lists, (6) parent-child lookup. Enforces short name guard rails (<=5 chars after preprocessing never eligible for fuzzy), exclusion list rejection. |
| `cache.py` | PERMANENT tier entity resolution cache (`_dd/entity_resolution_cache.json`). Implements cache lookup before 6-pass matcher, per-entry invalidation on config change (diff algorithm comparing added/removed aliases, exclusions, parent-child changes), confirmation count increment, and stale entry removal. |
| `safe_name.py` | `compute_safe_name(name: str) -> str` implementing the `subject_safe_name` convention: lowercase, strip legal suffixes (Inc., Corp., LLC, Ltd., ULC, GmbH, S.A., Pty), replace spaces and special characters with `_`, collapse consecutive underscores, strip leading/trailing underscores. |
| `dedup.py` | Entity deduplication. Merges duplicate subject entries detected by fuzzy matching. |
| `logging.py` | Match logging. Writes `entity_matches.json` to the FRESH tier with matches, unmatched (with per-pass attempt details), and rejected arrays. |

### Inventory (`src/dd_agents/inventory/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports inventory builder functions. |
| `discovery.py` | File discovery: runs `tree`, `find`, and `file --mime-type` commands (or Python equivalents) with exclude patterns. Produces `tree.txt`, `files.txt`, `file_types.txt` in the FRESH inventory directory. Detects data room changes vs prior run inventory snapshot. |
| `subjects.py` | Subject registry builder. Parses `tree.txt` to identify the folder hierarchy (group/subject/files). Produces `subjects.csv` (group, name, safe_name, path, file_count, file_list) and `counts.json` (total_files, total_subjects, total_reference_files, files_by_extension, files_by_group, subjects_by_group). Computes `subject_safe_name` for each subject. |
| `reference_files.py` | Reference file classifier and router. Identifies files NOT under a subject directory as global reference files. Classifies by category (Financial, Pricing, Corporate/Legal, Operational, Sales, Compliance, HR, Other) and subcategory. Scans for subject name mentions. Assigns files to agents per routing table. Produces `reference_files.json`. |
| `mentions.py` | Subject-mention index builder. Matches subject names found in reference files against `subjects.csv` using entity resolution. Produces `subject_mentions.json` with matches, ghost subject gaps (in reference data but no folder), and phantom contract gaps (folder exists but absent from reference data). |
| `integrity.py` | Inventory integrity verifier. Asserts total files = subject files + reference files, no orphan files exist, and all files are classified. Any unclassified file triggers classification and addition. |

### Validation (`src/dd_agents/validation/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports validation gate functions. |
| `coverage.py` | Coverage gate (pipeline step 17). For each agent type, counts unique `{subject_safe_name}.json` files against expected subject count. Detects missing subjects, aggregate files, and empty outputs. Triggers re-spawn for missing subjects. Enforces clean-result entries for subjects with zero findings. |
| `numerical_audit.py` | 6-layer numerical audit. Layer 1: source traceability (every number traces to a file). Layer 2: arithmetic verification (re-derive from source). Layer 3: cross-source consistency (subjects.csv vs counts.json, etc.). Layer 4: cross-format parity (Excel vs JSON spot-check). Layer 5: semantic reasonableness (flag implausible numbers). Layer 6: cross-run consistency (compare with prior run values). Blocking gate between analysis and Excel generation. |
| `qa_audit.py` | Full QA audit (18 checks, step 28 blocking gate). Structural integrity verification: manifests, file coverage, citations, report sheets, etc. Produces `audit.json`. |
| `dod.py` | 31 Definition of Done checks (step 35 non-blocking). Completeness and quality evaluation. See dod.py module docstring for the two-tier validation design. |
| `pre_merge.py` | Pre-merge validation (step 23). Validates agent outputs before merge/dedup. |
| `schema_validator.py` | Report schema validation. After Excel generation, verifies all sheets exist, columns match schema, sort orders are correct. |

### Reporting (`src/dd_agents/reporting/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports reporting functions. |
| `merge.py` | Finding merge and deduplication across 4 specialist agents per subject. Collects per-agent JSONs, merges findings (keeping highest severity on duplicates, longest exact_quote), consolidates governance graphs (Legal primary), merges cross-references, and transforms agent-internal findings to framework-schema-compliant findings with auto-generated IDs. Writes merged per-subject JSONs and merged gap files. Preserves incremental carry-forward metadata. |
| `diff.py` | Report diff builder. Compares current findings against prior run using match keys (subject + category + citation location). Detects new findings, resolved findings, changed severity, new/resolved gaps, new/removed subjects. Writes `report_diff.json`. |
| `excel.py` | Excel report generation from `report_schema.json`. Schema-driven generation (no hardcoded sheet definitions). Handles activation conditions, conditional formatting, summary formulas, freeze panes, and auto-filters. |
| `contract_dates.py` | Contract date reconciliation. Reconciles database expiry dates against data room evidence. Writes `contract_date_reconciliation.json`. |
| `computed_metrics.py` | Derived analytics: three-way finding classification (noise → data quality → material), canonical categories, trend analysis, SaaS metrics, severity distribution. |
| `templates.py` | Configurable report templates: `ReportBranding`, `ReportSections`, `ReportTemplate`. |
| `clause_library.py` | Clause library analysis and aggregation across subjects. |
| `export.py` | Report export utilities. |
| `pdf_export.py` | HTML-to-PDF export using playwright or weasyprint (both optional). |
| `html.py` | HTML report orchestrator. Coordinates all section renderers to produce the final HTML report. |
| `html_base.py` | `SectionRenderer` base class with shared helpers: `escape()`, `severity_badge()`, `render_alert()`, `fmt_currency()`. All renderers inherit from this. |
| `html_*.py` | 30+ section renderers (dashboard, executive, findings_table, subjects, gaps, cross, governance, financial, risk, analysis, compliance, domains, entity, quality, methodology, diff, timeline, renewal, discount, liability, ip_risk, key_employee, product_adoption, saas_metrics, tech_stack, valuation, strategy, red_flags, recommendations, clause_library, integration_playbook, cross_domain). |

### Persistence (`src/dd_agents/persistence/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports persistence managers. |
| `tiers.py` | Three-tier lifecycle manager implementing PERMANENT, VERSIONED, and FRESH tier operations. |
| `run_manager.py` | Run initialization: generates run_id, creates `{RUN_DIR}` with all subdirectories, snapshots prior inventory, wipes FRESH tier. Run finalization: updates `latest` symlink, writes final metadata. |
| `incremental.py` | Subject classification for incremental mode. Classifies as NEW, CHANGED, STALE_REFRESH, UNCHANGED, or DELETED. Carries forward UNCHANGED subject findings. |
| `concurrency.py` | File-based locking utilities for concurrent pipeline access. |
| `project_registry.py` | Multi-project registry manager. CRUD operations on `ProjectRegistry`, portfolio comparison, deal archival. |

### Hooks (`src/dd_agents/hooks/`)

> **Note**: The orchestrator (`05-orchestrator.md` step 16) imports hooks via `agents.hooks` and `agents.mcp_server`. These paths are satisfied by package-level re-exports in `agents/__init__.py` that delegate to `hooks/` and `tools/` respectively.

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports hook builders. Also re-exported from `agents/__init__.py` for convenience (`from dd_agents.agents.hooks import ...`). |
| `factory.py` | Hook builder factory. Creates hook configurations per agent type. |
| `pre_tool.py` | PreToolUse hooks. Path guard: blocks Write/Edit outside the project `_dd/` directory. Bash guard: blocks destructive commands (`rm -rf`, `git push --force`, etc.). File size guard: warns on writes exceeding configurable size limit. |
| `post_tool.py` | PostToolUse hooks. JSON validation: when an agent writes a `{subject_safe_name}.json` file, validates it against the `SubjectJSON` Pydantic model. Manifest validation: when `coverage_manifest.json` is written, validates against `CoverageManifest` model. Audit entry validation: spot-checks JSONL entries for required fields. |
| `stop.py` | Stop hooks. Coverage enforcement: blocks agent stop if subject output count does not match expected count. Manifest enforcement: blocks stop if `coverage_manifest.json` has not been written. Audit log enforcement: warns (does not block) if `audit_log.jsonl` is missing. |

### Tools (`src/dd_agents/tools/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports all tool functions and `create_tool_server()`. |
| `server.py` | Legacy MCP server setup. |
| `mcp_server.py` | MCP server builder using `@tool` decorator + `create_sdk_mcp_server()`. Context-free tools get simple wrappers; context-dependent tools use closure-based binding of runtime paths. `build_mcp_server()` is the public API. |
| `validate_finding.py` | `validate_finding` tool: accepts a finding JSON, validates against `Finding` Pydantic model, returns structured error list or "valid". Checks citation requirements per severity level. |
| `validate_gap.py` | `validate_gap` tool: accepts a gap JSON, validates against `Gap` model, returns errors or "valid". Checks required fields and enum values. |
| `validate_manifest.py` | `validate_manifest` tool: accepts coverage manifest JSON, validates against `CoverageManifest` model, checks `coverage_pct >= 0.90` and `fallback_attempted` on failed files. |
| `verify_citation.py` | `verify_citation` tool: given a citation, checks that `source_path` exists in `files.txt` and that `exact_quote` can be found (substring search) in the extracted text. Returns match status and location. |
| `get_subject_files.py` | `get_subject_files` tool: returns the file list and count for a given subject name from inventory. Used by agents during analysis to confirm they have processed all files. |
| `resolve_entity.py` | `resolve_entity` tool: checks entity resolution cache for a given name, returns canonical name, match method, and confidence, or "unresolved" if not found. |
| `report_progress.py` | `report_progress` tool: allows agents to report progress back to the orchestrator. Used for liveness monitoring. |
| `read_office.py` | `read_office` tool: extracts text from Office documents using markitdown. |
| `search_similar.py` | `search_similar` tool: vector similarity search via ChromaDB (optional). |
| `web_research.py` | `web_research` tool: web research via google-researcher-mcp for claim verification. |

### Search (`src/dd_agents/search/`)

| File | Responsibilities |
|------|-----------------|
| `runner.py` | Search orchestration: discovers data room files, groups by subject, runs analyzer per subject, writes Excel output. Entry point for the `dd-agents search` CLI command. |
| `analyzer.py` | Multi-phase search analyzer implementing 4-phase analysis: map (per chunk) → merge → synthesis (conflicts) → validation (NOT_ADDRESSED). Uses page-aware chunking with 150K char target per chunk. |
| `chunker.py` | Page-aware document chunking. Splits at `--- Page N ---` markers with 15% overlap. Produces `AnalysisChunk` objects with page ranges and source tracking. |
| `citation_verifier.py` | Citation accuracy verification. Checks that `exact_quote` appears in the referenced file/page with fuzzy matching. |
| `excel_writer.py` | Writes search results to Excel with Summary (one row per subject, color-coded) and Details (one row per citation) sheets. |

### Utils (`src/dd_agents/utils/`)

| File | Responsibilities |
|------|-----------------|
| `constants.py` | Path constants (`_DD_DIR`, `SKILL_DIR`, `INDEX_DIR`, `INVENTORY_DIR`), exclude patterns for file discovery, severity labels, and audit action enums shared across modules. |
| `naming.py` | `subject_safe_name()` convention: lowercase, strip legal suffixes (Inc/Corp/LLC/Ltd), replace special chars with `_`, collapse underscores. Includes full Unicode transliteration table (ø→o, ß→ss, é→e, etc.). |

### Vector Store (`src/dd_agents/vector_store/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Conditional import; exports are no-ops if ChromaDB is not installed. |
| `store.py` | ChromaDB wrapper. Creates/loads a collection for the current data room. Indexes extracted text chunks with metadata (subject, file path, doc type). Provides similarity search with configurable top-k and distance threshold. |
| `embeddings.py` | Embedding generation for extracted text. Chunks documents into overlapping segments (configurable size and overlap). Generates embeddings using ChromaDB's default embedding function or a configurable alternative. |

### Precedence (`src/dd_agents/precedence/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports precedence engine functions. |
| `folder_priority.py` | Folder tier classification (AUTHORITATIVE=1, WORKING=2, SUPPLEMENTARY=3, HISTORICAL=4). |
| `version_chains.py` | Version chain detection using filename keywords (signed/executed/final/draft/old). |
| `scorer.py` | Precedence score calculation: version_rank 40%, folder_tier 30%, recency 30%. |

### Reasoning (`src/dd_agents/reasoning/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports reasoning graph functions. |
| `contract_graph.py` | NetworkX-based contract knowledge graph. Builds graph from ontology models, supports clause traversal, obligation tracking, and conflict detection. |

### Query (`src/dd_agents/query/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports query engine. |
| `indexer.py` | Finding index builder. Indexes merged findings for fast lookup by subject, severity, category, and keyword. |
| `engine.py` | Query engine for `dd-agents query` command. Natural-language queries over findings using Claude. |

### Knowledge (`src/dd_agents/knowledge/`)

`knowledge/` — Deal Knowledge Base: persistent knowledge layer (12 modules). Article CRUD, knowledge graph, analysis chronicle, finding lineage, health checks.

### Testing (`src/dd_agents/testing/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Test utility exports. |
| `data_generator.py` | Synthetic data room generator for testing and demos. |

---

## Module Dependency Table

This table shows which modules import from which, establishing the dependency graph within the package.

| Module | Imports From |
|--------|-------------|
| `cli` | `config`, `orchestrator.engine`, `utils.constants` |
| `config` | `models.config` |
| `utils.constants` | (none -- leaf module) |
| `utils.naming` | (none -- leaf module) |
| `models.config` | (pydantic only -- leaf model) |
| `models.finding` | `models.config` (for `AgentName` re-use) |
| `models.inventory` | (pydantic only -- leaf model) |
| `models.manifest` | `models.finding` (for `AgentName`) |
| `models.audit` | `models.finding` (for `Severity`, `AgentName`), `models.manifest` |
| `models.persistence` | `models.finding` (for `Severity`) |
| `models.reporting` | (pydantic only -- leaf model) |
| `models.entity` | (pydantic only -- leaf model) |
| `models.governance` | `models.finding` (for `Citation`) |
| `models.numerical` | (pydantic only -- leaf model) |
| `orchestrator.engine` | `orchestrator.state`, `orchestrator.steps`, `orchestrator.checkpoints`, `agents.*`, `extraction.pipeline`, `entity_resolution.matcher`, `inventory.*`, `validation.*`, `reporting.*`, `persistence.*`, `config` |
| `orchestrator.steps` | (enum only -- leaf module) |
| `orchestrator.state` | `orchestrator.steps`, `models.*` (for type annotations) |
| `orchestrator.checkpoints` | `orchestrator.state` |
| `orchestrator.team` | `agents.base`, `agents.specialists`, `agents.judge`, `agents.reporting_lead` |
| `agents.base` | `models.*`, `hooks.*`, `tools.server`, `config` |
| `agents.prompt_builder` | `models.config`, `models.inventory`, `models.finding`, `entity_resolution.safe_name`, `utils.constants` |
| `agents.specialists` | `agents.base`, `agents.prompt_builder` |
| `agents.judge` | `agents.base`, `agents.prompt_builder`, `models.audit` |
| `agents.executive_synthesis` | `agents.base`, `agents.prompt_builder`, `models.finding` |
| `agents.red_flag_scanner` | `agents.base`, `agents.prompt_builder`, `models.finding` |
| `agents.acquirer_intelligence` | `agents.base`, `agents.prompt_builder`, `models.config` |
| `agents.cost_tracker` | `models.config` (model profiles + cost tracking) |
| `extraction.pipeline` | `extraction.markitdown`, `extraction.ocr`, `extraction.glm_ocr`, `extraction.cache`, `extraction.quality`, `extraction._constants`, `extraction._helpers` |
| `search.runner` | `search.analyzer`, `search.chunker`, `search.excel_writer`, `utils.constants` |
| `search.analyzer` | `search.chunker`, `search.citation_verifier`, `models.*` |
| `extraction.markitdown` | `constants` |
| `extraction.ocr` | `constants` |
| `extraction.cache` | `constants` |
| `extraction.backend` | `extraction._constants` |
| `extraction.coordinates` | (pydantic only — leaf model) |
| `extraction.layout_pdf` | `extraction.coordinates`, `extraction._constants` |
| `extraction.language_detect` | (standalone utility) |
| `extraction.ocr_registry` | `extraction.ocr`, `extraction.glm_ocr` |
| `extraction.quality` | `models.inventory` (for `FileEntry`) |
| `entity_resolution.matcher` | `entity_resolution.cache`, `entity_resolution.safe_name`, `entity_resolution.logging`, `models.entity`, `models.config` (for `EntityAliases`) |
| `entity_resolution.cache` | `models.entity` |
| `entity_resolution.safe_name` | (standalone utility -- leaf module) |
| `entity_resolution.logging` | `models.entity` |
| `inventory.discovery` | `constants` |
| `inventory.subjects` | `entity_resolution.safe_name`, `models.inventory` |
| `inventory.reference_files` | `models.inventory`, `entity_resolution.matcher` |
| `inventory.mentions` | `models.inventory`, `entity_resolution.matcher` |
| `inventory.integrity` | `models.inventory` |
| `validation.coverage` | `models.manifest`, `models.inventory`, `orchestrator.state` |
| `validation.numerical_audit` | `models.numerical`, `models.inventory` |
| `validation.qa_audit` | `models.audit`, `models.manifest`, `models.finding`, `models.inventory`, `models.governance` |
| `validation.dod` | `validation.qa_audit`, `models.audit` |
| `validation.schema_validator` | `models.reporting` |
| `reporting.merge` | `models.finding`, `models.governance`, `models.inventory` |
| `reporting.diff` | `models.finding`, `models.persistence` |
| `reporting.excel` | `models.reporting`, `models.finding`, `models.inventory` |
| `reporting.contract_dates` | `models.config`, `models.inventory` |
| `persistence.tiers` | `constants` |
| `persistence.run_manager` | `persistence.tiers`, `models.persistence`, `constants` |
| `persistence.incremental` | `models.persistence`, `persistence.tiers` |
| `hooks.pre_tool` | `constants` |
| `hooks.post_tool` | `models.finding`, `models.manifest` |
| `hooks.stop` | `models.manifest`, `orchestrator.state` |
| `tools.server` | `tools.validate_finding`, `tools.validate_gap`, `tools.validate_manifest`, `tools.verify_citation`, `tools.get_subject_files`, `tools.resolve_entity`, `tools.report_progress` |
| `tools.validate_finding` | `models.finding` |
| `tools.validate_gap` | `models.finding` |
| `tools.validate_manifest` | `models.manifest` |
| `tools.verify_citation` | `models.inventory` |
| `tools.get_subject_files` | `models.inventory` |
| `tools.resolve_entity` | `entity_resolution.cache`, `models.entity` |
| `tools.report_progress` | `orchestrator.state` |
| `precedence.folder_priority` | `models.inventory` |
| `precedence.version_chains` | `models.inventory` |
| `precedence.scorer` | `precedence.folder_priority`, `precedence.version_chains` |
| `reasoning.contract_graph` | `models.ontology`, `networkx` |
| `query.indexer` | `models.finding` |
| `query.engine` | `query.indexer`, `models.finding` |
| `persistence.project_registry` | `models.project`, `persistence.concurrency` |
| `persistence.concurrency` | (standalone utility — leaf module) |
| `reporting.computed_metrics` | `models.finding`, `models.inventory` |
| `reporting.templates` | (pydantic only — leaf model) |
| `reporting.html` | `reporting.html_base`, `reporting.html_*.py` (all section renderers) |
| `reporting.html_base` | `models.finding` |
| `reporting.pdf_export` | (playwright/weasyprint — external, optional) |
| `vector_store.store` | `vector_store.embeddings` |
| `vector_store.embeddings` | (chromadb -- external) |

---

## Dependency Rules

1. **Models are leaf modules.** Model files import only from `pydantic` and other model files. They never import from orchestrator, agents, extraction, or any runtime module.
2. **No circular imports.** The dependency graph is a DAG. The orchestrator sits at the top; models sit at the bottom.
3. **`constants.py` is the true leaf.** It has zero internal imports and is importable by every other module.
4. **Agents depend on hooks and tools**, not the other way around. Hooks and tools import from models only.
5. **The orchestrator imports everything.** It is the composition root that wires all modules together.

---

## Package Configuration

```toml
[project]
name = "dd-agents"
version = "0.1.0"
description = "Due Diligence Agent SDK -- forensic M&A contract analysis"
requires-python = ">=3.12"
# All core dependencies are permissively licensed (Apache 2.0, MIT, BSD).
# pymupdf (AGPL-3.0) is optional — see [project.optional-dependencies].
dependencies = [
    "claude-agent-sdk>=0.1.39",
    "pydantic>=2.0",
    "openpyxl>=3.1",
    "rapidfuzz>=3.0",
    "networkx>=3.0",
    "scikit-learn>=1.3",
    "click>=8.0",
    "rich>=13.0",
    "markitdown>=0.1",
]

[project.optional-dependencies]
vector = [
    "chromadb>=0.4",
]
ocr = [
    "pytesseract>=0.3",
    "Pillow>=10.0",
]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "ruff>=0.1",
    "mypy>=1.5",
]

[project.scripts]
dd-agents = "dd_agents.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dd_agents"]
```

---

## Key Architectural Constraints

1. **Flat model imports.** All models are importable from `dd_agents.models` via the `__init__.py` re-export.
2. **Config files ship with the package.** `deal-config.template.json`, `deal-config.schema.json`, and `report_schema.json` live in `config/` at the repo root (not inside `src/`) and are referenced by path at runtime.
3. **No `__main__.py`.** The entry point is `cli.py` registered via `[project.scripts]`. Run with `dd-agents run <config>` or `python -m dd_agents` if `__main__.py` is added later.
4. **Tests mirror source structure.** Unit tests cover models and pure functions. Integration tests require a sample data room fixture. E2E tests require an API key and run the full pipeline.
5. **Vector store is fully optional.** All code paths that reference `vector_store` check for ChromaDB availability and degrade gracefully.
