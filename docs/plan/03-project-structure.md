# 03 -- Project Structure

## Repository Layout

```
due-diligence-agents/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── dd_agents/
│       ├── __init__.py
│       ├── cli.py                    # Click/Typer CLI entry point
│       ├── config.py                 # DealConfig loader + validation
│       ├── constants.py              # Path constants, severity enums
│       ├── models/
│       │   ├── __init__.py
│       │   ├── config.py             # DealConfig, BuyerInfo, TargetInfo, etc.
│       │   ├── finding.py            # Finding, Citation, Gap models
│       │   ├── inventory.py          # CustomerEntry, FileEntry, ReferenceFile
│       │   ├── manifest.py           # CoverageManifest, FileRead, FileSkipped
│       │   ├── audit.py              # AuditEntry, AuditReport, QualityScores
│       │   ├── persistence.py        # RunMetadata, Classification, RunHistory
│       │   ├── reporting.py          # ReportSchema, SheetDef, ColumnDef
│       │   ├── entity.py             # EntityMatch, EntityCache, MatchLog
│       │   ├── governance.py         # GovernanceEdge, GovernanceGraph
│       │   └── numerical.py          # NumericalManifest, ManifestEntry
│       ├── orchestrator/
│       │   ├── __init__.py
│       │   ├── engine.py             # Main pipeline engine (35 steps)
│       │   ├── steps.py              # PipelineStep enum (all 35 steps)
│       │   ├── state.py              # PipelineState dataclass
│       │   ├── checkpoints.py        # Checkpoint save/restore
│       │   └── team.py               # Agent team management
│       │   # NOTE: Steps are implemented as async methods on the PipelineEngine
│       │   # class in engine.py, not as individual files. The engine imports
│       │   # from agents/, extraction/, validation/, etc. as needed per step.
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py               # BaseAgentRunner (common spawn logic)
│       │   ├── prompt_builder.py      # Prompt builder (assembles from templates)
│       │   ├── specialists.py        # Legal, Finance, Commercial, ProductTech
│       │   ├── judge.py              # Judge agent with iteration loop
│       │   └── reporting_lead.py     # Reporting Lead agent
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── _constants.py         # Shared extension sets + confidence constants
│       │   ├── _helpers.py           # Shared read_text() helper
│       │   ├── pipeline.py           # Extraction orchestrator (pre-inspection + fallback chains)
│       │   ├── markitdown.py         # markitdown wrapper (Office + PDF)
│       │   ├── ocr.py                # OCR fallback (pytesseract)
│       │   ├── glm_ocr.py            # GLM-OCR vision-language model (mlx-vlm / Ollama)
│       │   ├── cache.py              # Checksum-based cache
│       │   ├── quality.py            # ExtractionQuality tracker
│       │   └── reference_downloader.py  # External T&C URL download
│       ├── entity_resolution/
│       │   ├── __init__.py
│       │   ├── matcher.py            # 6-pass cascading matcher
│       │   ├── cache.py              # PERMANENT tier cache
│       │   ├── safe_name.py          # customer_safe_name convention
│       │   └── logging.py            # Match logging (entity_matches.json)
│       ├── inventory/
│       │   ├── __init__.py
│       │   ├── discovery.py          # File discovery (tree, files, file_types)
│       │   ├── customers.py          # Customer registry builder
│       │   ├── reference_files.py    # Reference file classifier + router
│       │   ├── mentions.py           # Customer-mention index
│       │   └── integrity.py          # Inventory integrity verifier
│       ├── validation/
│       │   ├── __init__.py
│       │   ├── coverage.py           # Coverage gate (step 17)
│       │   ├── numerical_audit.py     # 5-layer numerical audit
│       │   ├── qa_audit.py           # Full QA audit (16 checks)
│       │   ├── dod.py                # 30 Definition of Done checks
│       │   └── schema_validator.py   # Report schema validation
│       ├── reporting/
│       │   ├── __init__.py
│       │   ├── merge.py              # Finding merge + dedup
│       │   ├── diff.py               # Report diff (vs prior run)
│       │   ├── excel.py              # Excel generation from schema
│       │   └── contract_dates.py     # Contract date reconciliation
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── tiers.py              # Three-tier lifecycle manager
│       │   ├── run_manager.py        # Run initialization + finalization
│       │   └── incremental.py        # Customer classification + carry-forward
│       ├── hooks/
│       │   ├── __init__.py
│       │   ├── pre_tool.py           # PreToolUse hooks
│       │   ├── post_tool.py          # PostToolUse hooks (JSON validation)
│       │   └── stop.py               # Stop hooks (coverage gate)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── server.py             # MCP server setup
│       │   ├── validate_finding.py   # validate_finding tool
│       │   ├── validate_gap.py       # validate_gap tool
│       │   ├── validate_manifest.py  # validate_manifest tool
│       │   ├── verify_citation.py    # verify_citation tool
│       │   ├── get_customer_files.py  # get_customer_files tool
│       │   ├── resolve_entity.py     # resolve_entity tool
│       │   └── report_progress.py    # report_progress tool
│       └── vector_store/
│           ├── __init__.py
│           ├── store.py              # ChromaDB wrapper (optional)
│           └── embeddings.py         # Embedding generation
├── tests/
│   ├── conftest.py
│   ├── fixtures/                     # Test data room, sample configs
│   ├── unit/
│   │   ├── test_models.py
│   │   ├── test_entity_resolution.py
│   │   ├── test_safe_name.py
│   │   ├── test_extraction.py
│   │   ├── test_numerical.py
│   │   └── test_hooks.py
│   ├── integration/
│   │   ├── test_pipeline.py
│   │   ├── test_agents.py
│   │   └── test_reporting.py
│   └── e2e/
│       └── test_full_run.py
├── config/                            # See 04-data-models.md § DealConfig for the full schema
│   ├── deal-config.template.json     # Template (copy from skill)
│   ├── deal-config.schema.json       # JSON Schema (copy from skill)
│   └── report_schema.json            # Report schema (copy from skill)
└── docs/
    └── setup.md                      # Setup instructions
```

---

## Module Descriptions

### Top-Level Package (`src/dd_agents/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Package root. Exports version string and key public classes. |
| `cli.py` | Click/Typer CLI entry point. Accepts `deal-config.json` path, execution mode overrides, and verbosity flags. Wires up the orchestrator and starts the pipeline run. |
| `config.py` | Loads `deal-config.json`, validates against JSON Schema and Pydantic `DealConfig` model, resolves schema version compatibility, and provides a typed `DealConfig` object to the rest of the system. **Note**: The orchestrator (05) imports from `config.deal_config`. To support this, `config.py` can be refactored into a `config/` package with `config/__init__.py` re-exporting from `config/deal_config.py`, or the orchestrator import can use `from dd_agents.config import DealConfig` directly. |
| `constants.py` | Path constants (`_DD_DIR`, `SKILL_DIR`, `INDEX_DIR`, `INVENTORY_DIR`), exclude patterns for file discovery, severity labels, and audit action enums shared across modules. |

### Models (`src/dd_agents/models/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Re-exports all model classes for convenient `from dd_agents.models import ...` imports. |
| `config.py` | Pydantic v2 models for the deal configuration hierarchy: `DealConfig`, `BuyerInfo`, `TargetInfo`, `PreviousName`, `AcquiredEntity`, `EntityAliases`, `SourceOfTruth`, `CustomerDatabase`, `KeyExecutive`, `DealInfo`, `JudgeConfig`, `ExecutionConfig`, `ReportingConfig`, `ForensicDDConfig`, `DomainConfig`. |
| `finding.py` | Core analysis output models: `Finding` (full framework-schema-compliant), `AgentFinding` (agent-internal pre-transformation), `Citation`, `Gap`. Includes `Severity`, `Confidence`, `SourceType`, `AgentName`, `GapType`, `DetectionMethod` enums. |
| `inventory.py` | Data room inventory models: `CustomerEntry` (one row per customer in registry), `FileEntry` (individual file metadata), `ReferenceFile` (global reference file with category, routing, and customer mentions), `CountsJson` (aggregate counts), `CustomerMention` (customer-mention index entry). |
| `manifest.py` | Agent coverage tracking: `CoverageManifest`, `FileRead`, `FileSkipped`, `FileFailed`, `ManifestCustomer`. Enforces `coverage_pct >= 0.0` and `fallback_attempted` constraints. |
| `audit.py` | Audit trail and QA models: `AuditEntry` (single JSONL line), `AuditAction` enum (14 actions), `AuditCheck` (individual QA check result with DoD mapping), `AuditReport` (consolidated `audit.json` structure), `QualityScores`, `AgentScore`, `UnitScore`, `SpotCheck`, `Contradiction`, `SpotCheckDimension`, `SpotCheckResult` enums. |
| `persistence.py` | Run lifecycle models: `RunMetadata`, `Classification`, `CustomerClassification` enum, `CustomerClassEntry`, `RunHistoryEntry`. |
| `reporting.py` | Report schema models: `ReportSchema`, `SheetDef`, `ColumnDef`, `SortOrder`, `ConditionalFormat`, `SummaryFormula`, `GlobalFormatting`, `SeverityColor`. Models for machine-readable report_schema.json parsing. |
| `entity.py` | Entity resolution models: `EntityMatch`, `EntityMatchLog`, `EntityCache`, `EntityCacheEntry`, `UnmatchedEntity`, `RejectedMatch`, `MatchAttempt`. |
| `governance.py` | Governance graph models: `GovernanceEdge` (source, target, relationship, citation), `GovernanceGraph` (structured model with `edges: list[GovernanceEdge]` and graph utility methods). |
| `numerical.py` | Numerical audit models: `NumericalManifest`, `ManifestEntry` (id, label, value, source_file, derivation, used_in, cross_check, verified). |

### Orchestrator (`src/dd_agents/orchestrator/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `PipelineEngine`, `PipelineState`, `PipelineStep`. |
| `engine.py` | Main pipeline engine implementing the 35-step execution flow as an async state machine. Each step is an async method on the `PipelineEngine` class (not a separate file). Controls step transitions, error recovery, and blocking gates (config gate at step 1, extraction gate at step 5, coverage gate at step 17, numerical audit gate at step 27, QA gate at step 28, post-generation at step 31). |
| `steps.py` | `PipelineStep` enum enumerating all 35 steps with string values used in checkpoints. Properties: `step_number`, `is_blocking_gate`, `is_conditional`. Defines `_BLOCKING_GATES` and `_CONDITIONAL_STEPS` frozensets. |
| `state.py` | `PipelineState` dataclass holding all mutable pipeline state: current step, run_id, run_dir, config, inventory paths, agent results, validation results. `StepResult` and `PipelineError` dataclasses. Serializable for checkpoint save/restore. Imports `PipelineStep` from `steps.py`. |
| `checkpoints.py` | Checkpoint save and restore logic. Serializes `PipelineState` to JSON at configurable intervals. Enables crash recovery by resuming from the last completed step. |
| `team.py` | Agent team management. Spawns specialist agents in parallel, monitors liveness, detects silent context exhaustion (no output for N minutes), coordinates retry and re-spawn logic per error recovery protocol. |

### Agents (`src/dd_agents/agents/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports agent runner classes. |
| `base.py` | `BaseAgentRunner` abstract class providing common agent lifecycle: SDK client setup, `ClaudeAgentOptions` configuration, prompt injection, agent spawn via `query()`, output collection, and timeout monitoring. Subclassed by each agent type. |
| `prompt_builder.py` | Prompt builder that assembles complete agent prompts from deal config, customer lists with file paths and safe names, reference file extracted text, domain-definitions extraction/governance/gap/cross-reference rules, and manifest instructions. Implements prompt size estimation and customer batching when estimated tokens exceed 80,000. |
| `specialists.py` | Four specialist agent runner classes (`LegalAgent`, `FinanceAgent`, `CommercialAgent`, `ProductTechAgent`), each providing agent-specific focus area instructions and reference file routing configuration. |
| `judge.py` | Judge agent runner implementing the full iteration loop: spawn, score calculation (weighted 30/25/20/15/10), threshold check, targeted re-spawn for failing agents, Round 2 scoring with blend formula (70% new + 30% prior), forced finalization with quality caveats. |
| `reporting_lead.py` | Reporting Lead agent runner. Provides the agent with reporting-protocol rules, numerical validation rules, merge/dedup protocol, report schema path, and all findings paths. Implements checkpointing for large customer sets. |

### Extraction (`src/dd_agents/extraction/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `ExtractionPipeline`. |
| `pipeline.py` | Extraction orchestrator that processes all non-plaintext files through the fallback chain (markitdown -> pdftotext -> pytesseract -> Read tool). Writes extracted markdown to `_dd/forensic-dd/index/text/`. Implements the blocking gate: will not proceed unless both `checksums.sha256` and `extraction_quality.json` exist and are non-empty. Detects systemic failure (>50% primary method failure). |
| `markitdown.py` | Wrapper around the `markitdown` CLI/library for primary document extraction (PDF, Word, Excel, PPT, images with OCR). |
| `ocr.py` | OCR fallback using pytesseract via `~/ocr_work/` working directory. Handles scanned PDFs and image files that markitdown cannot extract. |
| `cache.py` | SHA-256 checksum-based extraction cache. Maintains `checksums.sha256` in the PERMANENT tier. On re-runs, reuses cached extraction if hash matches. Removes stale extractions for deleted files. |
| `quality.py` | Tracks extraction quality per file. Writes `extraction_quality.json` with method used (primary, fallback_pdftotext, fallback_ocr, fallback_read, direct_read, failed), bytes extracted, and confidence. |

### Entity Resolution (`src/dd_agents/entity_resolution/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports `EntityResolver`, `compute_safe_name`. |
| `matcher.py` | Implements the 6-pass cascading matcher: (1) preprocessing/normalization, (2) exact match, (3) alias lookup from `entity_aliases.canonical_to_variants`, (4) fuzzy match using rapidfuzz token-sort ratio with length-dependent thresholds (>=88 for >8 chars, >=95 for 5-8 chars), (5) TF-IDF cosine similarity on character n-grams for large lists, (6) parent-child lookup. Enforces short name guard rails (<=5 chars after preprocessing never eligible for fuzzy), exclusion list rejection. |
| `cache.py` | PERMANENT tier entity resolution cache (`_dd/entity_resolution_cache.json`). Implements cache lookup before 6-pass matcher, per-entry invalidation on config change (diff algorithm comparing added/removed aliases, exclusions, parent-child changes), confirmation count increment, and stale entry removal. |
| `safe_name.py` | `compute_safe_name(name: str) -> str` implementing the `customer_safe_name` convention: lowercase, strip legal suffixes (Inc., Corp., LLC, Ltd., ULC, GmbH, S.A., Pty), replace spaces and special characters with `_`, collapse consecutive underscores, strip leading/trailing underscores. |
| `logging.py` | Match logging. Writes `entity_matches.json` to the FRESH tier with matches, unmatched (with per-pass attempt details), and rejected arrays. |

### Inventory (`src/dd_agents/inventory/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports inventory builder functions. |
| `discovery.py` | File discovery: runs `tree`, `find`, and `file --mime-type` commands (or Python equivalents) with exclude patterns. Produces `tree.txt`, `files.txt`, `file_types.txt` in the FRESH inventory directory. Detects data room changes vs prior run inventory snapshot. |
| `customers.py` | Customer registry builder. Parses `tree.txt` to identify the folder hierarchy (group/customer/files). Produces `customers.csv` (group, name, safe_name, path, file_count, file_list) and `counts.json` (total_files, total_customers, total_reference_files, files_by_extension, files_by_group, customers_by_group). Computes `customer_safe_name` for each customer. |
| `reference_files.py` | Reference file classifier and router. Identifies files NOT under a customer directory as global reference files. Classifies by category (Financial, Pricing, Corporate/Legal, Operational, Sales, Compliance, HR, Other) and subcategory. Scans for customer name mentions. Assigns files to agents per routing table. Produces `reference_files.json`. |
| `mentions.py` | Customer-mention index builder. Matches customer names found in reference files against `customers.csv` using entity resolution. Produces `customer_mentions.json` with matches, ghost customer gaps (in reference data but no folder), and phantom contract gaps (folder exists but absent from reference data). |
| `integrity.py` | Inventory integrity verifier. Asserts total files = customer files + reference files, no orphan files exist, and all files are classified. Any unclassified file triggers classification and addition. |

### Validation (`src/dd_agents/validation/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports validation gate functions. |
| `coverage.py` | Coverage gate (pipeline step 17). For each agent type, counts unique `{customer_safe_name}.json` files against expected customer count. Detects missing customers, aggregate files, and empty outputs. Triggers re-spawn for missing customers. Enforces clean-result entries for customers with zero findings. |
| `numerical_audit.py` | 5-layer numerical audit. Layer 1: source traceability (every number traces to a file). Layer 2: arithmetic verification (re-derive from source). Layer 3: cross-source consistency (customers.csv vs counts.json, etc.). Layer 4: cross-format parity (Excel vs JSON spot-check). Layer 5: semantic reasonableness (flag implausible numbers). Blocking gate between analysis and Excel generation. |
| `qa_audit.py` | Full QA audit implementing all 16+ checks from SKILL.md section 8: agent manifest reconciliation, file coverage, customer coverage, governance completeness, citation integrity, gap completeness, cross-reference completeness, domain coverage, audit log verification, extraction quality, merge/dedup, report sheets, entity resolution, numerical manifest, contract date reconciliation, and report consistency. Produces `audit.json`. |
| `dod.py` | 30 Definition of Done checks mapped to SKILL.md section 9. Each check is a function returning pass/fail with details. Checks are grouped: Core Analysis (1-12), Reporting and Audit (13-19), Judge Quality (20-23, conditional), Incremental Mode (24-27, conditional), Report Consistency (28-30). |
| `schema_validator.py` | Report schema validation. After Excel generation, verifies all sheets exist, columns match schema, sort orders are correct, and conditional formatting is applied. Cross-checks against `report_schema.json`. |

### Reporting (`src/dd_agents/reporting/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports reporting functions. |
| `merge.py` | Finding merge and deduplication across 4 specialist agents per customer. Collects per-agent JSONs, merges findings (keeping highest severity on duplicates, longest exact_quote), consolidates governance graphs (Legal primary), merges cross-references, and transforms agent-internal findings to framework-schema-compliant findings with auto-generated IDs. Writes merged per-customer JSONs and merged gap files. Preserves incremental carry-forward metadata. |
| `diff.py` | Report diff builder. Compares current findings against prior run using match keys (customer + category + citation location). Detects new findings, resolved findings, changed severity, new/resolved gaps, new/removed customers. Writes `report_diff.json`. |
| `excel.py` | Excel report generation from `report_schema.json`. Generates `build_report.py` script that reads the schema, loads all data sources, and produces the 14-sheet Excel workbook. Implements schema-driven generation (no hardcoded sheet definitions). Handles activation conditions, conditional formatting, summary formulas, freeze panes, and auto-filters. |
| `contract_dates.py` | Contract date reconciliation. When `source_of_truth.customer_database` exists, reconciles database expiry dates against data room evidence. Classifies customers as Active-Database Stale, Active-Auto-Renewal, Likely Active-Needs Confirmation, Expired-Confirmed, or Expired-No Contracts. Writes `contract_date_reconciliation.json`. |

### Persistence (`src/dd_agents/persistence/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports persistence managers. |
| `tiers.py` | Three-tier lifecycle manager implementing PERMANENT (never wiped: index/text, checksums, extraction quality, entity cache, all prior runs, run history), VERSIONED (archived per run: findings, audit, manifests, classification, metadata), and FRESH (rebuilt every run: inventory, reports) tier operations. |
| `run_manager.py` | Run initialization: generates run_id, creates `{RUN_DIR}` with all subdirectories (findings per agent with gaps, judge, report, audit per agent), snapshots prior inventory, wipes FRESH tier. Run finalization: updates `latest` symlink, writes final metadata with file checksums and completion status. |
| `incremental.py` | Customer classification for incremental mode. Compares current vs prior per-customer file checksums. Classifies as NEW, CHANGED, STALE_REFRESH (>= staleness_threshold consecutive unchanged runs), UNCHANGED, or DELETED. Writes `classification.json`. Carries forward UNCHANGED customer findings with `_carried_forward: true` metadata. |

### Hooks (`src/dd_agents/hooks/`)

> **Note**: The orchestrator (`05-orchestrator.md` step 16) imports hooks via `agents.hooks` and `agents.mcp_server`. These paths are satisfied by package-level re-exports in `agents/__init__.py` that delegate to `hooks/` and `tools/` respectively.

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports hook builders. Also re-exported from `agents/__init__.py` for convenience (`from dd_agents.agents.hooks import ...`). |
| `pre_tool.py` | PreToolUse hooks. Path guard: blocks Write/Edit outside the project `_dd/` directory. Bash guard: blocks destructive commands (`rm -rf`, `git push --force`, etc.). File size guard: warns on writes exceeding configurable size limit. |
| `post_tool.py` | PostToolUse hooks. JSON validation: when an agent writes a `{customer_safe_name}.json` file, validates it against the `CustomerJSON` Pydantic model. Manifest validation: when `coverage_manifest.json` is written, validates against `CoverageManifest` model. Audit entry validation: spot-checks JSONL entries for required fields. |
| `stop.py` | Stop hooks. Coverage enforcement: blocks agent stop if customer output count does not match expected count. Manifest enforcement: blocks stop if `coverage_manifest.json` has not been written. Audit log enforcement: warns (does not block) if `audit_log.jsonl` is missing. |

### Tools (`src/dd_agents/tools/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Exports all tool functions and `create_tool_server()`. |
| `server.py` | MCP server setup using `create_sdk_mcp_server()`. Registers all custom tools. Configures tool availability per agent type (specialists get validation tools; Judge gets verification tools; Reporting Lead gets all). |
| `validate_finding.py` | `validate_finding` tool: accepts a finding JSON, validates against `Finding` Pydantic model, returns structured error list or "valid". Checks citation requirements per severity level. |
| `validate_gap.py` | `validate_gap` tool: accepts a gap JSON, validates against `Gap` model, returns errors or "valid". Checks required fields and enum values. |
| `validate_manifest.py` | `validate_manifest` tool: accepts coverage manifest JSON, validates against `CoverageManifest` model, checks `coverage_pct >= 0.90` and `fallback_attempted` on failed files. |
| `verify_citation.py` | `verify_citation` tool: given a citation, checks that `source_path` exists in `files.txt` and that `exact_quote` can be found (substring search) in the extracted text. Returns match status and location. |
| `get_customer_files.py` | `get_customer_files` tool: returns the file list and count for a given customer name from inventory. Used by agents during analysis to confirm they have processed all files. |
| `resolve_entity.py` | `resolve_entity` tool: checks entity resolution cache for a given name, returns canonical name, match method, and confidence, or "unresolved" if not found. |
| `report_progress.py` | `report_progress` tool: allows agents to report progress back to the orchestrator (e.g., customers processed so far). Used for liveness monitoring and progress tracking. |

### Vector Store (`src/dd_agents/vector_store/`)

| File | Responsibilities |
|------|-----------------|
| `__init__.py` | Conditional import; exports are no-ops if ChromaDB is not installed. |
| `store.py` | ChromaDB wrapper. Creates/loads a collection for the current data room. Indexes extracted text chunks with metadata (customer, file path, doc type). Provides similarity search with configurable top-k and distance threshold. |
| `embeddings.py` | Embedding generation for extracted text. Chunks documents into overlapping segments (configurable size and overlap). Generates embeddings using ChromaDB's default embedding function or a configurable alternative. |

---

## Module Dependency Table

This table shows which modules import from which, establishing the dependency graph within the package.

| Module | Imports From |
|--------|-------------|
| `cli` | `config`, `orchestrator.engine`, `constants` |
| `config` | `models.config`, `constants` |
| `constants` | (none -- leaf module) |
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
| `agents.prompt_builder` | `models.config`, `models.inventory`, `models.finding`, `entity_resolution.safe_name`, `constants` |
| `agents.specialists` | `agents.base`, `agents.prompt_builder` |
| `agents.judge` | `agents.base`, `agents.prompt_builder`, `models.audit` |
| `agents.reporting_lead` | `agents.base`, `agents.prompt_builder`, `models.reporting` |
| `extraction.pipeline` | `extraction.markitdown`, `extraction.ocr`, `extraction.cache`, `extraction.quality`, `constants` |
| `extraction.markitdown` | `constants` |
| `extraction.ocr` | `constants` |
| `extraction.cache` | `constants` |
| `extraction.quality` | `models.inventory` (for `FileEntry`) |
| `entity_resolution.matcher` | `entity_resolution.cache`, `entity_resolution.safe_name`, `entity_resolution.logging`, `models.entity`, `models.config` (for `EntityAliases`) |
| `entity_resolution.cache` | `models.entity` |
| `entity_resolution.safe_name` | (standalone utility -- leaf module) |
| `entity_resolution.logging` | `models.entity` |
| `inventory.discovery` | `constants` |
| `inventory.customers` | `entity_resolution.safe_name`, `models.inventory` |
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
| `tools.server` | `tools.validate_finding`, `tools.validate_gap`, `tools.validate_manifest`, `tools.verify_citation`, `tools.get_customer_files`, `tools.resolve_entity`, `tools.report_progress` |
| `tools.validate_finding` | `models.finding` |
| `tools.validate_gap` | `models.finding` |
| `tools.validate_manifest` | `models.manifest` |
| `tools.verify_citation` | `models.inventory` |
| `tools.get_customer_files` | `models.inventory` |
| `tools.resolve_entity` | `entity_resolution.cache`, `models.entity` |
| `tools.report_progress` | `orchestrator.state` |
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
# All dependencies are permissively licensed open-source (Apache 2.0, MIT, BSD).
# No commercial or subscription dependencies.
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
