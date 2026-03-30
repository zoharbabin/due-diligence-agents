# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.5.1] - 2026-03-09

### Added

- **`read_office` MCP tool** (Issue #167, PR #168) — reads binary Office files (.xlsx, .xls, .docx, .doc, .pptx, .ppt) and returns structured text content.
  - openpyxl for .xlsx with streaming row reader, column-letter headers, and char-budget early termination
  - markitdown for .xls, .docx, .doc, .pptx, .ppt
  - Cell sanitization: newlines → spaces, pipes escaped for valid markdown tables
  - Fallback to pre-extracted text from `index/text/` when primary read fails
  - 150K char output truncation
  - Registered in tool server, specialist tools, and prompt builder file access instructions
  - 27 new unit tests covering Excel reading, Word reading, error handling, fallback, truncation, and tool registration
- **Document Precedence Engine** (Issue #163, PR #164) — 5-layer scoring system for document authority ranking.
  - `FolderPriority` — 4-tier folder classification (authoritative/working/supplementary/historical)
  - `VersionChainBuilder` — groups file families, detects version keywords (signed/executed/final/draft)
  - `PrecedenceScorer` — weighted composite score (version 40%, folder 30%, recency 30%)
  - `compute_precedence_index()` — wires all 3 components into pipeline step 6
  - Flows to prompts (step 14), respawn (step 17), and merge (step 24)
  - 42 new unit tests

### Fixed

- **Silent exception swallowing** — two `except Exception: pass` blocks now log debug messages instead of silently ignoring errors (`cli.py` finding count parsing, `reference_downloader.py` UTF-8 decode fallback).
- **Contradictory Bash instruction in prompts** — changed `use 'ls -R'` to `use 'Glob(pattern="**/*")'` since agents don't have Bash access (`prompt_builder.py`).

## [0.5.0] - 2026-03-06

### Added

- **Revenue-at-Risk & Financial Impact Quantification** (Issue #102) — new report section with:
  - Per-customer revenue extraction from cross-reference data (ARR, ACV, contract value keywords)
  - Revenue-at-risk waterfall chart (CoC exposure, TfC exposure, concentration risk, pricing risk)
  - Customer concentration treemap sized by revenue with risk-level color coding
  - Financial impact metrics strip (Total ARR, Revenue at Risk, Risk-Adjusted ARR)
  - Data completeness indicator showing revenue coverage percentage
  - `FinancialImpactRenderer` with full HTML escaping and print mode support
- **Red Flag Detection & Quick Scan Mode** (Issue #125) — early deal-killer warning:
  - `--quick-scan` CLI flag for rapid 5-minute red flag assessment
  - `RedFlagScannerAgent` — lightweight single-turn agent scanning 8 deal-killer categories (litigation, IP gaps, undisclosed contracts, key-person dependency, financial restatements, regulatory violations, customer concentration, debt covenants)
  - `RedFlagAssessmentRenderer` — single-page HTML report with stoplight indicators (green/yellow/red), confidence scoring, source citations, and recommended actions
  - `classify_signal()` — deterministic signal classification from flag severity and confidence
  - `RED_FLAG_SCANNER` agent type added to `AgentType` enum
- **Agent Cost Optimization** (Issue #129) — model selection, cost tracking, budget management:
  - 3 preset model profiles: economy (Haiku-heavy, ~$5-8/run), standard (Sonnet-heavy, ~$10-15/run), premium (Opus for synthesis, ~$40-60/run)
  - `AgentModelsConfig` in deal config with per-agent model overrides
  - `CostTracker` — per-agent, per-step token/cost tracking with hard budget limits
  - `ModelProfile` — preset configurations with `get_model_for_agent()` lookup
  - Pricing table for Claude model family (Opus 4.6, Sonnet 4.6, Haiku 4.5)
  - Note: modules delivered and tested; full engine-level integration (automatic token recording, budget enforcement) deferred to Phase 3 pending SDK token-reporting support
- **Parallel Agent Execution Optimization** (Issue #148) — smart batch scheduling:
  - `CustomerComplexity` scoring: file count + document size → simple/medium/complex tiers
  - `BatchScheduler` — priority queue scheduling (simple customers first for fast wins)
  - Token-aware batch splitting with configurable size and token limits
  - Per-step timing already tracked in `StepResult.duration_ms`
  - Note: modules delivered and tested; engine step 16 integration deferred to Phase 3 (current `AgentTeam.spawn_specialists()` batching is functional)
- 68 new unit tests (2259 total) covering red flag scanner, cost tracking, model profiles, batch scheduling, signal classification, and double-counting prevention

## [0.4.2] - 2026-03-06

### Added

- **P0/P1 follow-up verification loop** (Issue #140, AG-6) — mandatory self-verification protocol for all critical findings. Research-proven 9.2% accuracy improvement. Agents must re-read source documents, verify quotes verbatim, check for mitigating clauses, and confirm severity before finalizing P0/P1 findings.
- **Deterministic finding verification** in pre-merge validation (step 23) — P0 findings without citations automatically downgraded to P1; P0 findings without exact_quote downgraded to P1; P1 findings without citations downgraded to P2. Verified findings marked with `"verified": true`.
- **Data room health check** (`dd-agents assess`) — new CLI command (Issue #149) for pre-flight data room quality assessment. Reports file type distribution, extraction readiness, customer folder detection, potential issues, and overall completeness score (0-100).
- **`DataRoomAssessor`** module (`assessment.py`) — scans data room for empty files, unsupported formats, deeply nested structures, and generates actionable recommendations.
- 21 new unit tests (2170 total) covering follow-up prompt generation, deterministic verification, and data room assessment.

### Fixed

- **XSS vulnerability** — HTML-escape RAG status label in sidebar navigation `title` and `aria-label` attributes (`html_base.py`).
- **Severity comparison bug** — replaced fragile string comparison (`sev < max_sev` and `min()`) with explicit `_SEV_RANK` dict lookup for correct P0>P1>P2>P3 ordering in CoC and Privacy analysis renderers (`html_analysis.py`).
- **Missing `Not_Found` gap type** — added `NOT_FOUND = "Not_Found"` to `GapType` enum. Agents were instructed to use this value but it was missing, causing validation failures.
- **Red flag categories** — 6 new categories (`litigation`, `ip_gap`, `financial_restatement`, `key_person_risk`, `debt_covenant`, `customer_concentration`) added to `VALID_CATEGORIES` in finding validation.

### Changed

- `PromptBuilder.robustness_instructions()` expanded with mandatory 4-step P0/P1 self-verification loop (re-read, quote verify, severity recheck, context check).
- `PromptBuilder.robustness_instructions()` expanded with Red Flag Priority Detection (8 deal-killer patterns).
- Pre-merge validation (step 23) now runs critical finding verification after schema validation.
- Documentation updated: CHANGELOG, IMPLEMENTATION_PLAN test counts.

## [0.4.1] - 2026-03-05

### Added

- **Data quality finding separation** — three-way finding classification (material / data-quality / noise). Data quality findings moved to dedicated "Missing or Incomplete Data" appendix section.
- **Expanded agent analytical depth** — Finance: revenue composition, unit economics, financial projections, cost structure. Commercial: customer segmentation, pricing model, expansion/contraction, competitive positioning.
- **Executive synthesis agent** (`executive_synthesis.py`) — senior M&A partner review producing calibrated Go/No-Go signal, executive narrative, severity overrides, and ranked deal breakers.
- **Severity rubric** in specialist prompts — deal-type-aware P0-P3 calibration criteria with common false-positive avoidance.
- **Softened mechanical risk scoring** — single P0 finding no longer auto-triggers "No-Go"; requires 3+ P0 for "Critical" label.
- 150 new unit tests (2149 total) covering severity recalibration, executive synthesis, data quality classification, expanded agent focus areas, and canonical category mapping.

### Fixed

- **Deprecated openpyxl `alignment.copy()` call** — replaced with `copy()` from stdlib to eliminate DeprecationWarning in search Excel writer.
- **Ruff formatting** — 3 files auto-formatted to comply with ruff format rules.

### Changed

- Gap Analysis section renamed to "Missing or Incomplete Data" and moved to appendix zone in report navigation.
- Wolf pack and category group filtering now excludes data quality findings from main report sections.
- Documentation updated: README (test counts, agent count), IMPLEMENTATION_PLAN (test totals), CHANGELOG.

## [0.4.0] - 2026-03-03

### Added

- Board-ready executive HTML report (PR #112, Issue #113) — complete redesign from raw data dump to executive decision briefing.
  - **Sidebar navigation** with scroll tracking, TOC groups (Risk & Analysis, Business Analysis, Domain Detail, Data Quality, Actions & Appendix), RAG status indicators, and confidential badge. Replaces horizontal nav bar.
  - **CSS custom properties** — all colors via `:root` variables for consistent theming (20+ severity, domain, alert, and layout variables).
  - **Executive summary** with Go/No-Go signal, risk heatmap, top 5 deal breakers, key metrics strip, concentration risk (HHI).
  - **Customer-level P0/P1 tables** (`FindingsTableRenderer`) — entity-level severity tables replacing individual finding cards, with alert boxes and top-10 + collapsed rest pattern.
  - **Change of Control analysis** (`CoCAnalysisRenderer`) — CoC findings by entity with consent-required counts and severity matrix.
  - **Data Privacy analysis** (`PrivacyAnalysisRenderer`) — GDPR/CCPA/DPA findings by entity.
  - **Entity Health Tiers** (`CustomerHealthRenderer`) — Tier 1 (Critical/P0), Tier 2 (High/P1), Tier 3 (Standard) classification.
  - **Recommendations engine** (`RecommendationsRenderer`) — deterministic generation of 4-7 prioritized action items (Immediate/Pre-Close/Post-Close/Positive) from data patterns.
  - **Methodology & Limitations** (`MethodologyRenderer`) — process description, agent coverage, data quality metrics, known limitations.
  - **Alert boxes** — 4 severity levels (critical/high/info/good) for narrative context after major data tables.
  - **Topic classification** — business-topic bucketing of findings (CoC, IP, termination, privacy, employment, concentration, pricing, tech debt, security).
  - **Financial extraction** — best-effort regex extraction of dollar amounts from finding text.
  - **Section RAG indicators** — Red/Amber/Green per-section status visible in sidebar navigation.
  - `DashboardRenderer` with wolf pack dedup: P0-only deal breakers capped at 15, similarity-based grouping via `difflib.SequenceMatcher`.
  - `DiffRenderer` for run-over-run change tracking (new/resolved/changed-severity findings).
  - `StrategyRenderer` for optional buyer-context analysis (conditional on `buyer_strategy` config).
  - Category normalization: longest-match keyword algorithm mapping freeform agent categories to 12 canonical categories per domain. Expanded keyword lists (8-11 per category). Data-room folder name detection maps folder-style categories to "Other".
  - 3-way cross-reference match status (match/mismatch/unverified) replacing binary Yes/No.
  - Gap analysis table expanded to 7 columns (added Why Needed, Request to Company, Agent).
  - Terminology: "Customer" replaced with "Entity" in all reporting outputs.
  - `ReportDataComputer` + `ReportComputedData` Pydantic model (55 fields) for single-pass metric computation.
  - 240+ HTML renderer unit tests (up from 129).
- Pre-merge validation and cross-agent anomaly detection (step 23) — deterministic Python replacing the redundant Reporting Lead agent.
  - File completeness checks (4 agent files per customer).
  - JSON integrity validation (catch corrupt/truncated files before merge).
  - Schema spot-checks (required keys in findings and citations).
  - Citation path verification against file inventory.
  - Cross-agent asymmetric risk detection (P0/P1 from one agent + zero from another).
  - Cross-agent severity disagreement detection (2+ level gap on shared categories).
  - Summary matrix (findings-per-agent x customer) for operator visibility.
- Client-side turn enforcement for agents — soft limit at `max_turns`, hard kill at `3x max_turns`.
- `max_budget_usd` now passed to SDK options for cost-based agent termination.
- Respawn timeout wrapper (`asyncio.wait_for`) prevents indefinite agent runs.
- Per-customer agent retry for coverage gaps (step 17 respawn logic).
- Finance agent batch size reduced to 10 customers for better citation quality.
- Citation verification mandate in agent prompts for P0/P1 findings.
- Structured JSON output enforcement in agent system prompts.
- Agent direct file access — Read tool instructions replace extraction indirection.

### Removed

- **Reporting Lead agent** (`reporting_lead.py`) — eliminated entirely. All responsibilities (merge, audit, report generation) are handled by deterministic Python in steps 24-30. Step 23 now completes in <200ms instead of 30-60+ minutes, saving ~$8/run.

### Fixed

- **XSS vulnerability in `render_alert()` body parameter** — body text now HTML-escaped via `html.escape()`, preventing injection through finding descriptions.
- **Wolf pack P0 sorting** — deal breakers now sorted by severity weight (highest impact first) instead of alphabetical, preventing important findings from being dropped when capped at 15.
- **Section RAG severity-aware for CoC/Privacy** — CoC and Privacy RAG indicators now check for P0 findings (red) rather than relying solely on count thresholds.
- **Missing sidebar nav links** — added navigation links for P0/P1 entity tables, Quality Audit, and QA Checks sections.
- **P0 cap warning** — logs a warning when >15 P0 findings exist and the deal breakers list is truncated.
- Customer `safe_name` duplication — prompt enforcement + rapidfuzz validation in merge step.
- Entity cache `save()` missing `run_id` argument (step 34 crash).
- Extraction pipeline docstrings clarified as search-only purpose.
- All stale "reporting_lead" references removed from source code, tests, and output files (comments, docstrings, rule text).

## [0.3.1] - 2026-03-02

### Fixed

- Replaced real bank routing/account numbers in sample invoice with zeroed placeholders.
- Replaced `.io` email domain in sample data with `.example.com` per RFC 2606.
- Replaced real company names in test fixtures with fictional names.
- Removed phantom `reasoning/*` module reference from CLAUDE.md spec table.

### Changed

- Added `authors`, `keywords`, `classifiers`, and `[project.urls]` metadata to `pyproject.toml`.
- Added `data_room` section to `config/deal-config.template.json`.
- Added `node_modules/` and `*.db` to `.gitignore`.
- Updated test counts in README and IMPLEMENTATION_PLAN to reflect current totals (1,680+).

## [0.3.0] - 2026-02-28

### Added

- Entity deduplication module (`entity_resolution/dedup.py`) for post-resolution duplicate detection.
- Pluggable OCR registry (`extraction/ocr_registry.py`) replacing hardcoded OCR backend selection.
- Pluggable document extraction backend (`extraction/backend.py`) replacing hardcoded markitdown dependency.
- Layout-aware PDF extraction (`extraction/layout_pdf.py`) preserving table structure and spatial relationships.
- Visual grounding with bounding-box coordinate support (`extraction/coordinates.py`) for citation anchoring.
- Interactive HTML review report generation (`reporting/html.py`) alongside Excel output.
- Type-safety tests (`test_type_safety.py`) enforcing enum usage over raw strings in models.
- Visual grounding tests (`test_visual_grounding.py`) for citation bounding-box serialization.
- 253 new unit tests (1,291 → 1,544) covering entity dedup, extraction backends, layout PDF, OCR registry, HTML reports, type safety, and visual grounding.

### Fixed

- Citation path resolution now validates against file inventory instead of filesystem, fixing false negatives in containerized environments.
- Gap type normalization uses keyword-stem logic (e.g., "missing" → MISSING_DOCUMENT) instead of exact string matching.
- Cross-reference fields accept both `dict` and `str` types, fixing `AttributeError` on agent output with string cross-references.
- Priority coercion for gaps: string priorities (e.g., "high") are normalized to enum values before validation.
- Numerical audit N008/N009 rederivation formulas now match manifest field names.
- Worker crash handling in concurrent extraction no longer loses the error context.
- Search analyzer answer merging: YES-prefixed free text now correctly beats NO in priority.

### Changed

- Finding model (`models/finding.py`) extended with gap-specific fields and flexible cross-reference types.
- Merge module (`reporting/merge.py`) rewritten with proper gap preservation, citation dedup, and conflict resolution.
- Extraction pipeline hardened with backend abstraction and graceful degradation on missing optional dependencies.

## [0.2.1] - 2026-02-25

### Added

- Structured LLM output across all agent `query()` calls — Pydantic-validated JSON schemas via `output_schema` parameter.
- Ontology and reasoning module (`reasoning/`) with contract ontology, risk scoring, and graph-based reasoning.
- Vector store embeddings module (`vector_store/embeddings.py`) with document chunker.
- Contract search command (`dd-agents search`) with 4-phase analysis, citation verification, and Excel report output.
- Auto-config command (`dd-agents auto-config`) for AI-driven deal configuration generation.

### Fixed

- Engine staleness threshold config key (`staleness_threshold_runs` → `staleness_threshold`).
- Entity resolution empty-string preprocessing collision causing false-positive matches.
- Vector store unsafe dict access in search results parsing.
- Entity resolution pre-computes preprocessed guard list once in `__init__()` instead of per-call.
- Tool parameter naming consistency (`customer_name` → `customer_safe_name` in `get_customer_files`).
- 18 additional bug fixes from comprehensive codebase-wide review (PR #30).

## [0.2.0] - 2026-02-24

### Added

- PDF pre-inspection (`_inspect_pdf`) classifies PDFs before extraction — routes scanned and garbled PDFs directly to OCR, saving ~700ms per file.
- GLM-OCR vision-language model as preferred OCR method (mlx-vlm on Apple Silicon, Ollama cross-platform). Higher accuracy than pytesseract with structured Markdown output.
- Claude vision as last-resort fallback for images and PDFs that all OCR methods fail on — uses Claude Agent SDK to visually examine files.
- Control-character corruption detection (`_has_control_char_corruption`) catches garbled text from PDFs with missing /ToUnicode CMap entries.
- Watermark detection (`_is_watermark_only`) catches DocuSign overlay-only PDFs where >50% of lines are identical repeated strings.
- Binary image detection in readability gates — PNG/JPEG magic bytes, U+FFFD replacement character ratio, improved printable character counting.
- Confidence scaling (`_scale_confidence`) — base scores now scale by actual-vs-expected text extraction ratio, calibrated from production medians.
- Shared extraction constants (`_constants.py`) and helpers (`_helpers.py`) — eliminates 5 duplicate definitions across extraction modules.
- Unified `_try_method()` helper consolidates duplicated try/check/write/return patterns across PDF, image, and Office extraction chains.
- `_check_text_quality()` extracts shared U+FFFD and printable-ratio checks used by both `_is_cached_output_readable` and `_is_readable_text`.
- Reference URL downloads parallelized with `ThreadPoolExecutor` (5 concurrent).
- Citation verifier optimized with per-file page split caching and exact substring matching before fuzzy matching.

### Fixed

- Confidence scores calibrated to real-world medians — PDF ratio lowered from 0.5 to 0.09 (was producing 0.01-0.05 scores for well-extracted files).
- Binary PNG/JPEG data no longer passes readability gates (U+FFFD counted as non-printable).
- Identity-H PDF over-classification fixed — 25/26 Identity-H PDFs now extract normally with page markers (was skipping 91% of PDFs to markitdown, losing page markers).
- MuPDF C-level stderr noise suppressed and routed through Python logging.

### Changed

- PDF extraction chain expanded: pymupdf → pdftotext → markitdown → GLM-OCR → pytesseract → Claude vision → direct read.
- Image extraction chain expanded: markitdown → GLM-OCR → pytesseract → Claude vision → diagram placeholder.
- Scanned PDF chain: GLM-OCR → pytesseract → Claude vision → direct read (skips text extractors entirely).

## [0.1.0] - 2026-02-22

### Added

- 102 Pydantic v2 data models covering findings, gaps, manifests, config, inventory, quality scores, and all intermediate pipeline schemas.
- 6-pass cascading entity resolution with rapidfuzz token-sort-ratio matching, abbreviation expansion, cache learning, and configurable thresholds.
- Document extraction pipeline with markitdown, pdftotext fallback chain, checksum-based caching, and optional Tesseract OCR for scanned PDFs.
- 35-step deterministic orchestrator with 5 blocking quality gates, step dependencies, state machine, and checkpoint/resume support.
- 4 specialist agents (Legal, Finance, Commercial, ProductTech) plus optional Judge agent and Reporting Lead, all driven by claude-agent-sdk v0.1.39+.
- Schema-driven 14-sheet Excel report generation via openpyxl, with configurable report_schema.json governing sheet layout, column definitions, and formatting.
- 5-layer numerical audit system: extraction-time validation, cross-document reconciliation, agent-output verification, report-level totals check, and final sign-off gate.
- 30 Definition of Done (DoD) checks enforced as fail-closed quality gates across the pipeline.
- CLI with `run`, `validate`, and `version` commands via Click, with `--dry-run`, `--mode incremental`, and `--verbose` flags.
- Optional ChromaDB vector store integration for cross-document semantic search and retrieval-augmented analysis.
- Incremental execution mode that skips unchanged documents based on file checksums, reducing re-processing time for iterative runs.
- Three-tier persistence layer: run-scoped file storage, cross-run project registry, and optional database-backed metadata store.
- NetworkX-based governance graph construction for entity relationship mapping and contract hierarchy analysis.
- Hook-enforced quality gates via claude-agent-sdk PreToolUse, PostToolUse, and Stop hooks.
- Custom MCP tools (validate_finding, lookup_entity, query_vector_store) for agent-accessible validation and search.
- Deal configuration system with JSON schema validation, template configs, and entity alias management.
- Quickstart example with sample data room, pre-filled deal config, and step-by-step guide.
- Dockerfile with multi-stage build for containerized deployment.
- Comprehensive test infrastructure with pytest, fixtures, and markers for unit, integration, and e2e test tiers.
