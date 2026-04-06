# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

> **Note**: Versions 0.1.0 through 0.3.1 below are internal development milestones.
> The first public release was **v0.4.0** (2026-03-30). Tagged releases on PyPI and
> GitHub begin at **v0.4.1**.

## [0.5.0] - 2026-04-05

### Added

- **Knowledge Compounding Architecture** (Epic #186) — Karpathy LLM Wiki pattern applied to M&A due diligence. Every pipeline run, search, and query now enriches a persistent Deal Knowledge Base. Subsequent interactions start from a richer baseline.
- **Deal Knowledge Base** (#178) — PERMANENT-tier knowledge layer with article CRUD, atomic writes, batch write context manager, and auto-maintained JSON index. 5 article types: entity profiles, clause summaries, contradictions, insights, annotations.
- **Unified Knowledge Graph** (#179) — NetworkX-based cross-document relationship intelligence with 11 typed edge types, cycle detection, path queries, contradiction detection, and merge from existing governance/ontology graphs.
- **Analysis Chronicle** (#180) — Append-only JSONL interaction timeline with 5 interaction types, filtering by type/entity, timeline summary generation, and statistics.
- **Knowledge-Enriched Search** (#181) — Search prompts enriched with entity profiles, prior findings, contradictions, and graph context from the Knowledge Base.
- **Knowledge Compounding / File-back** (#182) — Pipeline findings compiled into entity profiles and clause summaries. Search results, query answers, and user annotations filed back as knowledge articles.
- **Finding Lineage Tracking** (#183) — SHA-256 fingerprinting for stable finding identity across runs. 5-state status tracking (active, resolved, recurring, escalated, de-escalated) with severity evolution history.
- **Agent Context Enrichment** (#184) — Agent prompts enriched with accumulated entity profiles, finding lineage, contradictions, graph context, and chronicle history. Domain-filtered for each specialist.
- **Knowledge Health Checks** (#185) — 7-category automated integrity validation (broken links, orphans, missing coverage, citation drift, graph integrity, lineage gaps, staleness) with auto-fix for broken links and orphans.
- 4 new CLI commands: `log` (chronicle viewer), `annotate` (user annotations), `lineage` (finding evolution), `health` (KB integrity checks with `--auto-fix`).
- `--no-knowledge` flag on `run` command to skip knowledge compilation.
- `--no-file` flag on `search` command to skip filing results back to KB.
- Knowledge compilation wired into pipeline step 32 (finalize_metadata) — best-effort, never blocks pipeline.
- New `src/dd_agents/knowledge/` package with 11 modules and 30+ public API exports.
- 234 new unit tests for knowledge package (total: 3,240 unit tests).
- **Homebrew formula** (#177) — `brew install zoharbabin/due-diligence-agents/dd-agents`. Formula auto-updated on each release via CI.
- Release workflow updated with `update-formula` job for automatic Homebrew version bumps.

## [0.4.3] - 2026-04-04

### Fixed

- **MCP server rewrite** (Issue #171, C1) — rewrote `tools/mcp_server.py` with `@tool` decorator wrappers for all 9 tools, replacing removed SDK API calls.
- **Hook factory SDK migration** (Issue #171, C2) — migrated to `HookMatcher` objects in `hooks/factory.py`.
- **Agent runtime context** (Issue #171, C3) — `_spawn_agent()` now passes `project_dir`/`run_dir` via closure binding.
- **`build_mcp_server` export** (Issue #171, C4) — added to `tools/__init__.py` exports.
- **SDK mock fixtures** (Issue #171, C5) — updated to current SDK API; shared `SdkMocks` fixture in `tests/conftest.py`.
- **~493 Pydantic fields missing descriptions** (Issue #171, H1) — all model fields now have `Field(description=...)`.
- **Judge/Executive Synthesis schema drift** (Issue #171, H2-H3) — schemas aligned with current models.

### Added

- 13 tests for `orchestrator/team.py`, 8 for `search/runner.py`, 25 for `vector_store/` (Issue #171, T1-T3).
- Shared data-room fixture `tests/fixtures/sample_data_room/` with 4 contract files (Issue #171, T4).
- Two-tier validation design documented in `dod.py` and engine step docstrings (Issue #171, H4).
- `PRE_MERGE_VALIDATION` backward-compatible StrEnum alias in `steps.py` (Issue #171, M5/M7).
- Co-located BaseModel subclasses documented in CLAUDE.md (Issue #171, M3).
- `03-project-structure.md` rewritten to reflect current 168-file inventory (Issue #171, H5/M9).

## [0.4.2] - 2026-04-04

### Fixed

- **Issue #171 audit fixes (batch 1)** — SDK wiring, hook factory, agent spawning, and standards compliance (PR #172).

### Added

- CI/CD and distribution documentation in CLAUDE.md (release process, PyPI OIDC, Docker GHCR, GitHub Releases).

## [0.4.1] - 2026-04-04

First published release on PyPI and GitHub Container Registry.

### Added

- GitHub Actions CI workflow (lint, types, unit tests on Python 3.12+3.13 matrix, integration tests, build, E2E).
- GitHub Actions release workflow (PyPI via OIDC, Docker to GHCR, GitHub Release with artifacts).
- `workflow_dispatch` trigger for manual release fallback.

### Changed

- Positioning refined: tool augments advisors, not replaces them.
- Documentation overhauled for non-technical M&A audience.

## [0.4.0] - 2026-03-30

Initial public release containing the complete Due Diligence Agent SDK.

### Core Platform

- **35-step deterministic orchestrator** with 5 blocking quality gates, step dependencies, state machine, and checkpoint/resume support.
- **8 AI agents**: 4 specialists (Legal, Finance, Commercial, ProductTech) + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence — all driven by `claude-agent-sdk` v0.1.39+.
- **102 Pydantic v2 data models** covering findings, gaps, manifests, config, inventory, quality scores, and all intermediate pipeline schemas.
- **CLI** with 15 commands: `run`, `validate`, `version`, `init`, `auto-config`, `search`, `assess`, `export-pdf`, `query`, `portfolio` (group), `templates` (group), `log`, `annotate`, `lineage`, `health`.

### Document Processing

- **Document extraction pipeline** with markitdown, pdftotext fallback chain, checksum-based caching, and optional OCR.
- **PDF pre-inspection** classifies PDFs before extraction — routes scanned/garbled PDFs directly to OCR.
- **GLM-OCR** vision-language model as preferred OCR method (mlx-vlm on Apple Silicon, Ollama cross-platform).
- **Claude vision** as last-resort fallback for files that all OCR methods fail on.
- **Layout-aware PDF extraction** preserving table structure and spatial relationships.
- **Pluggable OCR registry** and **document extraction backend** replacing hardcoded dependencies.
- **`read_office` MCP tool** — reads binary Office files (.xlsx, .xls, .docx, .doc, .pptx, .ppt) and returns structured text.

### Analysis & Intelligence

- **Document Precedence Engine** — 5-layer scoring system: folder priority (4-tier), version chain detection, weighted composite score (version 40%, folder 30%, recency 30%).
- **Revenue-at-Risk & Financial Impact Quantification** — per-customer revenue extraction, revenue-at-risk waterfall, customer concentration treemap, financial impact metrics.
- **Red Flag Detection & Quick Scan Mode** — `--quick-scan` CLI flag for rapid red flag assessment across 8 deal-killer categories.
- **Executive synthesis agent** — senior M&A partner review producing calibrated Go/No-Go signal, executive narrative, severity overrides, and ranked deal breakers.
- **Agent Cost Optimization** — 3 preset model profiles (economy/standard/premium), per-agent cost tracking, budget management. Engine-level integration deferred pending SDK token-reporting support.
- **Parallel Agent Execution Optimization** — customer complexity scoring, priority queue scheduling, token-aware batch splitting. Engine step 16 integration deferred (current batching is functional).
- **P0/P1 follow-up verification loop** — mandatory self-verification protocol for critical findings with research-proven 9.2% accuracy improvement.
- **Deterministic finding verification** in pre-merge validation (step 23) — P0 findings without citations auto-downgraded.
- **Data room health check** (`dd-agents assess`) — pre-flight quality assessment with completeness score.
- **Severity rubric** in specialist prompts — deal-type-aware P0-P3 calibration.

### Reporting

- **Interactive HTML executive report** — complete redesign with sidebar navigation, scroll tracking, RAG status indicators.
- **Executive summary** with Go/No-Go signal, risk heatmap, top 5 deal breakers, key metrics strip, HHI concentration risk.
- **Customer-level P0/P1 tables** — entity-level severity tables with alert boxes and top-10 + collapsed rest pattern.
- **Change of Control analysis** — CoC findings by entity with consent-required counts and severity matrix.
- **Data Privacy analysis** — GDPR/CCPA/DPA findings by entity.
- **Entity Health Tiers** — Tier 1 (Critical), Tier 2 (High), Tier 3 (Standard) classification.
- **Recommendations engine** — deterministic generation of 4-7 prioritized action items.
- **Methodology & Limitations** section with process description, agent coverage, data quality metrics.
- **Run-over-run diff tracking** for change analysis between pipeline runs.
- **Optional buyer-context strategy analysis** (conditional on `buyer_strategy` config).
- **Schema-driven 14-sheet Excel report** via openpyxl with configurable report_schema.json.
- **Optional PDF export** via Playwright or WeasyPrint.
- **Data quality finding separation** — three-way classification (material / data-quality / noise) with dedicated appendix.
- Category normalization: longest-match keyword algorithm mapping to 12 canonical categories per domain.

### Infrastructure

- **6-pass cascading entity resolution** with rapidfuzz token-sort-ratio matching, abbreviation expansion, cache learning.
- **Entity deduplication** for post-resolution duplicate detection.
- **Pre-merge validation and cross-agent anomaly detection** (step 23) — deterministic Python replacing the former Reporting Lead agent.
- **5-layer numerical audit system** and **30 Definition of Done checks** as fail-closed quality gates.
- **Three-tier persistence layer**: run-scoped file storage, cross-run project registry, optional database metadata.
- **NetworkX governance graph** for entity relationship mapping and contract hierarchy analysis.
- **Ontology and reasoning module** with contract ontology, risk scoring, and graph-based reasoning.
- **Optional ChromaDB vector store** for cross-document semantic search.
- **Contract search** (`dd-agents search`) with 4-phase analysis, citation verification, and Excel report output.
- **Auto-config** (`dd-agents auto-config`) for AI-driven deal configuration generation.
- **Hook-enforced quality gates** via claude-agent-sdk PreToolUse, PostToolUse, and Stop hooks.
- **Custom MCP tools** (validate_finding, lookup_entity, query_vector_store) for agent-accessible validation.
- **Structured LLM output** across all agent `query()` calls via Pydantic-validated JSON schemas.
- **Client-side turn enforcement** — soft limit at `max_turns`, hard kill at `3x max_turns`.
- **Incremental execution mode** that skips unchanged documents based on file checksums.
- **Dockerfile** with multi-stage build for containerized deployment.

---

*The following entries document internal development milestones prior to the initial public release.*

## [0.3.1] - 2026-03-02 (pre-release)

### Fixed

- Replaced real bank routing/account numbers in sample invoice with zeroed placeholders.
- Replaced `.io` email domain in sample data with `.example.com` per RFC 2606.
- Replaced real company names in test fixtures with fictional names.
- Removed phantom `reasoning/*` module reference from CLAUDE.md spec table.

### Changed

- Added `authors`, `keywords`, `classifiers`, and `[project.urls]` metadata to `pyproject.toml`.
- Added `data_room` section to `config/deal-config.template.json`.

## [0.3.0] - 2026-02-28 (pre-release)

### Added

- Entity deduplication module (`entity_resolution/dedup.py`).
- Pluggable OCR registry (`extraction/ocr_registry.py`).
- Pluggable document extraction backend (`extraction/backend.py`).
- Layout-aware PDF extraction (`extraction/layout_pdf.py`).
- Visual grounding with bounding-box coordinate support (`extraction/coordinates.py`).
- Interactive HTML review report generation (`reporting/html.py`).
- 253 new unit tests covering entity dedup, extraction backends, layout PDF, OCR registry, HTML reports.

### Fixed

- Citation path resolution validates against file inventory instead of filesystem.
- Gap type normalization uses keyword-stem logic instead of exact string matching.
- Cross-reference fields accept both `dict` and `str` types.
- Numerical audit rederivation formulas match manifest field names.
- Search analyzer answer merging: YES-prefixed free text correctly beats NO in priority.

## [0.2.1] - 2026-02-25 (pre-release)

### Added

- Structured LLM output across all agent `query()` calls.
- Ontology and reasoning module (`reasoning/`).
- Vector store embeddings module (`vector_store/embeddings.py`).
- Contract search command (`dd-agents search`).
- Auto-config command (`dd-agents auto-config`).

### Fixed

- Engine staleness threshold config key.
- Entity resolution empty-string preprocessing collision.
- 18 additional bug fixes from comprehensive codebase-wide review (PR #30).

## [0.2.0] - 2026-02-24 (pre-release)

### Added

- PDF pre-inspection, GLM-OCR, Claude vision fallback.
- Control-character corruption detection and watermark detection.
- Confidence scaling calibrated from production medians.
- Reference URL downloads parallelized with `ThreadPoolExecutor`.

### Fixed

- Confidence scores calibrated to real-world medians.
- Binary PNG/JPEG data no longer passes readability gates.
- Identity-H PDF over-classification fixed.

## [0.1.0] - 2026-02-22 (pre-release)

### Added

- 102 Pydantic v2 data models.
- 6-pass cascading entity resolution.
- Document extraction pipeline.
- 35-step deterministic orchestrator with 5 blocking quality gates.
- 4 specialist agents + Judge + Reporting Lead.
- Schema-driven 14-sheet Excel report.
- 5-layer numerical audit system and 30 DoD checks.
- CLI with `run`, `validate`, and `version` commands.
- Optional ChromaDB vector store integration.
- Three-tier persistence layer.
- Hook-enforced quality gates.
- Custom MCP tools.
- Deal configuration system with JSON schema validation.
- Quickstart example with sample data room.
- Dockerfile with multi-stage build.
