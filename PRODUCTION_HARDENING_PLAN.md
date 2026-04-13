# Production Hardening Plan

> **ARCHIVED** — All issues in this plan are RESOLVED as of v0.4.1 (2026-03-05). This document is kept for historical reference. See [CHANGELOG.md](CHANGELOG.md) for the current state.

> Original plan to bring the pipeline from functional prototype to
> production-grade quality: resilient, complete, stable, and accurate.

**Epic**: [#32](https://github.com/zoharbabin/due-diligence-agents/issues/32)
**Baseline at plan creation**: 1635 unit tests passing, mypy strict clean, ruff clean (v0.3.1)

> **Status (v0.4.1, 2026-03-05)**: ALL ISSUES RESOLVED. All P0/P1/P2/P3/P4 issues across 40+ tracked issues complete. Production hardening (#68-#80), post-production fixes (#81-#86), feature issues (#49, #65, #51, #11, #9, #6, #3, #2, #7), 100% coverage roadmap (#87-#94, #95), runaway agent defense (#96), Reporting Lead replacement (#97), report redesign (#113), severity calibration (#114), and data quality separation all implemented. 2149 unit tests, 17 integration, mypy strict, ruff clean. Pipeline production-tested: 73 merged subjects, 498 findings, audit PASSED.

---

## Table of Contents

1. [Goals and Success Criteria](#1-goals-and-success-criteria)
2. [Guiding Principles](#2-guiding-principles)
3. [Sensitive Data Policy](#3-sensitive-data-policy)
4. [Quality Gates](#4-quality-gates)
5. [Issue Inventory](#5-issue-inventory)
6. [Dependency Graph](#6-dependency-graph)
7. [Execution Waves](#7-execution-waves)
8. [Wave 0 — Crash Fixes and Core Wiring](#wave-0--crash-fixes-and-core-wiring-p0)
9. [Wave 1 — Data Integrity and Correctness](#wave-1--data-integrity-and-correctness-p1)
10. [Wave 2 — Robustness and Resilience](#wave-2--robustness-and-resilience-p2)
11. [Wave 3 — Observability and Polish](#wave-3--observability-and-polish-p3)
12. [Testing Strategy](#12-testing-strategy)
13. [Code Quality Standards](#13-code-quality-standards)
14. [Architectural Concerns](#14-architectural-concerns)
15. [Risk Register](#15-risk-register)
16. [Definition of Done (per issue)](#16-definition-of-done-per-issue)

---

## 1. Goals and Success Criteria

### What we are building toward

A pipeline that can process a production data room (100+ subjects, 1000+ files,
mixed PDF/DOCX/images) end-to-end and produce a correct, complete, auditable
Excel report — or fail loudly with actionable diagnostics.

### Success criteria

| Criterion | Metric | Current | Target |
|-----------|--------|---------|--------|
| **Stability** | Pipeline completes without crash on valid data rooms | Crashes on missing schema, missing manifest field | Zero crashes on valid input |
| **Completeness** | Every subject appears in output with all required columns | Gaps silently dropped through merge/model/Excel chain | 100% subject coverage or explicit gap findings |
| **Accuracy** | Citation quotes match source documents | Page markers stripped in multi-chunk, cross-file search incomplete | All citations verified against source text |
| **Blocking gates** | 5 gates block on failure as specified | 4 of 5 gates do not actually block | All 5 gates enforce their contracts |
| **Agent integration** | Agents produce real findings via Claude Agent SDK | All agent calls are placeholders returning empty strings | Full SDK integration with retry and recovery |
| **Validation** | 31 DoD checks enforce quality | 19 of 31 checks hardcoded to pass | All 31 checks implemented against real data |
| **Resume** | Pipeline can resume from checkpoint after interruption | State not fully serialized, runtime attributes lost | Full checkpoint/resume with atomic persistence |
| **Test coverage** | Critical paths have unit tests | 1544 tests, all modules covered | Target exceeded |

---

## 2. Guiding Principles

### 2.1 Fail loud, not silent

Every error must either be handled with an explicit recovery path or raised as
a blocking gate failure. No `except Exception: pass`. No `or True` to bypass
checks. No hardcoded `passed=True` in validation.

**Why**: In legal due diligence, a silently dropped finding or a missed subject
is worse than a pipeline crash. Lawyers need to trust that absence of a finding
means the contract was reviewed, not that the pipeline failed quietly.

### 2.2 Test-first, always

Write the test before the fix. The test must fail before the fix and pass after.
This ensures we are fixing the actual bug, not a related symptom.

**How**: For each issue, the PR must include:
1. A test that reproduces the bug (red)
2. The minimal code change to fix it (green)
3. Quality gates pass (refactor if needed)

### 2.3 Minimal, focused changes

Each issue is a single logical change. Do not bundle unrelated fixes. Do not
refactor surrounding code unless it is required for the fix. Do not add features
beyond the issue scope.

**Why**: Small changes are easier to review, test, and revert. They also reduce
merge conflicts when multiple issues are in flight.

### 2.4 Spec compliance

Every implementation must match its spec doc in `docs/plan/`. When the spec
conflicts with the current code, the spec wins unless there is an explicit
documented reason to deviate.

**Where**: Key spec references are listed per issue below and in `CLAUDE.md`.

### 2.5 No regressions

The existing 1544 tests must continue to pass after every change. If a fix
necessarily changes behavior, update the affected tests in the same commit.

---

## 3. Sensitive Data Policy

This policy applies to ALL code, tests, documentation, commit messages, issue
descriptions, and PR content in this repository.

### Prohibited content

- Real company names, people's names, financial figures, or addresses
- Actual contract text, clause language, or deal terms
- Data room file paths that reveal subject identities
- API keys, tokens, credentials, or connection strings

### Required practices

- Tests use generic placeholders: `"Subject A"`, `"file_1.pdf"`, `42.0`
- Example prompts use `"[SUBJECT]"`, `"[DOCUMENT]"`, `"[AMOUNT]"`
- Commit messages describe the code change, not the business context
- Issue descriptions reference module paths and line numbers, not deal specifics
- `.env` files are in `.gitignore` and never committed

### Enforcement

- Pre-commit hook checks for common patterns (email addresses, dollar amounts
  with commas, known company name patterns)
- Code review checks for any string literal that could be real data
- CI pipeline rejects commits containing `.env` or credential file patterns

---

## 4. Quality Gates

Run after EVERY change, before every commit:

```bash
# Fast check (mandatory)
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/

# Full check (before PR merge)
pytest tests/unit/ -x -q && \
pytest tests/integration/ -x -q && \
mypy src/ --strict && \
ruff check src/ tests/ && \
ruff format src/ tests/ --check
```

### Gate definitions

| Gate | Tool | Threshold | Blocks merge? |
|------|------|-----------|---------------|
| Unit tests | pytest | 100% pass | Yes |
| Integration tests | pytest | 100% pass | Yes |
| Type safety | mypy --strict | 0 errors | Yes |
| Lint | ruff check | 0 violations | Yes |
| Format | ruff format --check | 0 diffs | Yes |

---

## 5. Issue Inventory

### 5.1 All tracked issues (35 from deep review + epic)

| # | Title | Priority | Category |
|---|-------|----------|----------|
| **32** | **Epic: Pipeline Resilience, Scale & Accuracy** | **P0** | **Epic** |
| 33 | Wire agent integration with claude-agent-sdk | P0 | Agent |
| 34 | NumericalManifest missing `generated_at` crashes audit | P0 | Validation |
| 35 | Excel generation crashes on missing `report_schema.json` | P0 | Reporting |
| 37 | Implement subject batching in step 14 | P0 | Scale |
| 46 | Agent output parsing: silent data loss, no validation | P0 | Agent |
| 36 | Parallelize document extraction | P1 | Scale |
| 38 | Activate coverage gate, respawn for missing subjects | P1 | Resilience |
| 39 | Detect silent context exhaustion | P1 | Resilience |
| 40 | Error taxonomy + ErrorRecoveryManager | P1 | Resilience |
| 44 | Implement placeholder steps 15, 18, 20-22 | P1 | Orchestrator |
| 47 | Merge/dedup bugs: collisions, fake citations, paths | P1 | Reporting |
| 48 | Findings quality: reject dropped citations | P1 | Validation |
| 49 | Numerical audit Layer 2: N003-N010 rederivation | P1 | Validation |
| 50 | QA audit hardcoded passes + DoD stubs | P1 | Validation |
| 52 | LLM robustness mitigations in agent prompts | P1 | Agent |
| 53 | Excel reporting bugs + step 31 gate | P1 | Reporting |
| 54 | Step 27 numerical audit never blocks | P1 | Orchestrator |
| 55 | Step 28 QA audit never blocks | P1 | Orchestrator |
| 57 | Pipeline state not serialized — resume broken | P1 | Orchestrator |
| 58 | Judge always exits "all pass" — zeroed scores | P1 | Agent |
| 60 | Gaps silently lost through pipeline | P1 | Reporting |
| 61 | Search: page markers stripped, unbounded concurrency | P1 | Search |
| 65 | Model type safety: strings that should be enums | P1 | Models |
| 40 | Error taxonomy + ErrorRecoveryManager | P1 | Resilience |
| 43 | Shared resource concurrency protection | P2 | Resilience |
| 45 | Incremental/resume: prior_run_id never populated | P2 | Persistence |
| 51 | Mid-agent checkpointing + corruption recovery | P2 | Resilience |
| 56 | Step 35 DoD results not persisted | P2 | Orchestrator |
| 59 | Extraction: resource leaks, routing, confidence | P2 | Extraction |
| 62 | Inventory archiving never executes | P2 | Persistence |
| 63 | Non-atomic writes + run_id collision | P2 | Persistence |
| 64 | Entity resolution: phantom names, cache never saved | P2 | Entity |
| 66 | Incremental files_modified compares list indices | P2 | Persistence |
| 41 | Extraction systemic failure detection (polish) | P3 | Extraction |
| 42 | Agent activity monitoring + adaptive timeouts | P3 | Resilience |

### 5.2 Pre-existing backlog (not part of this plan)

These are feature enhancements tracked separately. They do not block production
hardening and should be addressed after all P0-P2 issues are resolved.

| # | Title | Priority |
|---|-------|----------|
| 2 | Replace pytesseract with pluggable OCR backend | P4 | **COMPLETE** — `ocr_registry.py` |
| 3 | Add layout-aware PDF extraction | P4 | **COMPLETE** — `layout_pdf.py` |
| 6 | Replace markitdown with pluggable document backend | P2 | **COMPLETE** — `backend.py` Protocol + ExtractionChain |
| 7 | Add visual grounding with bounding box citations | P4 | **COMPLETE** — `coordinates.py` + BoundingBox model |
| 9 | Generate interactive HTML review pages | P2 | **COMPLETE** — `html.py` HTMLReportGenerator |
| 11 | Add cross-document entity resolution | P2 | **COMPLETE** — `dedup.py` CrossDocumentDeduplicator |

---

## 6. Dependency Graph

```
Legend: A → B means "A must be completed before B can start"

Wave 0 (P0 — no dependencies between them):
  #34 (manifest crash)     — standalone
  #35 (Excel crash)        — standalone
  #46 (output parsing)     — standalone
  #33 (agent wiring)       — standalone
  #37 (subject batching)  — standalone
  #65 (model type safety)  — standalone

Wave 1 (P1 — depends on Wave 0):
  #33 → #38 (coverage gate needs real agents)
  #33 → #39 (context exhaustion needs real agents)
  #33 → #44 (steps 18, 20-22 need agent wiring)
  #33 → #52 (prompt mitigations need agent integration)
  #33 → #58 (judge fix needs agent wiring)
  #46 → #38 (coverage gate needs parse failure detection)
  #46 → #47 (merge dedup needs parsed output)
  #46 → #48 (findings quality needs parsed output)
  #40 → #38 (coverage gate uses ErrorRecoveryManager)
  #40 → #39 (context detection uses error taxonomy)
  #34 → #49 (N003-N010 needs valid manifest)
  #34 → #54 (step 27 fix needs valid manifest)
  #50 → #55 (step 28 uses QA audit checks)
  #47 → #53 (Excel bugs depend on correct merged data)
  #47 → #60 (gaps lost through merge)

Wave 2 (P2 — depends on Waves 0-1):
  #33 → #43 (concurrency needs real agent runs)
  #33 → #51 (mid-agent checkpoint needs real agents)
  #57 → #45 (resume needs serialized state)
  #57 → #51 (mid-agent checkpoint needs serializable state)
  #62 → #45 (incremental needs working archiving)
  #63 → #45 (incremental needs atomic writes)
  #66 → #45 (incremental needs correct file diff)

Wave 3 (P3 — depends on Wave 2):
  #33 → #42 (monitoring needs real agent runs)
  #41 → nothing (>50% gate already works, polish only)
```

---

## 7. Execution Waves

### Implementation order within each wave

Issues within each wave should be implemented in the order listed below. This
order minimizes merge conflicts and ensures dependencies within the wave are
satisfied incrementally.

---

## Wave 0 — Crash Fixes and Core Wiring (P0)

**Goal**: Eliminate all crash-on-valid-input paths. Wire the agent subsystem to
the real Claude Agent SDK. Establish the foundation that all subsequent waves
depend on.

**Entry criteria**: Current main branch, 1544 tests passing
**Exit criteria**: Pipeline can run steps 1-13 without crashing. Agent calls
reach the SDK (even if agents are not fully functional yet). All P0 issues
closed.

### Issue #34 — NumericalManifest missing `generated_at` crashes audit

**What**: The `NumericalManifest` Pydantic model requires a `generated_at` field,
but the manifest builder in `engine.py` (step 26) does not populate it. When
step 27 loads the manifest, Pydantic validation fails and the audit crashes.

**Why it matters**: This crash is the first thing a user hits when running the
full pipeline. It blocks all validation.

**Where**: `src/dd_agents/orchestrator/engine.py` (step 26, ~line 920),
`src/dd_agents/models/numerical.py`

**How**:
1. Add `generated_at=datetime.now(timezone.utc).isoformat()` to manifest construction
2. Add a test that builds a manifest and validates it loads without error
3. Add a test that a manifest without `generated_at` raises `ValidationError`

**Spec**: `docs/plan/11-qa-validation.md` (NumericalManifest schema)

**Tests**: `tests/unit/test_validation.py` — add 2 tests

---

### Issue #35 — Excel generation crashes on missing `report_schema.json`

**What**: `excel.py` loads `report_schema.json` at initialization. If the file
does not exist or is empty, the code raises an unhandled exception instead of a
clear error message.

**Why it matters**: New installations or misconfigured deployments hit this
immediately on any report generation attempt.

**Where**: `src/dd_agents/reporting/excel.py` (initialization)

**How**:
1. Add graceful error handling: if schema file is missing, raise
   `ConfigurationError` with a clear message pointing to the expected path
2. If schema file is empty or invalid JSON, raise with specific parse error
3. Add a bundled default schema as package data fallback

**Spec**: `docs/plan/10-reporting.md`

**Tests**: `tests/unit/test_reporting.py` — add 3 tests (missing, empty, invalid)

---

### Issue #46 — Agent output parsing: silent data loss

**What**: `_parse_agent_output()` in `agents/base.py` returns an empty list on
any parse failure with no logging. This means agent output is silently discarded.

**Why it matters**: This is the most dangerous bug in the codebase. When agents
are wired (#33), this will be the first point of data loss. An agent could
produce 200 findings and the pipeline would silently report zero.

**Where**: `src/dd_agents/agents/base.py` (~line 215)

**How**:
1. Add structured logging on parse failure (log the raw output, the parse error,
   the agent name, the expected schema)
2. Add Pydantic schema validation of parsed output
3. Raise `AgentOutputParseError` instead of returning empty list
4. Add retry logic: if parse fails, attempt JSON repair (strip markdown fences,
   fix trailing commas)
5. If all parse attempts fail, preserve raw output to disk for debugging

**Spec**: `docs/plan/06-agents.md`, `docs/plan/12-error-recovery.md`

**Tests**: `tests/unit/test_agents.py` — add 8 tests (valid JSON, invalid JSON,
markdown-wrapped JSON, truncated JSON, empty output, schema mismatch, raw output
preservation, retry success)

---

### Issue #33 — Wire agent integration with claude-agent-sdk

**What**: The agent subsystem (`agents/base.py`, `specialists.py`, `judge.py`)
contains placeholder implementations that return empty strings instead of
calling the Claude Agent SDK.

**Why it matters**: This is the critical path. Nothing downstream of step 14
produces real output until agents are wired. This blocks 15+ other issues.

**Where**: `src/dd_agents/agents/base.py` (line ~167), `specialists.py`,
`judge.py`, `src/dd_agents/hooks/` (return types wrong),
`src/dd_agents/tools/server.py` (missing MCP integration)

**How**:
1. Replace `_spawn_agent` placeholder with actual `claude_agent_sdk.query()` call
2. Wire `ClaudeAgentOptions` with system prompt, tools, hooks, budget
3. Fix hook return types (currently return tuples, SDK expects flat dicts)
4. Create `hooks/factory.py` for SDK hook registration
5. Wire MCP tool server for agent-accessible tools
6. Update specialist classes to use the real spawn path
7. Wire judge iteration loop to use actual SDK responses
8. Implement `_build_scores_from_result` to parse real judge output

**Spec**: `docs/plan/06-agents.md`, `docs/plan/07-tools-and-hooks.md`

**Tests**: `tests/unit/test_agents.py` — update existing tests, add 10+ new
tests with mocked SDK calls

**Concerns**:
- Hook return type changes may break existing tests — update systematically
- SDK version compatibility: pin to `>=0.1.39` as in `pyproject.toml`
- Tool handler/definition signature alignment with SDK expectations

---

### Issue #37 — Implement subject batching in step 14

**What**: Step 14 assigns subjects to agents but uses a naive fixed-token
estimation (`tokens_per_subject=50`) that does not account for actual extracted
text size. For large data rooms, this produces poorly balanced batches.

**Why it matters**: Unbalanced batches cause context exhaustion in some agents
while others are underutilized. This is the root cause of Scenarios 7-8 in the
error recovery spec.

**Where**: `src/dd_agents/orchestrator/engine.py` (step 14, ~line 704),
`src/dd_agents/agents/prompt_builder.py` (batch_subjects method, ~line 270)

**How**:
1. Replace fixed token estimation with actual extracted text size measurement
2. Implement `_estimate_subject_tokens()` that reads text index file sizes
3. Use bin-packing algorithm to distribute subjects across batches
4. Target 150K chars per batch (per spec 22 and search guide finding)
5. Add batch size validation: reject batches that exceed model context limit

**Spec**: `docs/plan/05-orchestrator.md`, `docs/plan/22-llm-robustness.md`

**Tests**: `tests/unit/test_orchestrator.py` — add 5 tests (balanced batching,
single large subject, many small subjects, empty data room, token estimation)

---

### Issue #65 — Model type safety: strings that should be enums

**What**: Several Pydantic models use `str` fields where enum types should
enforce valid values. The `Confidence` enum case mismatch between search module
(UPPERCASE) and enum definition (lowercase) causes validation issues.

**Why it matters**: Invalid values pass validation silently, causing downstream
logic errors that are hard to trace.

**Where**: `src/dd_agents/models/persistence.py`, `models/config.py`,
`models/search.py`

**How**:
1. Replace `execution_mode: str` with `execution_mode: ExecutionMode`
2. Replace `completion_status: str` with validated enum
3. Fix confidence normalization to match enum case
4. Add `@field_validator` for computed fields like `FindingCounts.total`
5. Replace date regex validation with `datetime.date` type

**Spec**: `docs/plan/04-data-models.md`

**Tests**: `tests/unit/test_models/test_config.py` — add validation tests

---

## Wave 1 — Data Integrity and Correctness (P1)

**Goal**: Every piece of data that enters the pipeline exits correctly. Blocking
gates enforce their contracts. Findings, gaps, and citations flow through merge,
validation, and reporting without loss or corruption.

**Entry criteria**: Wave 0 complete, agents wired to SDK
**Exit criteria**: All 5 blocking gates functional. Merge/dedup produces correct
output. Excel report matches pipeline state. All P1 issues closed.

### Issue #40 — Error taxonomy + ErrorRecoveryManager

**What**: The spec defines 15 error scenarios with structured error records and
an `ErrorRecoveryManager`. None of this exists in code. Errors are caught with
bare `except Exception` and logged as warnings.

**Where**: `src/dd_agents/errors.py` (to create), `src/dd_agents/orchestrator/recovery.py` (to create)

**Spec**: `docs/plan/12-error-recovery.md` (full implementation guide)

---

### Issue #57 — Pipeline state not serialized — resume broken

**What**: Runtime attributes (`_discovered_files`, `_subject_entries`,
`_reference_files`, `_entity_resolver`) are stored via `type: ignore[attr-defined]`
and never included in checkpoint serialization. `deal_config` is also missing
from `to_checkpoint_dict()`.

**Where**: `src/dd_agents/orchestrator/state.py`, `checkpoints.py`

**Spec**: `docs/plan/05-orchestrator.md` (checkpoint/resume)

---

### Issue #54 — Step 27 numerical audit never blocks

**What**: Step 27 catches ALL exceptions and always sets
`validation_results["numerical_audit"] = True`. The "BLOCKING GATE" label in
the docstring is misleading.

**Where**: `src/dd_agents/orchestrator/engine.py` (~lines 1039-1042)

**How**: Remove the blanket `except Exception`, let `BlockingGateError` propagate.
Add structured error handling per the error taxonomy (#40).

---

### Issue #55 — Step 28 QA audit never blocks

**What**: Same pattern as #54. The QA audit runs and logs but never raises
`BlockingGateError`.

**Where**: `src/dd_agents/orchestrator/engine.py` (~lines 1060-1068)

---

### Issue #49 — Numerical audit Layer 2: N003-N010 rederivation

**What**: `_rederive()` only handles N001 and N002. The remaining 8 entries
(N003-N010) hit a generic fallback that returns the existing value unchanged,
making Layer 2 a no-op for most entries.

**Where**: `src/dd_agents/validation/numerical_audit.py` (~lines 284-293)

**Spec**: `docs/plan/11-qa-validation.md` (Layer 2 specification with all 10
rederivation formulas)

---

### Issue #50 — QA audit hardcoded passes + DoD stubs

**What**: 19 of 31 DoD checks are hardcoded to `passed=True` or use `or True`.
3 QA audit checks (`gap_completeness`, `cross_reference_completeness`,
schema conditional checks) are hardcoded.

**Where**: `src/dd_agents/validation/dod.py`, `qa_audit.py`, `schema_validator.py`

**Spec**: `docs/plan/11-qa-validation.md` (all 31 DoD checks with implementation)

---

### Issue #47 — Merge/dedup bugs

**What**: Empty citation collision in `_match_key`, auto-generated fake citation
with `source_path="unknown"`, cross-ref dedup, path normalization issues.

**Where**: `src/dd_agents/reporting/merge.py`

**Spec**: `docs/plan/10-reporting.md`

---

### Issue #60 — Gaps silently lost through pipeline

**What**: Gap findings are silently dropped at multiple points: merge step 6 not
implemented, gap model missing fields, Excel gap sheet always empty, QA gap
check hardcoded.

**Where**: `reporting/merge.py`, `models/finding.py`, `reporting/excel.py`,
`validation/qa_audit.py`

---

### Issue #48 — Findings quality: reject dropped citations

**What**: No pre-generation validation that P0/P1 findings have non-empty
citations. Findings can reach the report with empty `exact_quote` fields.

**Where**: `src/dd_agents/reporting/merge.py`, `validation/qa_audit.py`

---

### Issue #53 — Excel reporting bugs + step 31 gate

**What**: Step 31 post-generation validation does not actually validate. Multiple
Excel generation bugs produce incorrect cell references.

**Where**: `src/dd_agents/reporting/excel.py`, `orchestrator/engine.py` (step 31)

---

### Issue #38 — Activate coverage gate + respawn

**What**: Step 17 coverage gate is labeled "BLOCKING" but does not respawn
agents for missing subjects or generate gap findings.

**Depends on**: #33 (agents), #46 (parsing), #40 (error taxonomy)

**Spec**: `docs/plan/12-error-recovery.md` (Scenarios 2, 7, 8, 15)

---

### Issue #39 — Detect silent context exhaustion

**What**: No detection for agents that silently stop producing output mid-task.

**Depends on**: #33 (agents), #40 (error taxonomy)

**Spec**: `docs/plan/12-error-recovery.md` (Scenario 8)

---

### Issue #44 — Implement placeholder steps 15, 18, 20-22

**What**: Steps 15 (route reference files), 18 (post-agent checks), 20-22
(judge iteration) are placeholders with `pass` bodies.

**Where**: `src/dd_agents/orchestrator/engine.py`

**Note**: Step 15 has no dependencies and can be implemented immediately.
Steps 18, 20-22 depend on #33 (agent wiring).

---

### Issue #52 — LLM robustness mitigations

**What**: Agent prompts are missing 5 of 11 required sections per spec 22.
Mitigations for hallucination, context exhaustion, and format drift are not
implemented.

**Depends on**: #33 (agents)

**Spec**: `docs/plan/22-llm-robustness.md`

---

### Issue #58 — Judge always exits "all pass"

**What**: `_build_scores_from_result` always returns zeroed scores, causing the
judge iteration loop to always exit on the first pass with "all pass".

**Depends on**: #33 (agents)

**Where**: `src/dd_agents/agents/judge.py`

---

### Issue #36 — Parallelize document extraction

**What**: `extract_all()` processes files serially. For 1000+ files with OCR,
this is the primary bottleneck.

**Where**: `src/dd_agents/extraction/pipeline.py` (~line 173)

**How**: Use `concurrent.futures.ThreadPoolExecutor` with configurable worker
count. Add thread safety to `ExtractionQualityTracker` and `ExtractionCache`.

**Concerns**:
- MuPDF's `fitz.TOOLS.mupdf_display_errors()` is global state — not thread-safe
- `GlmOcrExtractor` has mutable instance state without locking
- Need to cap concurrency to avoid memory exhaustion on large PDFs

---

### Issue #61 — Search module bugs

**What**: Page markers stripped from multi-chunk segments (critical for citation
accuracy), unbounded API concurrency per subject, verification stops on first
failure.

**Where**: `src/dd_agents/search/chunker.py` (~line 194),
`search/analyzer.py`, `search/runner.py`

**Spec**: `docs/search-guide.md`, `docs/plan/22-llm-robustness.md`

---

## Wave 2 — Robustness and Resilience (P2)

**Goal**: Pipeline handles adverse conditions gracefully. Concurrent access is
safe. Persistence is atomic. Resume works correctly.

**Entry criteria**: Wave 1 complete, blocking gates functional
**Exit criteria**: Checkpoint/resume works end-to-end. Incremental mode produces
correct diffs. All P2 issues closed.

### Issue #45 — Fix incremental/resume mode

**Depends on**: #57 (state serialization), #62 (archiving), #63 (atomic writes),
#66 (file diff)

---

### Issue #62 — Inventory archiving never executes

**What**: `ensure_run_dirs()` pre-creates the `inventory_snapshot` directory,
so `archive_versioned()` sees it as already existing and skips the archive.

**Where**: `src/dd_agents/persistence/tiers.py`

---

### Issue #63 — Non-atomic writes + run_id collision

**What**: Multiple persistence modules write directly to target files. If the
process crashes mid-write, files are left corrupt. run_id uses second-level
timestamp precision.

**Where**: `persistence/run_manager.py`, `persistence/tiers.py`,
`orchestrator/checkpoints.py`, `entity_resolution/cache.py`

**How**: Write to temp file, then `os.replace()` (atomic on all platforms).
Add UUID suffix to run_id.

---

### Issue #66 — Incremental files_modified compares list indices

**What**: The diff detection compares checksums by list position rather than by
filename, producing incorrect results when files are added, removed, or reordered.

**Where**: `src/dd_agents/persistence/incremental.py` (~lines 104-108)

---

### Issue #64 — Entity resolution bugs

**What**: `_pass_5_parent_child` returns non-existent canonical names.
`EntityResolver` never calls `cache.save()` or `cache.compute_invalidation()`.

**Where**: `src/dd_agents/entity_resolution/matcher.py`, `cache.py`, `resolver.py`

---

### Issue #59 — Extraction resource leaks and routing

**What**: pypdfium2 documents and PIL Images not closed. Encrypted PDFs not
routed to skip text extractors. OCR confidence not scaled by page success rate.

**Where**: `extraction/glm_ocr.py`, `extraction/ocr.py`, `extraction/pipeline.py`

---

### Issue #43 — Shared resource concurrency protection

**What**: Multiple concurrent runs can corrupt shared PERMANENT-tier files.

**Spec**: `docs/plan/12-error-recovery.md` (Scenario 10)

---

### Issue #51 — Mid-agent checkpointing

**What**: If the pipeline crashes during a long agent run (30+ minutes), all
progress is lost.

**Depends on**: #57 (state serialization), #33 (agents)

---

### Issue #56 — Step 35 DoD results not persisted

**What**: Step 35 runs all DoD checks but only logs pass/fail count. Results
are not stored, not written to disk, do not affect exit status.

**Where**: `src/dd_agents/orchestrator/engine.py` (~lines 1214-1234)

---

## Wave 3 — Observability and Polish (P3)

**Goal**: Monitoring, diagnostics, and edge case handling.

### Issue #41 — Extraction systemic failure detection (polish)

**What**: The >50% failure rate gate already works. Remaining work: extraction
quality summary logging + extraction_audit.json output.

---

### Issue #42 — Agent activity monitoring + adaptive timeouts

**What**: No file-watcher or heartbeat mechanism to detect stalled agents.

**Depends on**: #33 (agents)

**Spec**: `docs/plan/12-error-recovery.md` (Scenario 9)

---

## 12. Testing Strategy

### 12.1 Test-first mandate

Every issue must include tests that:
1. **Reproduce the bug** (if a bug fix) — test must fail on current code
2. **Verify the fix** — test must pass after the change
3. **Guard against regression** — test must be deterministic and fast

### 12.2 Test categories

| Category | Location | When to run | Coverage target |
|----------|----------|-------------|-----------------|
| Unit | `tests/unit/` | Every change | All public APIs |
| Integration | `tests/integration/` | Before PR merge | Pipeline steps 1-13 |
| E2E | `tests/e2e/` | Weekly / pre-release | Full pipeline with API |

### 12.3 What to test

- **Happy path**: Normal input produces expected output
- **Error path**: Invalid input produces clear error (not crash)
- **Boundary conditions**: Empty input, maximum size, Unicode, special characters
- **Concurrency**: Thread-safe operations under concurrent access (for #36, #43)
- **Idempotency**: Running the same step twice produces the same result

### 12.4 What NOT to test

- Private helper functions (test through public APIs)
- Third-party library internals (trust the library, test the integration)
- Exact log messages (test behavior, not wording)

### 12.5 Modules needing new test coverage

| Module | Current tests | Target | Priority |
|--------|--------------|--------|----------|
| `search/runner.py` | 5 (CLI only) | 20 | High (#61) |
| `orchestrator/team.py` | 0 | 10 | High (#33) |
| `models/finding.py` | 0 (indirect) | 12 | Medium (#60) |
| `vector_store/` | 0 | 8 | Low |
| `extraction/ocr.py` | 0 (indirect) | 5 | Medium (#59) |
| `models/entity.py` | 0 | 5 | Medium (#64) |

---

## 13. Code Quality Standards

### 13.1 Python style

- **Python 3.12+** — use modern syntax (match/case, `X | Y` unions, StrEnum)
- **Line length**: 120 characters (per ruff config)
- **Type annotations**: Required on all public functions. `mypy --strict` must pass.
- **Docstrings**: Required on all public classes and functions. One-line for
  trivial functions, Google-style for complex ones.
- **Naming**: snake_case for functions/variables, PascalCase for classes,
  UPPER_CASE for module-level constants

### 13.2 Pydantic models

- Every field must have a `Field(description="...")` annotation
- Use `model_validate()` for all deserialization (not `__init__()` with dicts)
- Use `model_json_schema()` for LLM structured output schemas
- Use `extra="forbid"` to catch unexpected fields in agent output
- Use enums instead of string literals for constrained values

### 13.3 Error handling

- **Never** use bare `except Exception: pass`
- **Always** log the exception at WARNING or ERROR level
- **Classify** errors using the error taxonomy (#40)
- **Propagate** errors that cannot be recovered from
- **Record** errors that are recovered from (ErrorRecoveryManager)

### 13.4 Async patterns

- Pipeline steps are `async` methods on `PipelineEngine`
- Agent calls use `asyncio.wait_for()` with timeouts
- Parallel agent runs use `asyncio.gather()` with `return_exceptions=True`
- File I/O in async context should use thread pool (`asyncio.to_thread()`)

### 13.5 Import organization (enforced by ruff)

```python
# Standard library
from __future__ import annotations

import asyncio
import json
from pathlib import Path

# Third-party
from pydantic import BaseModel, Field

# Local
from dd_agents.models.config import DealConfig
from dd_agents.orchestrator.state import PipelineState
```

---

## 14. Architectural Concerns

### 14.1 Agent SDK coupling

The agent subsystem is tightly coupled to the Claude Agent SDK's API surface.
When wiring agents (#33), create an abstraction layer (`AgentRunner` protocol)
that isolates SDK-specific details. This allows:
- Unit testing with mock agents
- Future SDK version upgrades without rewriting the pipeline
- Potential support for alternative agent frameworks

### 14.2 Global mutable state

MuPDF uses process-global state (`fitz.TOOLS.mupdf_display_errors()`). When
parallelizing extraction (#36), this state must be protected. Options:
- Use a threading lock around MuPDF calls
- Use multiprocessing instead of threading for PDF extraction
- Accept the race condition (MuPDF errors are diagnostics, not correctness)

### 14.3 Persistence atomicity

The current persistence layer is not atomic. Multiple issues (#45, #62, #63, #66)
address individual symptoms, but the root cause is architectural: the persistence
layer lacks a transactional model. The fix for #63 (atomic writes via
`os.replace()`) should be applied as a general pattern across all persistence
modules, not just the specific files mentioned in the issue.

### 14.4 State serialization

The pipeline state uses Python-specific objects (`Path`, custom classes) that do
not serialize to JSON. Issue #57 addresses this for checkpoint/resume, but the
fix should establish a general pattern: all state fields must be either
JSON-serializable or have explicit `to_dict()`/`from_dict()` methods.

### 14.5 Search module context management

The search module's 4-phase analysis (map → merge → synthesis → validation)
creates an unbounded number of concurrent API calls per subject. Issue #61
addresses the immediate bug, but the architectural concern is broader: the search
module needs a global concurrency budget that respects API rate limits.

---

## 15. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Claude Agent SDK breaking change | High | Low | Pin version, test in CI |
| Agent context exhaustion on large data rooms | High | Medium | Subject batching (#37), context detection (#39) |
| Non-atomic writes causing data corruption | Medium | Medium | Atomic writes (#63) across all modules |
| Test suite becoming slow (>60s) | Low | Medium | Keep unit tests fast, use marks for slow tests |
| Merge conflicts between concurrent issue branches | Medium | High | Small PRs, rebase frequently, implement in order |
| Sensitive data leaking into commits | High | Low | Pre-commit hooks, code review checklist |

---

## 16. Definition of Done (per issue)

Every issue is considered done when ALL of the following are true:

- [ ] **Tests written first** — test reproduces the bug or specifies the behavior
- [ ] **Implementation complete** — code change is minimal and focused
- [ ] **Quality gates pass** — `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`
- [ ] **No regressions** — existing tests still pass
- [ ] **No sensitive data** — no real names, financial data, or credentials in code/tests/commits
- [ ] **Spec compliant** — implementation matches the relevant spec doc
- [ ] **Documentation updated** — if behavior changes, update docstrings and relevant docs
- [ ] **Issue closed** — with a comment summarizing what was changed and linking the commit

---

## Appendix: Spec Document Reference

| Spec | Path | Relevant Issues |
|------|------|----------------|
| Architecture | `docs/plan/02-system-architecture.md` | #43, #45, #62, #63 |
| Data Models | `docs/plan/04-data-models.md` | #65 |
| Orchestrator | `docs/plan/05-orchestrator.md` | #37, #44, #54, #55, #56, #57 |
| Agents | `docs/plan/06-agents.md` | #33, #46, #52, #58 |
| Tools & Hooks | `docs/plan/07-tools-and-hooks.md` | #33 |
| Extraction | `docs/plan/08-extraction.md` | #36, #41, #59 |
| Entity Resolution | `docs/plan/09-entity-resolution.md` | #64 |
| Reporting | `docs/plan/10-reporting.md` | #35, #47, #48, #53, #60 |
| QA Validation | `docs/plan/11-qa-validation.md` | #34, #49, #50 |
| Error Recovery | `docs/plan/12-error-recovery.md` | #38, #39, #40, #42 |
| LLM Robustness | `docs/plan/22-llm-robustness.md` | #52, #61 |
| Search Guide | `docs/search-guide.md` | #61 |
