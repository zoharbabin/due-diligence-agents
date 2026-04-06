# 17 -- File Manifest (101 files)

Every file to create for the Due Diligence Agent SDK project. Each entry includes the file path, module/class it contains, key responsibilities, and an approximate line count estimate.

---

## Core Infrastructure

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 1 | `pyproject.toml` | (build config) | Package definition (name, version, description), Python 3.12+ requirement, all dependencies (`claude-agent-sdk>=0.1.39`, `pydantic>=2.0`, `openpyxl>=3.1`, `rapidfuzz>=3.0`, `scikit-learn>=1.3`, `click>=8.0`, `rich>=13.0`, `markitdown>=0.1`), optional deps (chromadb, pytesseract, dev tools), `[project.scripts]` entry point, hatchling build system config. | ~60 |
| 2 | `README.md` | (documentation) | Project overview, quick start, CLI usage, architecture summary, link to docs/setup.md. | ~80 |
| 3 | `.env.example` | (env template) | Template for required environment variables: `ANTHROPIC_API_KEY`, optional `CHROMADB_ENABLED`, `LOG_LEVEL`, `MAX_AGENT_RETRIES`. | ~15 |
| 4 | `src/dd_agents/__init__.py` | Package root | Version string export (`__version__`), re-export of key public classes (`DealConfig`, `PipelineEngine`, `PipelineState`). | ~15 |
| 5 | `src/dd_agents/cli.py` | `main()`, Click/Typer commands | CLI entry point: `run` command accepting deal-config.json path, `--mode` override (full/incremental), `--resume` for checkpoint recovery, `--dry-run` for prompt preview, `--verbose` flag. Wires up config loader, orchestrator, and starts the pipeline. | ~120 |
| 6 | `src/dd_agents/config.py` | `load_deal_config()`, `validate_config()` | Loads deal-config.json from path, validates against JSON Schema (`config/deal-config.schema.json`), deserializes into `DealConfig` Pydantic model, checks minimum `config_version >= 1.0.0`, resolves `report_schema_override` path, computes config hash (SHA-256). | ~100 |
| 7 | `src/dd_agents/constants.py` | Path constants, enums | `_DD_DIR = "_dd"`, `SKILL_DIR = "_dd/forensic-dd"`, `INDEX_DIR`, `INVENTORY_DIR`, `RUNS_DIR`, exclude patterns for file discovery (`.git`, `node_modules`, `_dd`, etc.), exclude file patterns (`*.DS_Store`, `Due_Diligence*`, etc.), agent name list, domain registry defaults. | ~80 |

---

## Models

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 8 | `src/dd_agents/models/__init__.py` | Re-exports | Re-exports all model classes from sub-modules for `from dd_agents.models import Finding, Gap, ...` convenience. | ~60 |
| 9 | `src/dd_agents/models/config.py` | `DealConfig`, `BuyerInfo`, `TargetInfo`, `PreviousName`, `AcquiredEntity`, `EntityAliases`, `SourceOfTruth`, `CustomerDatabase`, `CustomerDatabaseColumns`, `ActiveFilter`, `KeyExecutive`, `DealInfo`, `SamplingRates`, `JudgeConfig`, `ExecutionConfig`, `ReportingConfig`, `ForensicDDConfig`, `DomainConfig`, `CustomDomain`, `DealType`, `ExecutionMode` | Complete deal-config.json hierarchy as Pydantic v2 models with validators for config_version semver check, acquisition_date format, and field constraints from deal-config.schema.json. | ~250 |
| 10 | `src/dd_agents/models/finding.py` | `Finding`, `AgentFinding`, `Citation`, `Gap`, `FileHeader`, `CrossReferenceData`, `CrossReference`, `CrossReferenceSource`, `CrossReferenceSummary`, `CustomerAnalysis`, `MergedCustomerOutput`, `Severity`, `Confidence`, `SourceType`, `AgentName`, `GapType`, `DetectionMethod` | Core analysis output models. Finding with id pattern validator, P0/P1 citation enforcement, Citation with web_research access_date validator, FileHeader with governed_by validator (file path / SELF / UNRESOLVED), Gap with all required fields. Customer analysis output model (per-agent) and merged output model (post-merge). All shared enums. | ~400 |
| 11 | `src/dd_agents/models/inventory.py` | `CustomerEntry`, `FileEntry`, `ReferenceFile`, `CountsJson`, `CustomerMention`, `CustomerMentionIndex`, `ExtractionQualityEntry`, `ReferenceFileCategory`, `ExtractionQualityMethod` | Data room inventory models: customer registry entries, file metadata, reference file classification with routing, aggregate counts, customer-mention index with ghost/phantom detection fields, extraction quality per-file records. | ~160 |
| 12 | `src/dd_agents/models/manifest.py` | `CoverageManifest`, `FileRead`, `FileSkipped`, `FileFailed`, `ManifestCustomer`, `FileSkipReason` | Agent coverage manifest models with forensic-dd extensions (reference_files_processed). Coverage percentage constraint (0.0-1.0). Skip reason enum. | ~100 |
| 13 | `src/dd_agents/models/audit.py` | `AuditEntry`, `AuditAction`, `AuditCheck`, `AuditSummary`, `AuditReport`, `QualityScores`, `AgentScore`, `AgentScoreDimensions`, `UnitScore`, `SpotCheck`, `Contradiction`, `SpotCheckDimension`, `SpotCheckResult` | Audit trail models (single JSONL entry, consolidated audit.json), quality/Judge models (spot checks with 5 dimensions, contradictions, per-agent scoring with weighted dimensions, per-unit scoring). | ~250 |
| 14 | `src/dd_agents/models/persistence.py` | `RunMetadata`, `Classification`, `ClassificationSummary`, `CustomerClassEntry`, `CustomerClassificationStatus`, `RunHistoryEntry`, `AnalysisUnitCounts`, `FindingCounts` | Run lifecycle models: metadata (initialization + finalization fields), incremental classification with per-customer status, run history entry for the shared run_history.json. | ~180 |
| 15 | `src/dd_agents/models/reporting.py` | `ReportSchema`, `SheetDef`, `ColumnDef`, `SortOrder`, `ConditionalFormat`, `SummaryFormulaEntry`, `GlobalFormatting`, `SeverityColor`, `ReportDiff`, `ReportDiffChange`, `ReportDiffSummary`, `ContractDateReconciliation`, `ContractDateReconciliationEntry` | Report schema models for machine-readable report_schema.json parsing (14 sheets with columns, sorts, formatting), report diff models, and contract date reconciliation models. | ~220 |
| 16 | `src/dd_agents/models/entity.py` | `EntityMatch`, `EntityMatchLog`, `EntityCache`, `EntityCacheEntry`, `EntityCacheConfigSnapshot`, `UnmatchedEntity`, `UnmatchedCacheEntry`, `RejectedMatch`, `MatchAttempt` | Entity resolution models: confirmed matches, unmatched entities with per-pass attempt details, rejected matches, PERMANENT cache structure with per-entry invalidation support and config snapshot. | ~160 |
| 17 | `src/dd_agents/models/governance.py` | `GovernanceEdge`, `GovernanceGraph`, `GovernanceCitation`, `GovernanceRelationship` | Governance graph models. GovernanceGraph is a structured Pydantic model (NOT a dict) with `edges: list[GovernanceEdge]` and utility methods: `get_governing_doc()`, `get_governed_docs()`, `get_unresolved_files()`, `has_cycles()`. | ~120 |
| 18 | `src/dd_agents/models/numerical.py` | `NumericalManifest`, `ManifestEntry` | Numerical audit manifest with traceable entries (id, label, value, source_file, derivation, used_in, cross_check, verified). Manifest enforces minimum 10 entries (N001-N010). | ~60 |

---

## Orchestrator

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 19 | `src/dd_agents/orchestrator/__init__.py` | Re-exports | Exports `PipelineEngine`, `PipelineState`, `PipelineStep`. | ~10 |
| 20 | `src/dd_agents/orchestrator/engine.py` | `PipelineEngine`, `BlockingGateError`, `RecoverableError`, `AgentFailureError`, `PartialFailureError` | Async state machine driving all 35 pipeline steps. Each step is an async method on `PipelineEngine` (e.g., `step_01_validate_config`, `step_17_coverage_gate`). Controls step transitions, blocking gates (extraction at step 5, coverage at step 17, numerical audit at step 27, QA at step 28, post-generation at step 31), error recovery with configurable retry limits, and conditional steps. Main entry: `async run(resume_from_step: int = 0) -> PipelineState`. | ~500 |
| 20a | `src/dd_agents/orchestrator/steps.py` | `PipelineStep` | `PipelineStep(str, Enum)` with all 35 steps as string values (e.g., `"01_validate_config"`). Properties: `step_number`, `is_blocking_gate`, `is_conditional`. Defines `_BLOCKING_GATES` and `_CONDITIONAL_STEPS` frozensets. | ~95 |
| 21 | `src/dd_agents/orchestrator/state.py` | `PipelineState`, `StepResult`, `PipelineError` | `PipelineState` dataclass holding: current_step, run_id, run_dir, skill_dir, config (DealConfig), inventory paths, customer list, customer safe name map, agent results, validation results, error log. `StepResult` and `PipelineError` dataclasses. Imports `PipelineStep` from `steps.py`. JSON-serializable for checkpoint save/restore via `to_checkpoint()` / `from_checkpoint()`. | ~260 |
| 22 | `src/dd_agents/orchestrator/checkpoints.py` | `CheckpointManager`, `save()`, `load()`, `latest()`, `clean()` | Serializes PipelineState to JSON after each step via atomic writes (write .tmp, rename). Enables crash recovery: `load()` deserializes and returns state at specified step. Stored at `{skill_dir}/checkpoints/step_{NN}.json`. | ~80 |
| 23 | `src/dd_agents/orchestrator/team.py` | `TeamManager`, `AgentStatus` | Agent team management. Spawns specialist agents in parallel using asyncio. Monitors liveness via output directory polling (detect files written). Detects silent context exhaustion (no new files for configurable timeout). Coordinates retry/re-spawn per error recovery protocol (SKILL.md section 7). Tracks per-agent status: running, completed, failed, retrying. | ~200 |
| 23a | _(removed)_ | — | Pipeline steps are implemented as methods within `orchestrator/engine.py` (file #20), not as separate files. Each step is an async method on `PipelineEngine` (e.g., `async def step_01_validate_config(self) -> PipelineState`). The 35 steps are registered in the engine's step dispatch table. This avoids 35 small files that would each import from the same set of modules. | — |

---

## Agents

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 24 | `src/dd_agents/agents/__init__.py` | Re-exports | Exports agent runner classes and prompt builder. | ~15 |
| 25 | `src/dd_agents/agents/base.py` | `BaseAgentRunner` | Abstract base class for all agent runners. Common logic: SDK client setup (`ClaudeSDKClient`), `ClaudeAgentOptions` configuration (model selection, max_tokens, allowed_tools), HookMatcher registration, MCP tool server attachment, agent spawn via `query()`, output collection, timeout monitoring (30-min wall clock), result validation. Subclassed by specialists, Judge, and Reporting Lead. | ~200 |
| 26 | `src/dd_agents/agents/prompt_builder.py` | `PromptBuilder`, `estimate_token_count()`, `batch_customers()` | Assembles complete agent prompts from: deal config context, customer list with file paths and pre-computed safe names, reference file extracted text, domain-definitions rules (extraction, governance, gap, cross-reference), manifest/output format instructions. Implements prompt size estimation (~500 tokens deal context + ~50 tokens/customer + measured reference text + ~3000 tokens rules). Splits customers into batches when estimate exceeds 80,000 tokens. | ~350 |
| 27 | `src/dd_agents/agents/specialists.py` | `LegalAgent`, `FinanceAgent`, `CommercialAgent`, `ProductTechAgent` | Four specialist agent runner subclasses of `BaseAgentRunner`. Each provides: agent-specific focus area instructions (from agent-prompts.md section 3), reference file category routing (Legal: Corporate/Legal + Compliance; Finance: Financial + Pricing; Commercial: Pricing + Sales + Operational; ProductTech: Operational + Compliance), and model selection (default: claude-sonnet-4-20250514). | ~250 |
| 28 | `src/dd_agents/agents/judge.py` | `JudgeAgent`, `JudgeIterationResult` | Judge agent runner implementing the full iteration loop. Spawns Judge with all specialist outputs, extracted text, reference files, and deal context. Parses `quality_scores.json`. Checks per-agent scores against threshold (default 70). If any agent below threshold: identifies up to 5 lowest-scoring customers, spawns targeted re-analysis, runs Judge Round 2 with blend formula (70% new + 30% prior). Forces finalization with `_quality_caveat` metadata if still below after max rounds. | ~250 |
| 29 | `src/dd_agents/agents/reporting_lead.py` | `ReportingLeadAgent` | Reporting Lead agent runner. Provides: full reporting-protocol rules, numerical-validation rules, merge/dedup protocol, report schema path (default or override), all findings and index paths, Judge quality scores if available, deal-config for _Metadata sheet. Implements checkpoint awareness for large customer sets (>100 customers). Model selection: claude-sonnet-4-20250514. | ~180 |

---

## Extraction

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 30 | `src/dd_agents/extraction/__init__.py` | Re-exports | Exports `ExtractionPipeline`. | ~10 |
| 31 | `src/dd_agents/extraction/pipeline.py` | `ExtractionPipeline`, `extract_all()` | Extraction orchestrator. Iterates all non-plaintext files from `files.txt`. For each file: check checksum cache, if miss run fallback chain (markitdown -> pdftotext -> OCR -> Read), write extracted markdown to `index/text/`, record quality. Implements blocking gate: refuses to proceed unless both `checksums.sha256` and `extraction_quality.json` exist and are non-empty. Detects systemic failure (>50% primary method failures). Removes stale extractions for deleted files. | ~200 |
| 32 | `src/dd_agents/extraction/markitdown.py` | `MarkitdownExtractor`, `extract_file()` | Wrapper around `markitdown` CLI/library. Handles PDF (text and scanned), Word, Excel, PPT, and images with OCR. Returns extracted text as markdown string. Raises `ExtractionError` on failure. Configurable timeout per file (default 2 minutes). | ~80 |
| 33 | `src/dd_agents/extraction/ocr.py` | `OCRExtractor`, `extract_with_ocr()` | OCR fallback using pytesseract. Creates working directory at `~/ocr_work/`. Handles scanned PDFs (convert to images first) and image files. Returns extracted text. Guards against pytesseract not being installed (optional dependency). | ~100 |
| 34 | `src/dd_agents/extraction/cache.py` | `ExtractionCache`, `compute_checksum()`, `is_cached()`, `get_cached_path()` | SHA-256 checksum-based extraction cache. Maintains `checksums.sha256` mapping each source file to its hash. On re-runs, returns cached extraction path if hash matches. Removes stale entries for deleted/modified files. All operations on the PERMANENT tier. | ~80 |
| 35 | `src/dd_agents/extraction/quality.py` | `ExtractionQualityTracker`, `record_quality()`, `load_quality()` | Tracks and persists extraction quality per file. Writes/reads `extraction_quality.json`. Records method used, bytes extracted, confidence score, and fallback chain attempted. Provides summary stats (success rate, method distribution). | ~80 |
| 35a | `src/dd_agents/extraction/tabular.py` | `extract_excel_smart()`, `detect_sub_tables()` | Smart Excel extraction with structure preservation: date serial number to ISO-8601 conversion, column header preservation as markdown table headers, sheet separation, currency/percentage formatting, sub-table detection via blank rows, wide table handling (>15 cols). Used as improved openpyxl fallback in extraction pipeline. Research basis: `22-llm-robustness.md` §7. | ~150 |
| 35b | `src/dd_agents/extraction/chunking.py` | `chunk_document()`, `chunk_tabular()`, `Chunk` | Clause-aware document chunking for optional vector store indexing. Splits at section/clause boundaries using regex patterns for legal headings, numbered subsections, recitals, schedules. Target ~3,500 chars per chunk with ~700-char overlap (per AG RAG report). Merges short sections (<200 chars). Prepends document context (50-100 tokens) per Anthropic contextual retrieval findings. Separate tabular chunking preserves header rows. Research basis: `22-llm-robustness.md` §2. | ~200 |

---

## Entity Resolution

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 36 | `src/dd_agents/entity_resolution/__init__.py` | Re-exports | Exports `EntityResolver`, `compute_safe_name`. | ~10 |
| 37 | `src/dd_agents/entity_resolution/matcher.py` | `EntityResolver`, `resolve_name()`, `resolve_all()` | Main resolver implementing the 6-pass cascading matcher. Pass 1: preprocessing (lowercase, strip legal suffixes, strip punctuation, collapse whitespace). Pass 2: exact match. Pass 3: alias lookup from `entity_aliases.canonical_to_variants`. Pass 4: fuzzy match using `rapidfuzz.fuzz.token_sort_ratio` with length-dependent thresholds (>=88 for >8 chars, >=95 for 5-8 chars). Pass 5: TF-IDF cosine similarity on char n-grams (3,4) for lists >50 names, threshold >=0.80. Pass 6: parent-child lookup. Enforces short name guard (<=5 chars never fuzzy), exclusion list rejection. Checks PERMANENT cache before running passes. | ~300 |
| 38 | `src/dd_agents/entity_resolution/cache.py` | `EntityResolutionCache`, `lookup()`, `update()`, `invalidate_changed_entries()`, `save()`, `load()` | PERMANENT tier cache at `_dd/entity_resolution_cache.json`. Cache lookup before 6-pass matcher. Per-entry invalidation on config change: computes diff of added/removed aliases, exclusions, parent-child changes, and invalidates only affected entries. Confirmation count increment and `last_confirmed_run` update on cache hit. Full rebuild fallback when diff cannot be computed. | ~200 |
| 39 | `src/dd_agents/entity_resolution/safe_name.py` | `compute_safe_name()` | Implements the `customer_safe_name` convention: lowercase, strip legal suffixes (Inc., Corp., LLC, Ltd., ULC, GmbH, S.A., Pty, L.P.), replace spaces and special characters (`&`, `'`, `/`, `,`, `.`, `-`) with `_`, collapse consecutive underscores, strip leading/trailing underscores. Examples: "Global Analytics Group" -> "global_analytics_group", "Alpine Systems, Inc." -> "alpine_systems". | ~50 |
| 40 | `src/dd_agents/entity_resolution/logging.py` | `MatchLogger`, `write_match_log()`, `load_match_log()` | Match logging to `_dd/forensic-dd/inventory/entity_matches.json`. Collects matches, unmatched (with per-pass attempt details), and rejected arrays during resolution. Serializes to `EntityMatchLog` model. | ~60 |

---

## Inventory

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 41 | `src/dd_agents/inventory/__init__.py` | Re-exports | Exports inventory builder functions. | ~10 |
| 42 | `src/dd_agents/inventory/discovery.py` | `FileDiscovery`, `discover_files()`, `detect_data_room_changes()` | File discovery: executes `tree` command (or Python walk) with exclude patterns, produces `tree.txt`. Executes `find` (or Python walk) for `files.txt` and `file --mime-type` for `file_types.txt`. All output to FRESH inventory directory. Compares current `files.txt` against prior run's `inventory_snapshot/files.txt` for change detection. | ~150 |
| 43 | `src/dd_agents/inventory/customers.py` | `CustomerRegistryBuilder`, `build_registry()`, `build_counts()` | Parses `tree.txt` to identify folder hierarchy (group/customer/files). Produces `customers.csv` with columns: group, name, safe_name, path, file_count, file_list. Produces `counts.json` with total_files, total_customers, total_reference_files, files_by_extension, files_by_group, customers_by_group. Computes `customer_safe_name` for each customer using `entity_resolution.safe_name`. | ~150 |
| 44 | `src/dd_agents/inventory/reference_files.py` | `ReferenceFileClassifier`, `classify_reference_files()`, `route_to_agents()` | Identifies files NOT under a customer directory. Classifies by category (Financial, Pricing, Corporate/Legal, Operational, Sales, Compliance, HR, Other) and subcategory. Scans extracted text for customer name mentions. Assigns to agents per routing table (Legal: Corporate/Legal + Compliance; Finance: Financial + Pricing; Commercial: Pricing + Sales + Operational; ProductTech: Operational + Compliance). Writes `reference_files.json`. Every file assigned to >= 1 agent. | ~180 |
| 45 | `src/dd_agents/inventory/mentions.py` | `CustomerMentionIndexBuilder`, `build_mention_index()` | Matches customer names from reference files against `customers.csv` using entity resolution. Builds `customer_mentions.json` with matches, `unmatched_in_reference` (ghost customers -> P1 gaps), and `customers_without_reference_data` (phantom contracts -> P2 gaps). | ~100 |
| 46 | `src/dd_agents/inventory/integrity.py` | `InventoryIntegrityVerifier`, `verify_integrity()` | Asserts total files = customer files + reference files. Detects orphan files (not under any customer and not classified as reference). Any unclassified file -> classify and add to appropriate category. Returns pass/fail with details. | ~80 |

---

## Validation

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 47 | `src/dd_agents/validation/__init__.py` | Re-exports | Exports validation gate functions. | ~10 |
| 48 | `src/dd_agents/validation/coverage.py` | `CoverageGate`, `validate_specialist_coverage()`, `validate_clean_results()` | Coverage gate at pipeline step 17. For each agent type: counts `{customer_safe_name}.json` files in output directory, compares against expected customer count. Identifies missing customers. Detects aggregate files (`_global.json`, `batch_summary.json`). Spot-checks empty customer JSONs for `domain_reviewed_no_issues` entries. Returns list of missing customers per agent for re-spawn. | ~150 |
| 49 | `src/dd_agents/validation/numerical_audit.py` | `NumericalAuditor`, `run_six_layer_audit()`, `validate_layer_1()` through `validate_layer_6()` | 6-layer numerical validation. Layer 1: source traceability (verify source_file exists). Layer 2: arithmetic verification (re-derive each number from source). Layer 3: cross-source consistency (customers.csv rowcount vs counts.json, etc.). Layer 4: cross-format parity (read Excel cells, compare to manifest). Layer 5: semantic reasonableness (flag implausible numbers). Layer 6: cross-run consistency (compare with prior run values). Returns per-layer pass/fail. Blocking gate before Excel generation (Layers 1-3, 5-6 must pass). | ~250 |
| 50 | `src/dd_agents/validation/qa_audit.py` | `QAAuditor`, `run_all_checks()`, `build_audit_json()` | Implements all 16+ QA checks from SKILL.md section 8: agent_manifest_reconciliation, customer_coverage, file_coverage, governance_completeness, citation_integrity, gap_completeness, cross_reference_completeness, domain_coverage, audit_logs, extraction_quality, merge_dedup, report_sheets, entity_resolution, numerical_manifest, contract_date_reconciliation, report_consistency. Each check returns an `AuditCheck` with pass/fail and DoD mapping. Builds consolidated `audit.json`. | ~400 |
| 51 | `src/dd_agents/validation/dod.py` | `DoDChecker`, `check_all()`, individual `check_N()` methods | 31 Definition of Done checks from SKILL.md section 9. Grouped: Core Analysis (1-12, always required), Reporting and Audit (13-19, always required), Judge Quality (20-23, conditional on judge.enabled), Incremental Mode (24-27, conditional on execution_mode), Report Consistency (28-30, always required). Returns overall pass/fail and per-check details. | ~300 |
| 52 | `src/dd_agents/validation/schema_validator.py` | `ReportSchemaValidator`, `validate_report()`, `validate_sheet()` | Post-generation report schema validation. Loads generated Excel with openpyxl. Verifies all required sheets exist (per activation conditions). Checks columns match schema definitions (name, order, type). Validates sort orders were applied. Checks conditional formatting rules. Returns pass/fail with specific mismatches. | ~150 |

---

## Reporting

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 53 | `src/dd_agents/reporting/__init__.py` | Re-exports | Exports reporting functions. | ~10 |
| 54 | `src/dd_agents/reporting/merge.py` | `FindingMerger`, `merge_customer_findings()`, `deduplicate_findings()`, `merge_gap_files()`, `transform_to_schema()` | Multi-agent finding merge and dedup per customer. Collects 4 agent JSONs per customer. Dedup logic: same clause + same file -> keep highest severity, longest exact_quote, note multi-agent agreement. Severity escalation on disagreement. Governance graph consolidation (Legal primary). Cross-reference merge. Transform agent-internal findings to framework-schema findings (add id, agent, skill, run_id, timestamp, analysis_unit). Gap file merge with dedup by missing_item. Preserves incremental carry-forward metadata. Writes per-customer merged JSONs. | ~300 |
| 55 | `src/dd_agents/reporting/diff.py` | `ReportDiffBuilder`, `build_diff()`, `match_findings()` | Compares current findings against prior run. Match key: customer + category + citation location. Detects: new_finding, resolved_finding, changed_severity, new_gap, resolved_gap, new_customer, removed_customer. Gap match key: customer + gap_type + missing_item (normalized). Writes `report_diff.json`. | ~150 |
| 56 | `src/dd_agents/reporting/excel.py` | `ExcelGenerator`, `generate_build_script()`, `run_build_script()`, `generate_direct()` | Excel report generation from `report_schema.json`. Two modes: (1) generate `build_report.py` script that reads schema and data files, or (2) direct generation in Python. Schema-driven: iterates `sheets[]`, creates worksheets with exact columns, widths, sorts, conditional formatting, and summary formulas. Handles 14 sheets with activation conditions. Output: `Due_Diligence_Report_{run_id}.xlsx`. | ~350 |
| 57 | `src/dd_agents/reporting/contract_dates.py` | `ContractDateReconciler`, `reconcile_dates()`, `classify_customer_status()` | Contract date reconciliation (SKILL.md section 5). For customers where database shows `contract_end < current_date AND ARR > 0`: searches data room for renewal evidence, detects auto-renewal clauses, classifies status (Active-Database Stale, Active-Auto-Renewal, Likely Active-Needs Confirmation, Expired-Confirmed, Expired-No Contracts). Writes `contract_date_reconciliation.json`. | ~150 |

---

## Persistence

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 58 | `src/dd_agents/persistence/__init__.py` | Re-exports | Exports persistence managers. | ~10 |
| 59 | `src/dd_agents/persistence/tiers.py` | `TierManager`, `ensure_permanent_tier()`, `wipe_fresh_tier()`, `archive_versioned_tier()` | Three-tier lifecycle manager. PERMANENT: never wiped (`index/text/`, `checksums.sha256`, `extraction_quality.json`, `entity_resolution_cache.json`, all `runs/`, `run_history.json`). VERSIONED: archived per run (each run gets its own directory under `runs/{run_id}/`). FRESH: rebuilt every run (inventory directory wiped and recreated). | ~100 |
| 60 | `src/dd_agents/persistence/run_manager.py` | `RunManager`, `initialize_run()`, `finalize_run()`, `generate_run_id()` | Run initialization: generates `run_id` (UTC timestamp `YYYYMMDD_HHMMSS`), creates full directory tree under `{RUN_DIR}` (findings per agent with gaps, judge, report, audit per agent), snapshots prior inventory to prior run dir, wipes FRESH tier. Run finalization: updates `latest` symlink, writes final `metadata.json` with file_checksums, finding_counts, gap_counts, agent_scores, completion_status. | ~150 |
| 61 | `src/dd_agents/persistence/incremental.py` | `IncrementalClassifier`, `classify_customers()`, `carry_forward_findings()` | Customer classification for incremental mode. Compares current per-customer file checksums against prior run. Classifies each customer (NEW, CHANGED, STALE_REFRESH, UNCHANGED, DELETED). STALE_REFRESH triggered at >= `staleness_threshold` consecutive unchanged runs. Writes `classification.json`. Carry-forward: copies UNCHANGED customer findings with `_carried_forward: true`, `_original_run_id`, and `_consecutive_unchanged_runs` metadata. | ~180 |

---

## Hooks

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 62 | `src/dd_agents/hooks/__init__.py` | Re-exports | Exports hook builder functions. | ~10 |
| 63 | `src/dd_agents/hooks/pre_tool.py` | `build_pre_tool_hooks()`, `PathGuardHook`, `BashGuardHook` | PreToolUse hooks returned as `HookMatcher` configs. Path guard: blocks Write/Edit to paths outside `_dd/` directory tree. Bash guard: blocks destructive bash commands (`rm -rf /`, `git push --force`, etc.). Returns `"block"` result to prevent tool execution when triggered. | ~100 |
| 64 | `src/dd_agents/hooks/post_tool.py` | `build_post_tool_hooks()`, `JSONOutputValidator`, `ManifestValidator` | PostToolUse hooks. JSON output validation: when Write tool creates a `{customer_safe_name}.json` in findings directory, deserializes and validates against `CustomerAnalysis` Pydantic model. Manifest validation: validates `coverage_manifest.json` against `CoverageManifest` model. Logs validation errors to audit. Returns structured error messages for agent correction. | ~120 |
| 65 | `src/dd_agents/hooks/stop.py` | `build_stop_hooks()`, `CoverageStopHook` | Stop hooks. Coverage enforcement: when an agent attempts to stop, counts customer output files against expected count. Blocks stop if count does not match. Manifest enforcement: blocks stop if `coverage_manifest.json` not written. Audit log check: warns (does not block) if `audit_log.jsonl` missing. | ~80 |

---

## Tools

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 66 | `src/dd_agents/tools/__init__.py` | Re-exports | Exports all tool functions and `create_tool_server`. | ~15 |
| 67 | `src/dd_agents/tools/server.py` | `create_tool_server()` | Creates MCP server using `create_sdk_mcp_server()`. Registers all custom tools. Returns server object for attachment to agent options. Configures tool availability: specialists get validation tools, Judge gets verification tools, Reporting Lead gets all tools. | ~60 |
| 68 | `src/dd_agents/tools/validate_finding.py` | `validate_finding()` (decorated with `@tool`) | Accepts finding JSON dict, validates against `Finding` or `AgentFinding` Pydantic model. Returns structured error list (field name, error message) or `{"status": "valid"}`. Checks: required fields present, severity enum valid, citation requirements per severity (P0/P1 need exact_quote), title max length, id pattern. | ~60 |
| 69 | `src/dd_agents/tools/validate_gap.py` | `validate_gap()` (decorated with `@tool`) | Accepts gap JSON dict, validates against `Gap` model. Returns errors or valid status. Checks: all 9 required fields present, gap_type enum valid, detection_method enum valid, priority enum valid, missing_item max length. | ~50 |
| 70 | `src/dd_agents/tools/validate_manifest.py` | `validate_manifest()` (decorated with `@tool`) | Accepts manifest JSON, validates against `CoverageManifest` model. Checks: `coverage_pct >= 0.90`, all `files_failed` have `fallback_attempted: true`, `analysis_units_assigned == analysis_units_completed`, customers array has required fields. Returns errors or valid. | ~60 |
| 71 | `src/dd_agents/tools/verify_citation.py` | `verify_citation()` (decorated with `@tool`) | Given a citation dict (source_path, exact_quote): checks source_path exists in `files.txt`, loads extracted text from `index/text/`, searches for exact_quote (substring, allowing minor whitespace differences). Returns `{"found": true/false, "location": "..."}`. | ~70 |
| 72 | `src/dd_agents/tools/get_customer_files.py` | `get_customer_files()` (decorated with `@tool`) | Accepts customer name or safe_name, looks up in customer registry (`customers.csv`). Returns file list, file count, and customer path. Used by agents to confirm they have processed all files for a customer. | ~50 |
| 73 | `src/dd_agents/tools/resolve_entity.py` | `resolve_entity()` (decorated with `@tool`) | Accepts an entity name string. Checks entity resolution cache for existing match. Returns canonical name, match method, confidence, and match pass number. Returns `{"status": "unresolved"}` if not in cache. | ~50 |
| 73a | `src/dd_agents/tools/report_progress.py` | `report_progress()` (decorated with `@tool`) | Allows agents to report progress (e.g., customers processed, current phase). Used by orchestrator for liveness monitoring and progress tracking. | ~40 |

---

## Reasoning

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 74a | `src/dd_agents/models/ontology.py` | `ContractNode`, `ContractRelationship`, `ContractOntology`, `DocumentType`, `ClauseType`, `RelationshipType`, `PartyRole`, `ClauseNode`, `PartyNode`, `OntologyEdge` | Lightweight contract ontology models: document types, clause types, typed relationships between documents/clauses/parties, ontology node models for graph construction. Extends GovernanceEdge from `04-data-models.md`. Source: `21-ontology-and-reasoning.md` §2. | ~220 |
| 74b | `src/dd_agents/reasoning/contract_graph.py` | `ContractReasoningGraph`, `from_governance_graph()`, `get_clause_provenance()`, `get_amendment_chain()`, `get_effective_terms_at()`, `detect_contradictions()`, `analyze_change_of_control_impact()` | NetworkX-backed contract reasoning graph for deterministic graph-based reasoning. Builds per-customer graph from agent outputs, supports clause provenance tracking, amendment chain traversal, point-in-time state reconstruction, contradiction detection (grant/waive conflict, multi-parent governance, circular governance), and change-of-control impact analysis. Source: `21-ontology-and-reasoning.md` §3. | ~300 |
| 74c | `src/dd_agents/reasoning/verification.py` | `Tier1Verifier`, `Tier2Verifier`, `Tier4Flagger` | Hallucination prevention verification protocol. Tier 1: deterministic structural checks (citation file exists, dates valid, quote non-empty for P0/P1). Tier 2: graph-based checks (chain traversable, no broken links, no governance cycles). Tier 4: human review flagging (P0, invalid chains, Judge failures). Source: `21-ontology-and-reasoning.md` §10. | ~150 |

---

## Vector Store (Optional)

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 74 | `src/dd_agents/vector_store/__init__.py` | Conditional imports | Checks if `chromadb` is installed. Exports `VectorStore` and `Embedder` if available, otherwise exports no-op stubs. | ~20 |
| 75 | `src/dd_agents/vector_store/store.py` | `VectorStore`, `index_document()`, `search()`, `delete_collection()` | ChromaDB wrapper. Creates/loads a persistent collection for the data room. Indexes extracted text chunks with metadata (customer, file_path, doc_type, page). Similarity search with configurable top-k and distance threshold. Collection named `forensic-dd-{data_room_hash}`. | ~120 |
| 76 | `src/dd_agents/vector_store/embeddings.py` | `Embedder`, `chunk_document()`, `generate_embeddings()` | Document chunking and embedding generation. Splits documents into overlapping segments (default: 1000 chars, 200 char overlap). Uses ChromaDB's default embedding function. Returns list of `(chunk_text, metadata, embedding)` tuples. | ~80 |

---

## Tests

| # | File Path | Module / Class | Responsibilities | Est. Lines |
|---|-----------|---------------|-----------------|------------|
| 77 | `tests/conftest.py` | Pytest fixtures | Shared fixtures: `sample_deal_config` (valid DealConfig), `sample_customer_entry`, `sample_finding`, `sample_gap`, `sample_manifest`, `tmp_data_room` (temporary directory with sample files), `tmp_run_dir`, `sample_entity_aliases`. | ~150 |
| 78 | `tests/fixtures/` | (directory) | Test data: `sample_deal_config.json`, `sample_customer_jsons/` (sample agent outputs for 2-3 customers), `sample_data_room/` (minimal data room with 3 customer folders, 2 reference files, ~10 total files), `sample_report_schema.json`. | ~50 (configs) |
| 79 | `tests/unit/test_models.py` | `TestFinding`, `TestGap`, `TestCitation`, `TestFileHeader`, `TestCoverageManifest`, `TestDealConfig`, `TestGovernanceGraph`, etc. | Unit tests for all Pydantic models. Tests: valid construction, required field enforcement, validator triggers (P0 citation requirement, governed_by format, config_version semver, id pattern), serialization with exclude_none, enum validation, edge cases (empty lists, None fields). | ~400 |
| 80 | `tests/unit/test_entity_resolution.py` | `TestEntityResolver`, `TestSixPassMatcher`, `TestCacheInvalidation` | Tests for 6-pass cascading matcher: exact match, alias lookup, fuzzy match (above/below threshold), TF-IDF matching, parent-child lookup, short name guard (<=5 chars rejected from fuzzy), exclusion list rejection. Cache tests: hit/miss, per-entry invalidation on config change, confirmation count increment, stale entry removal. | ~300 |
| 81 | `tests/unit/test_safe_name.py` | `TestComputeSafeName` | Tests for `customer_safe_name` convention: "Global Analytics Group" -> "global_analytics_group", "Alpine Systems, Inc." -> "alpine_systems", "R&D Global" -> "r_d_global", edge cases (leading/trailing underscores, consecutive special chars, all-suffix names). | ~80 |
| 82 | `tests/unit/test_extraction.py` | `TestExtractionPipeline`, `TestChecksumCache`, `TestExtractionQuality` | Tests for extraction pipeline: cache hit/miss, checksum computation, quality tracking, fallback chain order, systemic failure detection (>50% failure rate), stale extraction removal. Mock markitdown/OCR calls. | ~150 |
| 82a | `tests/unit/test_tabular.py` | `TestExcelSmartExtraction`, `TestDateConversion`, `TestSubTableDetection` | Tests for smart Excel extraction: date serial numbers to ISO-8601, currency/percentage formatting, header preservation, sub-table splitting, wide table truncation. Uses sample .xlsx fixtures with known values. Research basis: `22-llm-robustness.md` §7. | ~100 |
| 82b | `tests/unit/test_chunking.py` | `TestClauseAwareChunking`, `TestTabularChunking`, `TestChunkOverlap` | Tests for clause-aware chunking: boundary detection at legal headings, chunk size within target range, overlap consistency, short section merging, document context prepending, tabular header repetition. Uses sample contract text fixtures. Research basis: `22-llm-robustness.md` §2. | ~120 |
| 83 | `tests/unit/test_numerical.py` | `TestNumericalAuditor`, `TestLayerValidation` | Tests for 6-layer numerical audit: Layer 1 (source file existence), Layer 2 (arithmetic re-derivation), Layer 3 (cross-source consistency checks), Layer 5 (reasonableness flags), Layer 6 (cross-run consistency). Tests with intentionally broken manifests to verify failure detection. | ~200 |
| 84 | `tests/unit/test_hooks.py` | `TestPreToolHooks`, `TestPostToolHooks`, `TestStopHooks` | Tests for hooks: path guard blocks writes outside `_dd/`, bash guard blocks dangerous commands, JSON output validator catches invalid customer JSON, coverage stop hook blocks premature agent stop, manifest stop hook blocks stop without manifest. | ~150 |
| 85 | `tests/integration/test_pipeline.py` | `TestPipelinePhases` | Integration tests for pipeline phases with mock agents. Tests step transitions, blocking gate enforcement, checkpoint save/restore, error recovery (agent failure -> re-spawn), incremental mode classification and carry-forward. Requires sample data room fixture. | ~300 |
| 86 | `tests/integration/test_agents.py` | `TestAgentSpawn`, `TestPromptBuilder` | Integration tests for agent lifecycle. Tests prompt construction (complete customer list, reference file text, rules), prompt size estimation accuracy, customer batching logic, output parsing and validation. Requires API key for full agent spawn tests (marked with `@pytest.mark.api`). | ~200 |
| 87 | `tests/integration/test_reporting.py` | `TestFindingMerger`, `TestExcelGenerator`, `TestReportDiff` | Integration tests for reporting pipeline: finding merge across 4 agents for multiple customers, dedup logic (same clause kept once), severity escalation, governance consolidation, Excel generation from schema, report diff detection. Uses sample merged JSONs from fixtures. | ~250 |
| 88 | `tests/e2e/test_full_run.py` | `TestFullPipelineRun` | End-to-end test running the full 35-step pipeline on the sample data room fixture. Verifies all outputs exist: inventory files, per-agent findings, merged findings, audit.json, numerical_manifest.json, Excel report. Marked with `@pytest.mark.e2e` and `@pytest.mark.api` (requires API key, long-running). | ~200 |

---

## Config Files

| # | File Path | Contents | Responsibilities | Est. Lines |
|---|-----------|----------|-----------------|------------|
| 89 | `config/deal-config.template.json` | Template JSON | Copy of the skill's `deal-config.template.json`. Template for users to create their `deal-config.json` with all sections (buyer, target, entity_aliases, source_of_truth, key_executives, deal, judge, execution, reporting, forensic_dd). Includes `_comment` fields explaining each section. | ~210 |
| 90 | `config/deal-config.schema.json` | JSON Schema | Copy of the skill's `deal-config.schema.json`. Machine-readable validation schema for deal-config.json. Defines required sections (config_version, buyer, target, deal), field types, constraints, enum values, and pattern validations. | ~280 |
| 91 | `config/report_schema.json` | Report schema | Copy of the skill's `report_schema.json`. Authoritative definition of the 14-sheet Excel report structure: sheet names, column definitions (name, key, type, width, format), sort orders, conditional formatting rules, summary formulas, activation conditions, global formatting. | ~430 |

---

## Documentation

| # | File Path | Contents | Responsibilities | Est. Lines |
|---|-----------|----------|-----------------|------------|
| 92 | `docs/setup.md` | Setup guide | Installation instructions (pip install, optional deps), environment setup (.env), deal-config.json creation walkthrough, first run guide, troubleshooting common issues (API key, markitdown not found, pytesseract not installed). | ~120 |

---

## File Count Summary

| Category | File Count | Est. Total Lines |
|----------|-----------|-----------------|
| Core Infrastructure | 7 | ~470 |
| Models | 11 | ~1,960 |
| Orchestrator | 6 | ~1,195 |
| Agents | 6 | ~1,245 |
| Extraction | 8 | ~900 |
| Entity Resolution | 5 | ~620 |
| Inventory | 6 | ~670 |
| Validation | 6 | ~1,260 |
| Reporting | 5 | ~960 |
| Persistence | 4 | ~440 |
| Hooks | 4 | ~310 |
| Tools | 9 | ~455 |
| Reasoning | 3 | ~670 |
| Vector Store | 3 | ~220 |
| Tests | 14 | ~2,650 |
| Config | 3 | ~920 |
| Documentation | 1 | ~120 |
| **TOTAL** | **101** | **~15,065** |

Note: Pipeline steps (35 steps) are methods within `orchestrator/engine.py`, not individual files. The previous count of ~134 included 35 step implementation files and their `__init__.py`; these have been consolidated into `engine.py`.
