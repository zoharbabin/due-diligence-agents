# Implementation Plan — Due Diligence Agent SDK

> Execute ONE phase at a time. Write tests first, then implement. Run quality gates after every module.
> Update status as you complete each item. Do NOT proceed to the next phase until the current phase is fully complete.

**Quality gate command** (run after every module):
```bash
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/ && ruff format --check src/ tests/
```

---

## Phase 1: Foundation
**Goal**: All Pydantic models, entity resolution, extraction pipeline, and utilities — with full test coverage.
**Dependencies**: None (no external deps except pydantic, rapidfuzz, networkx, openpyxl)
**Status**: COMPLETE

### 1.1 Project Setup
**Status**: Complete
- [x] Verify `pyproject.toml` deps install: `pip install -e ".[dev]"`
- [x] Create `src/dd_agents/utils/__init__.py`
- [x] Create package __init__.py files

### 1.2 Utility Modules
**Status**: Complete
- [x] Write `tests/unit/test_naming.py` — 43 parametrized tests
- [x] Implement `src/dd_agents/utils/naming.py` — `customer_safe_name()`, `preprocess_name()`
- [x] Write `tests/unit/test_constants.py` — 10 tests
- [x] Implement `src/dd_agents/utils/constants.py` — tier names, agent names, severity levels, paths

### 1.3 Data Models
**Status**: Complete — 102 model classes across 12 files
- [x] Write `tests/unit/test_models/test_config.py` — 60 tests
- [x] Implement `src/dd_agents/models/config.py` — 19 config models (DealConfig hierarchy)
- [x] Implement `src/dd_agents/models/finding.py` — 13 finding/citation models
- [x] Implement `src/dd_agents/models/inventory.py` — 7 inventory models
- [x] Implement `src/dd_agents/models/manifest.py` — 5 coverage manifest models
- [x] Implement `src/dd_agents/models/governance.py` — 3 governance models with NetworkX
- [x] Implement `src/dd_agents/models/audit.py` — 10 audit/quality models
- [x] Implement `src/dd_agents/models/persistence.py` — 7 run lifecycle models
- [x] Implement `src/dd_agents/models/entity.py` — 9 entity resolution models
- [x] Implement `src/dd_agents/models/numerical.py` — 2 numerical manifest models
- [x] Implement `src/dd_agents/models/reporting.py` — 13 report schema models
- [x] Implement `src/dd_agents/models/enums.py` — 16 StrEnum classes
- [x] Implement `src/dd_agents/models/__init__.py` — re-exports all 102 classes

### 1.4 Entity Resolution
**Status**: Complete — 59 tests
- [x] Implement `src/dd_agents/entity_resolution/matcher.py` — 6-pass cascade
- [x] Implement `src/dd_agents/entity_resolution/cache.py` — per-entry invalidation
- [x] Implement `src/dd_agents/entity_resolution/logging.py` — MatchLogger
- [x] Implement `src/dd_agents/entity_resolution/safe_name.py` — re-exports
- [x] Write `tests/unit/test_entity_resolution.py` — 59 tests across 12 test classes

### 1.5 Extraction Pipeline
**Status**: Complete — 115 tests (originally 40, expanded in Issues #27, #28, #30)
- [x] Implement `src/dd_agents/extraction/cache.py` — SHA-256 checksum cache
- [x] Implement `src/dd_agents/extraction/quality.py` — ExtractionQualityTracker
- [x] Implement `src/dd_agents/extraction/markitdown.py` — MarkitdownExtractor
- [x] Implement `src/dd_agents/extraction/ocr.py` — OCRExtractor
- [x] Implement `src/dd_agents/extraction/pipeline.py` — ExtractionPipeline with fallback chain
- [x] Implement `src/dd_agents/extraction/glm_ocr.py` — GLM-OCR vision-language model extractor
- [x] Implement `src/dd_agents/extraction/_constants.py` — Shared extension sets and confidence constants
- [x] Implement `src/dd_agents/extraction/_helpers.py` — Shared `read_text()` helper
- [x] Write `tests/unit/test_extraction.py` — 115 tests (pre-inspection, quality gates, Claude vision, shared constants)
- [x] Write `tests/unit/test_glm_ocr.py` — 24 tests

### 1.6 Config & CLI
**Status**: Complete — 28 tests
- [x] Implement `src/dd_agents/config.py` — load/validate with error hierarchy
- [x] Implement `src/dd_agents/cli.py` — Click CLI with run/validate/version
- [x] Write `tests/unit/test_config_loader.py` — 28 tests

### Phase 1 Acceptance
- [x] `pytest tests/unit/ -x -q` — ALL unit tests pass
- [x] `mypy src/ --strict` — no type errors
- [x] `ruff check src/ tests/` — clean

---

## Phase 2: Infrastructure
**Goal**: Persistence layer, inventory building, SDK hooks, MCP tools, pipeline state.
**Dependencies**: Phase 1 complete
**Status**: COMPLETE

### 2.1 Persistence
**Status**: Complete — 27 tests
- [x] Implement `src/dd_agents/persistence/tiers.py` — PERMANENT, VERSIONED, FRESH management
- [x] Implement `src/dd_agents/persistence/run_manager.py` — run init, finalize, history
- [x] Implement `src/dd_agents/persistence/incremental.py` — customer classification
- [x] Write `tests/unit/test_persistence.py` — 27 tests

### 2.2 Inventory
**Status**: Complete — 38 tests
- [x] Implement `src/dd_agents/inventory/discovery.py` — tree.txt, files.txt
- [x] Implement `src/dd_agents/inventory/customers.py` — customers.csv, counts.json
- [x] Implement `src/dd_agents/inventory/reference_files.py` — reference_files.json
- [x] Implement `src/dd_agents/inventory/mentions.py` — customer_mentions.json
- [x] Implement `src/dd_agents/inventory/integrity.py` — InventoryIntegrityVerifier
- [x] Write `tests/unit/test_inventory.py` — 38 tests

### 2.3 Hooks
**Status**: Complete — 42 tests
- [x] Implement `src/dd_agents/hooks/pre_tool.py` — path_guard, bash_guard, file_size_guard
- [x] Implement `src/dd_agents/hooks/post_tool.py` — validate JSON outputs
- [x] Implement `src/dd_agents/hooks/stop.py` — coverage/manifest/audit checks
- [x] Write `tests/unit/test_hooks.py` — 42 tests

### 2.4 MCP Tools
**Status**: Complete — 39 tests
- [x] Implement `src/dd_agents/tools/server.py` — tool definitions + per-agent routing
- [x] Implement 7 tool files: validate_finding, validate_gap, validate_manifest, verify_citation, get_customer_files, resolve_entity, report_progress
- [x] Write `tests/unit/test_tools.py` — 39 tests

### Phase 2 Acceptance
- [x] `pytest tests/unit/ -x -q` — ALL tests pass
- [x] `mypy src/ --strict` — no type errors
- [x] `ruff check src/ tests/` — clean

---

## Phase 3: Pipeline Engine
**Goal**: 35-step state machine, agent lifecycle management, checkpoints, error taxonomy.
**Dependencies**: Phase 2 complete
**Status**: COMPLETE

### 3.1 Pipeline Engine + Steps
**Status**: Complete — 35 tests
- [x] Implement `src/dd_agents/orchestrator/steps.py` — PipelineStep enum (35 steps)
- [x] Implement `src/dd_agents/orchestrator/state.py` — PipelineState + StepResult
- [x] Implement `src/dd_agents/orchestrator/checkpoints.py` — atomic save/restore
- [x] Implement `src/dd_agents/orchestrator/team.py` — AgentTeam management
- [x] Implement `src/dd_agents/orchestrator/engine.py` — PipelineEngine (35 steps wired)
- [x] Write `tests/unit/test_orchestrator.py` — 35 tests

### Phase 3 Acceptance
- [x] All 35 steps registered and callable in engine
- [x] Checkpoint save/restore works
- [x] Full quality gates pass

---

## Phase 4: Agent Implementation
**Goal**: Prompt assembly, specialist spawning, Judge iteration. (Reporting Lead removed in v0.4.0 — replaced by deterministic pre-merge validation.)
**Dependencies**: Phase 3 complete
**Status**: COMPLETE

### 4.1 Agents
**Status**: Complete — 77 tests
- [x] Implement `src/dd_agents/agents/base.py` — BaseAgentRunner abstract class
- [x] Implement `src/dd_agents/agents/prompt_builder.py` — prompt assembly + batching
- [x] Implement `src/dd_agents/agents/specialists.py` — Legal, Finance, Commercial, ProductTech
- [x] Implement `src/dd_agents/agents/judge.py` — JudgeAgent with scoring + iteration
- [x] Implement `src/dd_agents/agents/reporting_lead.py` — ReportingLeadAgent
- [x] Write `tests/unit/test_agents.py` — 77 tests

### Phase 4 Acceptance
- [x] Prompts include all required sections per spec
- [x] 4 specialists spawn with proper config
- [x] Judge produces quality scores with iteration
- [x] Full quality gates pass

---

## Phase 5: Reporting + Validation
**Goal**: Merge/dedup, report diff, Excel generation, numerical audit, QA audit, DoD checks.
**Dependencies**: Phase 4 complete
**Status**: COMPLETE

### 5.1 Reporting
**Status**: Complete — 34 tests (core) + 1933 total with HTML renderers
- [x] Implement `src/dd_agents/reporting/merge.py` — FindingMerger with dedup
- [x] Implement `src/dd_agents/reporting/diff.py` — ReportDiffBuilder
- [x] Implement `src/dd_agents/reporting/excel.py` — schema-driven 14-sheet generator
- [x] Implement `src/dd_agents/reporting/contract_dates.py` — ContractDateReconciler
- [x] Write `tests/unit/test_reporting.py` — 34 tests
- [x] Implement `src/dd_agents/reporting/computed_metrics.py` — ReportDataComputer + ReportComputedData
- [x] Implement `src/dd_agents/reporting/html_base.py` — SectionRenderer ABC, CSS, JS, shared helpers
- [x] Implement `src/dd_agents/reporting/html.py` — HTMLReportGenerator orchestrator
- [x] Implement `src/dd_agents/reporting/html_executive.py` — ExecutiveSummaryRenderer (Go/No-Go, heatmap, deal breakers)
- [x] Implement `src/dd_agents/reporting/html_dashboard.py` — DashboardRenderer with wolf pack dedup
- [x] Implement `src/dd_agents/reporting/html_risk.py` — RiskRenderer (heat map, concentration)
- [x] Implement `src/dd_agents/reporting/html_domains.py` — DomainRenderer (per-domain deep-dive)
- [x] Implement `src/dd_agents/reporting/html_cross.py` — CrossRefRenderer (3-way match status)
- [x] Implement `src/dd_agents/reporting/html_customers.py` — CustomerRenderer (entity profiles)
- [x] Implement `src/dd_agents/reporting/html_gaps.py` — GapRenderer (7-column table)
- [x] Implement `src/dd_agents/reporting/html_quality.py` — QualityRenderer (governance + audit checks)
- [x] Implement `src/dd_agents/reporting/html_strategy.py` — StrategyRenderer (buyer context, conditional)
- [x] Implement `src/dd_agents/reporting/html_diff.py` — DiffRenderer (run-over-run changes)
- [x] Write `tests/unit/test_html_report.py`, `test_html_renderers.py`, `test_report_rendering.py`

### 5.2 Validation
**Status**: Complete — 33 tests
- [x] Implement `src/dd_agents/validation/coverage.py` — CoverageValidator
- [x] Implement `src/dd_agents/validation/numerical_audit.py` — 6-layer NumericalAuditor (Layer 6: financial citation verification)
- [x] Implement `src/dd_agents/validation/qa_audit.py` — 17-check QAAuditor
- [x] Implement `src/dd_agents/validation/dod.py` — 30-check DefinitionOfDoneChecker
- [x] Implement `src/dd_agents/validation/schema_validator.py` — SchemaValidator
- [x] Write `tests/unit/test_validation.py` — 33 tests

### Phase 5 Acceptance
- [x] Merge correctly combines findings from 4 agents
- [x] 6 numerical audit layers validate correctly (including Layer 6: financial citation verification)
- [x] All 31 DoD checks implemented (30 original + 12b agent coverage)
- [x] 14-sheet Excel matches report_schema.json
- [x] HTML executive report with Go/No-Go signal, risk heatmap, top deal breakers
- [x] Category normalization with longest-match algorithm (12 canonical categories per domain)
- [x] Wolf pack dedup: P0-only deal breakers with similarity-based grouping
- [x] 3-way cross-reference match status (match/mismatch/unverified)
- [x] Run-over-run diff renderer (new/resolved/changed findings)
- [x] Full quality gates pass

---

## Phase 6: Integration
**Goal**: CLI interface, optional ChromaDB, E2E testing, quality hardening.
**Dependencies**: Phase 5 complete
**Status**: COMPLETE

### 6.1 CLI Enhancements
**Status**: Complete
- [x] Add `--resume-from` and `--dry-run` options
- [x] Wire pipeline to `asyncio.run()` for execution
- [x] Rich output panels for errors, completion, interrupts

### 6.2 Vector Store (Optional)
**Status**: Complete
- [x] Implement `src/dd_agents/vector_store/store.py` — ChromaDB wrapper
- [x] Implement `src/dd_agents/vector_store/embeddings.py` — DocumentChunker
- [x] Implement `src/dd_agents/vector_store/__init__.py` — conditional import with stub

### 6.3 Integration Tests
**Status**: Complete — 17 tests
- [x] Write `tests/integration/test_pipeline_integration.py` — 17 tests with sample data room

### 6.4 E2E Tests
**Status**: Complete — 6 pass + 3 API-dependent (skipped without API key)
- [x] Write `tests/e2e/conftest.py` — fixtures with sample data room
- [x] Write `tests/e2e/test_full_run.py` — pre-agent + full pipeline + incremental

### 6.5 Quality Hardening
**Status**: Complete
- [x] `mypy src/ --strict` — 0 errors in 93 files
- [x] `ruff check src/ tests/` — all checks passed
- [x] `ruff format --check src/ tests/` — all files formatted
- [x] All 188 mypy strict errors fixed across 25 files

### Phase 6 Acceptance
- [x] All CLI commands work: run, validate, version with --resume-from, --dry-run
- [x] Vector store gracefully degrades without ChromaDB
- [x] Full E2E test passes (pre-agent steps)
- [x] ALL quality gates pass

---

## Completion Criteria

The project is complete when ALL of the following are true:
- [x] All 6 phases have status "Complete"
- [x] `pytest tests/ -x` passes — 1987 unit tests, 17 integration, 9 E2E (3 skipped without API key)
- [x] `mypy src/ --strict` passes — 0 errors across 116 source files
- [x] `ruff check src/ tests/` is clean
- [x] `ruff format --check src/ tests/` is clean

> **Status: COMPLETE** — All 6 phases implemented and verified. Production hardening (v0.3.0) added 253 additional unit tests. v0.3.1 adds security, documentation, and config cleanup. v0.4.0 adds board-ready executive HTML report (Issue #113), sidebar navigation, CSS variables, business analysis renderers (CoC, privacy, health tiers, recommendations, methodology), alert boxes, RAG indicators, and expanded category normalization. See `PRODUCTION_HARDENING_PLAN.md` for post-implementation hardening work.

## Test Summary

| Category | Count |
|----------|-------|
| Unit tests (models, utils, entity resolution, extraction, config, hooks, tools, orchestrator, agents, reporting, validation, search, glm_ocr, type safety, visual grounding, entity dedup, OCR registry, layout PDF, HTML report, HTML renderers, report rendering, extraction backend, turn limits) | 1987 |
| Integration tests (pipeline steps 1-11) | 17 |
| E2E tests (pre-agent: config, tiers, discovery, registry, run manager, cache) | 6 |
| E2E tests (API-dependent: dry run, full pipeline, incremental — skipped without key) | 3 |
| **Total** | **1987 passed, 3 skipped** |

## Git History

```
Phase 1.2-1.3: Implement utility modules and all 102 data models
Phase 1.4: Implement 6-pass entity resolution with cache
Phase 1.5-1.6: Implement extraction pipeline, config loader, and CLI
Phase 2: Implement persistence, inventory, hooks, and MCP tools
Phase 3-4: Implement orchestrator pipeline engine and agent module
Phase 5: Implement reporting and validation modules
Phase 6: Vector store, pipeline wiring, integration tests, CLI
Quality hardening: mypy strict, ruff format, E2E tests
Issue #25: GLM-OCR vision-language model extractor
Issue #27: Extraction pipeline optimization + Claude vision fallback
Issue #4: Structured LLM output + 18 bug fixes from codebase-wide review
```
