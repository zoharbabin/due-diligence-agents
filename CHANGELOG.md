# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.4.0] - 2026-03-03

### Added

- Board-ready executive HTML report (PR #112) — modular `SectionRenderer` architecture with pre-computed metrics.
  - `ExecutiveSummaryRenderer` with Go/No-Go signal, risk heatmap, top 5 deal breakers, key metrics strip, concentration risk (HHI).
  - `DashboardRenderer` with wolf pack dedup: P0-only deal breakers capped at 15, similarity-based grouping via `difflib.SequenceMatcher`.
  - `DiffRenderer` for run-over-run change tracking (new/resolved/changed-severity findings).
  - `StrategyRenderer` for optional buyer-context analysis (conditional on `buyer_strategy` config).
  - Category normalization: longest-match keyword algorithm mapping freeform agent categories to 12 canonical categories per domain.
  - 3-way cross-reference match status (match/mismatch/unverified) replacing binary Yes/No.
  - Gap analysis table expanded to 7 columns (added Why Needed, Request to Company, Agent).
  - Terminology: "Customer" replaced with "Entity" in all reporting outputs.
  - `ReportDataComputer` + `ReportComputedData` Pydantic model for single-pass metric computation.
  - Navigation bar with links to all 10 report sections.
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

- Customer `safe_name` duplication — prompt enforcement + rapidfuzz validation in merge step.
- Entity cache `save()` missing `run_id` argument (step 34 crash).
- Extraction pipeline docstrings clarified as search-only purpose.
- All stale "reporting_lead" references removed from source code, tests, and output files (comments, docstrings, rule text).

## [0.3.1] - 2026-03-02

### Fixed

- Replaced real bank routing/account numbers in sample invoice with zeroed placeholders.
- Replaced `.io` email domain in sample data with `.example.com` per RFC 2606.
- Replaced real company names (Salesforce, Twilio) in test fixtures with fictional names.
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
