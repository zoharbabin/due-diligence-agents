# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

> **Note**: Versions 0.1.0 through 0.3.1 below are internal development milestones.
> The first public release was **v0.4.0** (2026-03-30). Tagged releases on PyPI and
> GitHub begin at **v0.4.1**.

## [1.5.0] — 2026-04-29

### Added

- **Neurosymbolic Cross-Domain Analysis** (Issue #189) — Symbolic trigger rules detect when findings in one domain require verification by another (e.g., Finance revenue recognition -> Legal contract enforceability). 7 built-in rules, budget-bounded, priority-ordered. 3 new pipeline steps (18-20): cross_domain_analysis, targeted_respawn, targeted_merge.
- **Domain Ontology** — 13-edge dependency graph across 9 specialist domains. Powers trigger rules and enriches chat system prompt with cross-domain context.
- **Cross-Domain Config** — `forensic_dd.cross_domain` in deal-config.json: enable/disable, budget cap, severity filter, rule disable list.
- **Agent Registry** — `AgentRegistry` singleton and `AgentDescriptor` metadata enable extensible agent architecture. Built-in agents self-register; external agents via entry-points.
- **CLI Demo Video** — Terminal recording showcasing real M&A analysis: data room scan, pipeline preview, natural-language queries with citation-backed answers.
- **Eval Framework Extension** — 6 cross-domain ground truth contracts with expected findings for Finance, Legal, and Commercial. 57 deterministic trigger rule tests. 15 E2E cross-domain tests.

### Improved

- **Query command Markdown rendering** — `dd-agents query` output now renders Markdown (tables, headers, bullets, bold) via Rich instead of raw text.
- **Chat cross-domain context** — System prompt includes dependency descriptions when multiple domain agents are active, enabling cross-domain synthesis in answers.

## [1.4.0] — 2026-04-28

### Added

- **Extensible Agent Architecture** (Issue #188) — AgentRegistry singleton with descriptor-based metadata enables dynamic agent resolution throughout the pipeline. Built-in agents self-register at import; external agents register via `dd_agents.specialists` entry-points.
- **5 new specialist agents** — Cybersecurity, HR, Tax, Regulatory, and ESG join the existing Legal, Finance, Commercial, and ProductTech specialists (9 total). Each has domain-specific prompts, keyword sets, and extraction instructions.
- **Config-driven agent customization** — Disable agents per-deal via `deal-config.json` `forensic_dd.specialists.disabled`. Pipeline, validation, merge, and reporting all resolve active agents dynamically.
- **Eval ground truth for all 9 agents** — Contracts and expected findings for Cybersecurity, HR, Tax, Regulatory, and ESG added to `tests/evals/ground_truth/`. 15 new CATEGORY_SYNONYMS entries for eval matching.

### Improved

- **Documentation audit** — Comprehensive review and update across 21 files. All agent counts, domain references, CLI signatures, and test counts updated. Historical spec docs marked with disclaimer banners. Stale content removed.

### Fixed

- **Integration test agent naming** — `test_external_agent_can_be_disabled` no longer collides with built-in ESG agent.

## [1.3.4] — 2026-04-27

### Added

- **Chat: extract_document tool** — Chat agent can now index new or updated files on the fly. When `search_in_file` or `get_page_content` can't find a document, the agent calls `extract_document` to run the extraction pipeline and add it to the search index. Supports all formats (PDF, docx, xlsx, images, etc.) with 100 MB size limit and path containment security.
- **Chat: system prompt rule for unindexed files** — New rule 9 instructs the model to use `extract_document` when encountering files added after the pipeline run completed, then retry the search.

### Fixed

- **Chat: document tools blocked by path guard** — `read_office`, `extract_document`, `verify_citation`, and other tools that read original data room files were silently returning empty results because `allowed_dir` was set to `_dd/forensic-dd/` instead of the project root. All document reads outside `_dd/` were blocked as "path traversal". Fixed by setting `allowed_dir` to the project directory (data room root).
- **Chat: extract_document output not findable by search tools** — Extracted text files were named using the absolute path, but `search_in_file` looked them up using relative paths. Now writes copies under all plausible path variants (absolute, relative, ./relative) so any lookup succeeds.
- **Chat: extract_document not registered when text_dir missing** — The tool silently failed to register when no prior pipeline run had created the text index directory. Now falls back to the standard `_dd/forensic-dd/index/text/` path and creates it on first use.

## [1.3.3] — 2026-04-16

### Fixed

- **Chat: memory leak — unbounded process accumulation** — SDK subprocesses (claude CLI + Bun.js workers) now killed between every query, not just at session exit. Grandchild processes killed bottom-up to prevent orphan reparenting.
- **Chat: memory leak — unbounded buffer allocation** — `_compute_buffer_size()` capped at 25 MB (was unbounded — large document corpuses could request multi-GB buffers). Applied to both chat engine and pipeline agent runner.
- **Chat: memory leak — intermediate text accumulation** — Intermediate reasoning text during long tool-use chains (50+ turns) capped at 500 KB. Final answer text (returned to user) remains uncapped.
- **Chat: memory leak — stderr capture growth** — SDK stderr handler now caps at 200 lines per query instead of growing without limit.
- **Chat: memory leak — delayed history truncation** — Conversation history now truncated eagerly after each response instead of waiting until the next query.
- **Chat: fd leak on stderr redirect failure** — File descriptor cleanup in `_run_chat_query` now wrapped in try/finally with null-safe guards.
- **Chat: Esc cancel leaves zombie processes** — Pressing Esc now kills the orphaned SDK subprocess before returning, instead of leaving it running.
- **Chat: thread timeout leaves zombie processes** — Query thread timeout (60s) now kills the SDK subprocess so the daemon thread can exit.

## [1.3.1] — 2026-04-14

### Improved

- **Chat: multiline input** — Shift+Enter inserts a newline for composing multi-line messages (iTerm2 key binding: Shift+Return → Send "\n"). Option+Enter works as a fallback in any terminal.
- **Chat: Esc to cancel** — Press Esc during thinking to cancel the active query and preserve your message for editing.
- **Chat: word wrap fix** — Markdown output no longer hard-wraps mid-word at the terminal edge. Rich renders with a 2-char margin to prevent Unicode width miscalculation overflow.
- **Chat: prompt_toolkit input** — Replaced `readline` with `prompt_toolkit` for the input prompt, enabling proper multiline editing, prompt continuation markers, and robust key binding.

## [1.3.0] — 2026-04-14

### Added

- **Finding Corrections** — Chat mode can now flag incorrect pipeline findings. When the model discovers a hallucinated or mis-severity finding, it uses the `flag_finding` tool to record a correction. Corrections persist across sessions and are applied during the next pipeline run's merge step.
- **Correction MCP Tools** — Two new chat tools: `flag_finding` (fuzzy-match a finding by title, dismiss/downgrade/upgrade/adjust with justification) and `list_corrections` (view all active corrections, filterable by subject).
- **Pipeline Integration** — `FindingMerger.apply_corrections()` loads corrections from JSONL and applies them non-destructively during step 24 (merge/dedup). Original severity preserved in metadata for audit trail.
- **Corrections in System Prompt** — Active corrections shown in chat context as `[DISMISSED]` or `[P1->P2]` annotations, so future sessions see prior corrections immediately.

## [1.2.1] — 2026-04-14

### Fixed

- **Chat: intermediate reasoning leaked to output** — Tool-use "thinking" text (e.g. "Let me search...") no longer appears in the response. Only the final answer is rendered as markdown.
- **Chat: no spinner during tool use** — Spinner now stays visible with descriptive status labels ("Verifying citation...", "Reading document...") while the agent works, instead of disappearing immediately.
- **Chat: arrow keys not working in prompt** — Switched to readline-backed input, enabling arrow key navigation, backspace, and line editing.
- **Chat: SDK crash kills session** — Engine now catches SDK failures gracefully, returns a clean error message, and keeps the session alive for the next question.
- **Chat: noisy error output** — Raw SDK subprocess errors ("exit code 1", "Fatal error in message reader") collapsed into a friendly one-line message with `--verbose` hint.

## [1.2.0] — 2026-04-14

### Added

- **Chat Mode** (`dd-agents chat`) — Interactive multi-turn conversation over DD findings. Ask questions, drill into source documents, verify citations — all in one session.
- **Persistent Chat Memory** — The model saves key insights during conversation and recalls them in future sessions. Memory stored in append-only JSONL, searched via rapidfuzz keyword matching.
- **MCP Memory Tools** — Two new tools (`save_memory`, `search_chat_memory`) available to the model during chat for cross-session context.
- **Session Transcripts** — Full conversation transcripts saved automatically on session exit, with session index for browsing history.
- **Streaming Output with Spinner** — Animated "Thinking..." indicator while waiting for the agent, replaced by streamed text as it arrives.
- **Budget Tracking** — Per-turn and per-session cost limits (`--max-cost`) with automatic exhaustion detection.
- **CHAT Interaction Type** — Chat turns logged to the Analysis Chronicle for the deal timeline.

## [1.1.1] — 2026-04-13

### Fixed

- **mypy CI failure** — Added `type: ignore[import-not-found]` for optional dependencies (playwright, weasyprint, chromadb) that caused strict type checking to fail in CI.

## [1.1.0] — 2026-04-13

### Added

- **Finding Schema Guard** — PreToolUse hook validates finding JSON structure on Write, blocking wrong field names before they reach disk.
- **Citation Enforcement** — Agents required to provide exact citations; validation rejects findings without source references.
- **Agent Hardening** — Improved prompt robustness and output parsing across all agents.
- **New MCP Tools** — Additional document analysis tools for agent use.

## [1.0.2] — 2026-04-10

### Fixed

- **Resume from step 6+ finds 0 subjects** — `_discovered_files` was not persisted in checkpoints. Steps 6-9 and precedence depend on it but got an empty list after resume. Now serialized/restored alongside `_subject_entries`.
- **Judge spot-check validation errors** — `SpotCheckResult` enum expected uppercase `PASS`/`PARTIAL`/`FAIL` but the prompt instructs the agent to write lowercase. Changed enum values to lowercase to match prompt and agent output.
- **Judge score parsing fails on deeply nested JSON** — Strategy 3 (brace matching) used a regex limited to 2 nesting levels, failing on the judge's multi-level `agent_scores` structure. Replaced with `json.JSONDecoder.raw_decode()` which handles arbitrary nesting depth.

## [1.0.1] — 2026-04-10

### Fixed

- **Pipeline crash at step 28 (QA audit)** — `'int' object is not iterable` when agent writes `files_read` as integer count instead of list in coverage manifest. Added type guards in `qa_audit.py` and `dod.py`.
- **DoD check [2] false failure** — file coverage check now defers gracefully when manifests lack file-level data (only subject-level summaries), matching `qa_audit.py` behavior.
- **Executive synthesis and acquirer intelligence producing zero output** — `max_turns` increased from 15 to 75; agents were burning all turns on file reads before generating JSON. Budget for acquirer intelligence raised from $1 to $3.
- **CLI exit hang on `auto-config` and `query` commands** — added `_terminate_child_processes()` to kill orphaned SDK Bun subprocesses that survive normal Python exit.
- **Auto-config asset-sale focus areas** — added `purchased_assets_schedule`, `excluded_liabilities`, `employee_transfer`, `cure_costs` to deal-type-specific focus areas.
- **JSON parser robustness** — improved extraction of structured JSON from agent text output containing narration.

## [1.0.0] — 2026-04-08

### Breaking

- **`customer` → `subject` rename** (Issue #187) — complete codebase-wide rename across all modules, tests, and configuration.
- **Data file renames** — `customers.csv` → `subjects.csv`, `customer_mentions.json` → `subject_mentions.json`.
- **Checkpoint file renames** — sub-files renamed from `customer_*.json` → `subject_*.json`.
- **Backward-compat aliases removed** — no shim modules, no class aliases; all code must use `subject` directly.
- **Pydantic model fields renamed** — `.customer` → `.subject`, `Classification.customers` → `.subjects`, `CoverageManifest.customers` → `.subjects`.
- **CSS class renames** — `customer-*` → `subject-*` in all HTML report templates and renderers.

### Changed

- HTML report displays "Entity" instead of "Customer" for external-facing content.
- Version bump from 0.5.13 → 1.0.0.

## [0.5.4] — 2026-04-07

### Security

- **CSS injection hardening** — removed parentheses from CSS value allowlist regex in `templates.py`, preventing `url()` / `expression()` injection vectors.
- **Production assert removal** — replaced `assert last_error is not None` in pipeline retry loop with explicit `RuntimeError` (asserts are stripped by `python -O`).

### Fixed

- **`lstrip("#")` → `removeprefix("#")`** — 6 instances in `excel.py` where `lstrip` could strip multiple `#` characters from color hex values (e.g., `"#00FF00"` → `"FF00"` instead of `"00FF00"`).
- **Redundant `Exception` in except tuple** — `except (json.JSONDecodeError, OSError, Exception)` in engine.py made the specific catches dead code; narrowed to `except (json.JSONDecodeError, OSError)`.
- **Class attribute mutation** — `PromptBuilder.MAX_LISTED_FILES` was mutated via `self.MAX_LISTED_FILES = ...`, affecting all instances; now uses explicit instance attribute `self.max_listed_files`.
- **Silent exception logging** — `PromptBuilder._coerce_deal_config` bare `except Exception: return None` now logs the error at DEBUG level.
- **Redundant import** — removed local `import datetime` in `_write_audit_log` that shadowed the module-level import.

### Changed

- **Encoding fallback logging** — `extraction/_helpers.py` now logs at DEBUG when falling back from UTF-8 to latin-1 encoding.
- **Doc accuracy** — fixed check counts in `dod.py` docstring (30→31), QA audit reference (17→18 checks), stale comment in `state.py`.
- **Test & doc counts updated** — README badge (3,267→3,289), CONTRIBUTING.md (~2,900→~3,300, 9→24 E2E), CLAUDE.md (~3,000+→~3,300), IMPLEMENTATION_PLAN.md refreshed with post-phase feature history.

## [0.5.1] — 2026-04-06

### Added

- **Excel cell formatting (E-1/E-2)** — `read_office` tool now renders dates as ISO-8601, currencies with symbols, and percentages with `%` suffix instead of raw openpyxl values. Guards against NaN/Inf in numeric formatting.
- **Sub-table detection (E-3)** — Blank rows in spreadsheets split into separate logical tables, each with its own column-letter headers.
- **Table-aware chunking (E-4)** — Search chunker detects markdown tables and splits at row boundaries with header repetition, preserving table structure for LLM analysis.
- Security tests for `read_office` path traversal validation.
- Edge-case tests for NaN, Inf, and negative currency formatting.
- Proper `__all__` exports for `precedence` and `reasoning` packages.

### Security

- **SSRF redirect validation** — HTTP redirects now re-validated against SSRF blocklist via `_NoRedirectHandler`.
- **Credential bypass fix** — removed silent `except Exception: pass` that skipped embedded-credential checks in `net_safety.py`.
- **AWS ECS metadata IP** (`169.254.170.2`) added to SSRF blocklist.
- **XSS fix** — `html.escape()` on LLM-sourced severity values in HTML customer renderer.
- **Bash blocklist hardening** — `dd of=`, `python -m`, `python3 -m` added to pre-tool hook blocklist.

### Fixed

- **Gap severity mapping** — "critical" keywords now correctly map to P0 (was P1), "important" to P1 (was P2) in merge gap recovery.
- **File descriptor leak** in `chronicle.py` atomic write exception handler.
- **Config triple-read eliminated** — step 1 now reads `deal-config.json` once, validates via `validate_deal_config()`, and hashes the same bytes.
- **Platform encoding safety** — explicit `encoding="utf-8"` on all `read_text()`/`write_text()` calls across 15+ modules.

### Changed

- **DRY constants** — `NON_CUSTOMER_STEMS`, `ALL_SPECIALIST_AGENTS`, `SEVERITY_ORDER` extracted to `utils/constants.py`; removed duplicate definitions from `merge.py`, `pre_merge.py`, `computed_metrics.py`, `html_base.py`.
- **`net_safety.py` refactored** — `_validate_common()` shared helper eliminates code duplication between `validate_url` and `resolve_and_validate`.
- **Removed 12 redundant inline `_Path` imports** across 5 files, replaced with top-level `from pathlib import Path`.
- `ThreadPoolExecutor` in `reference_downloader.py` now used as context manager.

### Documentation

- **"5-layer" → "6-layer"** numerical audit references corrected across 14 plan docs.
- **"30 DoD" → "31 DoD"** corrected across 9 plan docs, CHANGELOG, and PRODUCTION_HARDENING_PLAN.
- **ReportingLead removed** from `06-agents.md` — replaced with deterministic merge documentation reflecting v0.4.0 architecture.
- CLI reference updated with knowledge commands (`log`, `annotate`, `lineage`, `health`) and `--no-knowledge`/`--no-file` flags.
- Inline docstrings updated for qa_audit (18 checks), engine (31 DoD), numerical_audit (6 layers).

## [Unreleased]

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
- New `src/dd_agents/knowledge/` package with 12 modules and 30+ public API exports.
- 234 new unit tests for knowledge package (total: 3,267 unit tests).
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
- **13 AI agents**: 9 specialists (Legal, Finance, Commercial, ProductTech, Cybersecurity, HR, Tax, Regulatory, ESG) + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence — all driven by `claude-agent-sdk`. Agent set is extensible via `AgentRegistry` and config-driven via `deal-config.json`.
- **137 Pydantic v2 data models** covering findings, gaps, manifests, config, inventory, quality scores, and all intermediate pipeline schemas.
- **CLI** with 16 commands: `run`, `validate`, `version`, `init`, `auto-config`, `search`, `assess`, `export-pdf`, `query`, `chat`, `portfolio` (group), `templates` (group), `log`, `annotate`, `lineage`, `health`.

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
- **6-layer numerical audit system** and **31 Definition of Done checks** as fail-closed quality gates.
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

- 137 Pydantic v2 data models.
- 6-pass cascading entity resolution.
- Document extraction pipeline.
- 35-step deterministic orchestrator with 5 blocking quality gates.
- 4 specialist agents + Judge + Reporting Lead.
- Schema-driven 14-sheet Excel report.
- 6-layer numerical audit system and 31 DoD checks.
- CLI with `run`, `validate`, and `version` commands.
- Optional ChromaDB vector store integration.
- Three-tier persistence layer.
- Hook-enforced quality gates.
- Custom MCP tools.
- Deal configuration system with JSON schema validation.
- Quickstart example with sample data room.
- Dockerfile with multi-stage build.
