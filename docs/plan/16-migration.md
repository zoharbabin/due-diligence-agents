# 16 — Migration from Claude Code Skill

## Overview

This document provides a step-by-step migration plan from the existing Claude Code Skill (`~/.claude/skills/forensic-dd/SKILL.md` + 8 reference files, totaling 3,100+ lines) to the Python Agent SDK application (`dd_agents`). The migration is phased so that the existing skill remains fully functional throughout -- no "big bang" cutover.

Cross-reference: `01-architecture-decisions.md` ADR-01 (why SDK over Skills), `03-project-structure.md` (target layout), `18-implementation-order.md` (build dependency graph).

---

## 1. Migration Principles

1. **Parallel operation**: The skill and SDK coexist. The skill is not modified or disabled until the SDK is validated.
2. **Content preservation**: All 3,100+ lines of domain knowledge (extraction rules, severity taxonomy, governance protocol, gap detection, cross-reference reconciliation, entity resolution, reporting schema) transfer as agent prompts and Pydantic models. The analytical content is unchanged.
3. **Incremental validation**: Each phase has acceptance criteria. Do not proceed to the next phase until the current phase passes.
4. **Production comparison**: The final validation (end of Phase 4) runs the SDK on the same reference data room that the skill processed, and compares outputs.

---

## 2. What Transfers, What Changes

### 2.1 Transfers Directly (Domain Knowledge)

| Skill Source | SDK Destination | Content |
|-------------|----------------|---------|
| `SKILL.md` section 4 + `domain-definitions.md` | `src/dd_agents/agents/prompt_builder.py` | Extraction rules, severity taxonomy, governance protocol, gap detection, cross-reference reconciliation |
| `agent-prompts.md` | `src/dd_agents/agents/prompt_builder.py` | Agent prompt templates (Legal, Finance, Commercial, ProductTech, Judge, Reporting Lead) |
| `entity-resolution-protocol.md` | `src/dd_agents/entity_resolution/` | 6-pass cascading matcher, cache protocol, short name guards |
| `reporting-protocol.md` | `src/dd_agents/reporting/` | Merge/dedup rules, 14-sheet structure, report diff |
| `numerical-validation.md` | `src/dd_agents/validation/numerical_audit.py` | 6-layer validation framework |
| `deal-config.schema.json` | `src/dd_agents/models/config.py` | Deal configuration Pydantic model |
| `report_schema.json` | `src/dd_agents/reporting/schema.py` | Excel report structure (loaded at runtime) |
| `deal-config.template.json` | `src/dd_agents/config/deal-config.template.json` | Template for new deals |
| `dd-framework/schemas/*.json` | `src/dd_agents/models/` | Finding, coverage manifest, quality score, audit entry models |

### 2.2 Changes (Architectural)

| Skill Pattern | SDK Pattern | Why |
|--------------|------------|-----|
| LLM reads SKILL.md and decides flow | Python state machine drives 35 steps | Deterministic enforcement |
| "MUST" in markdown = advisory | `if/else` in Python = mandatory | Programmatic control |
| Agent reads skill file for rules | Agent receives rules in prompt (Python assembled) | Agents cannot read skill files |
| TeamCreate / TaskCreate for coordination | `asyncio.gather()` for parallel, `await` for sequential | Direct control |
| SendMessage for inter-agent communication | Python collects agent output, passes to next agent | Orchestrator mediates |
| LLM counts files for coverage check | Python counts files, blocks agent stop if incomplete | PreToolUse + Stop hooks |
| LLM writes audit.json at the end | Python generates audit.json from collected validation results | Deterministic QA |
| Agent decides to re-spawn on failure | Python catches exception, re-spawns automatically | Error recovery engine |

---

## 3. Phase 1: Foundation (No Skill Changes)

**Goal**: Build the data layer and deterministic components. No SDK dependency yet. Pure Python + Pydantic.

### Step 1: Project Setup

```bash
# Create project structure
mkdir -p src/dd_agents/{models,entity_resolution,extraction,utils,config}
mkdir -p tests/{unit,integration,e2e,fixtures}

# Initialize pyproject.toml with dependencies:
# - pydantic>=2.0
# - openpyxl
# - networkx
# - rapidfuzz
# - click
```

**Acceptance**: `pip install -e .` succeeds. `python -c "import dd_agents"` succeeds.

### Step 2: Pydantic Models

Port all data structures from `deal-config.schema.json`, `domain-definitions.md`, and `dd-framework/schemas/`:

- `src/dd_agents/models/config.py` -- DealConfig (buyer, target, deal, judge, execution, reporting, entity_aliases, source_of_truth)
- `src/dd_agents/models/finding.py` -- Finding, Citation, Gap, FileHeader
- `src/dd_agents/models/coverage.py` -- CoverageManifest, FileCoverage
- `src/dd_agents/models/quality.py` -- QualityScore, SpotCheck, Contradiction
- `src/dd_agents/models/audit.py` -- AuditEntry, ConsolidatedAudit
- `src/dd_agents/models/inventory.py` -- CustomerEntry, CountsJson, ReferenceFile, CustomerMention, EntityMatch
- `src/dd_agents/models/classification.py` -- CustomerClassification (NEW, CHANGED, STALE_REFRESH, UNCHANGED, DELETED)
- `src/dd_agents/models/report.py` -- NumericalManifest, ReportDiff

Source: SKILL.md sections 0c-0e, 2a-2c, domain-definitions.md, all dd-framework schemas.

**Acceptance**: `pytest tests/unit/test_models.py` passes. All models validate sample data. All models reject invalid data.

### Step 3: Entity Resolution Module

Port the 6-pass cascading matcher from `entity-resolution-protocol.md`:

- `src/dd_agents/entity_resolution/matcher.py` -- EntityMatcher class with 6 passes
- `src/dd_agents/entity_resolution/cache.py` -- Cache load/save with corruption detection
- `src/dd_agents/entity_resolution/normalization.py` -- Name normalization (strip legal suffixes, special chars)

Source: `references/entity-resolution-protocol.md`, SKILL.md section 1d.

**Acceptance**: `pytest tests/unit/test_entity_resolution.py` passes. All 6 passes tested with edge cases.

### Step 4: Extraction Pipeline

Port the fallback chain from SKILL.md section 1b:

- `src/dd_agents/extraction/pipeline.py` -- ExtractionPipeline (markitdown -> pdftotext -> Read -> tesseract)
- `src/dd_agents/extraction/checksum.py` -- SHA-256 computation and cache
- `src/dd_agents/extraction/quality.py` -- ExtractionQuality model and writer

Source: SKILL.md section 1b, 1c.

**Acceptance**: `pytest tests/unit/test_extraction.py` passes. Fallback chain tested. Checksum cache tested.

### Step 5: Unit Tests for Phase 1

Write comprehensive unit tests for all Phase 1 modules. Target: 80+ tests.

**Acceptance**: `pytest tests/unit/ -v` passes. `mypy src/ --strict` passes. `ruff check src/` clean.

---

## 4. Phase 2: Core Pipeline (No Skill Changes)

**Goal**: Build the pipeline infrastructure. Adds `claude-agent-sdk` dependency.

### Step 6: Pipeline State Machine

Implement the 35-step pipeline as an async state machine:

- `src/dd_agents/orchestrator/state.py` -- PipelineState dataclass
- `src/dd_agents/orchestrator/engine.py` -- PipelineEngine with `run_step(n)` and `run_steps(start, end)`
- `src/dd_agents/orchestrator/checkpoints.py` -- Checkpoint save/load for resume

Source: SKILL.md section 10 (all 35 steps).

**Acceptance**: Pipeline engine can execute steps 1-12 (pre-agent steps) on the sample data room. Checkpoint save/load round-trips correctly.

### Step 7: Persistence Tier Management

Implement the three-tier model:

- `src/dd_agents/persistence/tiers.py` -- PERMANENT, VERSIONED, FRESH tier management
- `src/dd_agents/persistence/run_manager.py` -- Run initialization (mkdir, snapshot prior inventory, wipe FRESH)
- `src/dd_agents/persistence/shared_files.py` -- read-validate-write for shared PERMANENT files
- `src/dd_agents/persistence/incremental.py` -- Customer classification algorithm (NEW/CHANGED/STALE_REFRESH/UNCHANGED/DELETED)

Source: SKILL.md section 0c, 0e.

**Acceptance**: Run initialization creates correct directory structure. FRESH tier wipe preserves PERMANENT and VERSIONED. Incremental classification produces correct results on sample data.

### Step 8: Inventory Building

Implement file discovery and customer registry:

- `src/dd_agents/inventory/discovery.py` -- File discovery (tree.txt, files.txt, file_types.txt)
- `src/dd_agents/inventory/customers.py` -- Customer registry (customers.csv, counts.json)
- `src/dd_agents/inventory/references.py` -- Reference file registry (reference_files.json)
- `src/dd_agents/inventory/mentions.py` -- Customer-mention index (customer_mentions.json)

Source: SKILL.md sections 1a, 2a-2d.

**Acceptance**: Inventory building on sample data room produces correct customers.csv, counts.json, reference_files.json.

### Step 9: Hooks

Implement SDK hooks for deterministic enforcement:

- `src/dd_agents/hooks/path_guard.py` -- PreToolUse: block access outside project directory
- `src/dd_agents/hooks/bash_guard.py` -- PreToolUse: block dangerous bash commands
- `src/dd_agents/hooks/output_validator.py` -- PostToolUse: validate JSON output on Write
- `src/dd_agents/hooks/stop_hook.py` -- Stop: block premature agent stop (customer count check)

Source: `01-architecture-decisions.md` ADR-01, SKILL.md section 7 (error recovery).

**Acceptance**: `pytest tests/unit/test_hooks.py` passes. Path guard blocks traversal. Stop hook blocks premature stop.

### Step 10: Custom MCP Tools

Implement tools agents can call:

- `src/dd_agents/tools/server.py` -- MCP server factory (project-scoped)
- `src/dd_agents/tools/validate_finding.py` -- Validate finding against schema
- `src/dd_agents/tools/resolve_entity.py` -- Entity resolution lookup
- `src/dd_agents/tools/check_governance.py` -- Governance graph validation
- `src/dd_agents/tools/get_customer_list.py` -- Return customer list for current deal
- `src/dd_agents/tools/report_progress.py` -- Agent progress reporting

Source: `02-system-architecture.md` (MCP tool server diagram).

**Acceptance**: Tools registered with `create_sdk_mcp_server`. Each tool returns expected output for sample inputs.

### Step 11: Integration Tests for Phase 2

Write integration tests for pipeline steps 1-12, hooks, and tools.

**Acceptance**: `pytest tests/integration/ -v` passes.

---

## 5. Phase 3: Agents (Skill Used as Reference)

**Goal**: Build the agent spawning and management layer. The skill files are read as reference for prompt content but are not modified.

### Step 12: Prompt Assembly Engine

Build the prompt builder that assembles complete agent prompts from components:

- `src/dd_agents/agents/prompt_builder.py` -- PromptBuilder class
  - Combines: deal context + customer list (with safe names) + file paths + reference file content + extraction rules + governance rules + gap detection rules + cross-reference rules
  - Prompt size estimation (token counting)
  - Automatic customer batching if prompt exceeds 80,000 tokens

Source: SKILL.md section 10 step 14 (prompt preparation), `agent-prompts.md`.

**Acceptance**: PromptBuilder produces prompts that include all required sections. Token estimation matches manual count within 10%.

### Step 13: Specialist Agent Spawning

Implement parallel specialist spawning:

- `src/dd_agents/agents/specialists.py` -- spawn_specialists() with asyncio.gather()
- `src/dd_agents/agents/base.py` -- Base agent configuration (model, budget, tools, hooks)

Source: SKILL.md section 3b, 10 step 16.

**Acceptance**: 4 specialists spawn in parallel. Each receives correct prompt. Results are collected.

### Step 14: Coverage Gate

Implement step 17 validation:

- `src/dd_agents/orchestrator/coverage.py` -- Coverage gate with aggregate detection, silent context exhaustion detection, re-spawn for missing customers

Source: SKILL.md section 10 step 17, section 7 (Scenarios 2, 7, 8, 15).

**Acceptance**: Coverage gate correctly identifies missing customers. Re-spawn produces output for missing customers. Aggregate files detected and handled.

### Step 15: Judge Agent

Implement the Judge with iteration loop:

- `src/dd_agents/agents/judge.py` -- spawn_judge() with quality threshold check and iteration

Source: SKILL.md section 10 steps 19-22, `agent-prompts.md` section 6.

**Acceptance**: Judge produces quality_scores.json. Below-threshold scores trigger re-spawn. Force finalization with caveats after max iterations.

### Step 16: Reporting Lead Agent

Implement the Reporting Lead:

- `src/dd_agents/agents/reporting_lead.py` -- spawn_reporting_lead() with checkpoint support

Source: SKILL.md section 6, section 10 steps 23-31.

**Acceptance**: Reporting Lead produces merged findings, gap merge, numerical manifest, Excel report.

### Step 17: Agent Integration Tests

Test agent spawning with the small sample data room (5 customers, 15 files).

**Acceptance**: Full agent cycle (spawn 4 specialists, coverage gate, Judge, Reporting Lead) completes on sample data room.

---

## 6. Phase 4: Reporting and Validation (Skill Used as Reference)

**Goal**: Complete the reporting pipeline and QA validation.

### Step 18: Merge/Dedup Engine

- `src/dd_agents/reporting/merge.py` -- Per-customer merge from 4 agents with deduplication

Source: `reporting-protocol.md` section 1.

### Step 19: Numerical Validation

- `src/dd_agents/validation/numerical_audit.py` -- 6-layer validation framework
- `src/dd_agents/validation/numerical_manifest.py` -- Manifest builder

Source: `numerical-validation.md`.

### Step 20: Excel Generation

- `src/dd_agents/reporting/excel.py` -- Generate 14-sheet Excel from report_schema.json
- `src/dd_agents/reporting/schema.py` -- Load and interpret report_schema.json

Source: `reporting-protocol.md` sections 2-3.

### Step 21: Report Diff

- `src/dd_agents/reporting/diff.py` -- Compare current run vs prior run

Source: `reporting-protocol.md` section 4.

### Step 22: Full QA Audit

- `src/dd_agents/validation/qa_audit.py` -- All 31 DoD checks (SKILL.md section 9)
- `src/dd_agents/validation/dod.py` -- Definition of Done checker
- `src/dd_agents/validation/schema_validator.py` -- Post-generation schema validation

Source: SKILL.md sections 8, 9.

### Step 23: Reference Data Room Validation

Run the SDK on the same reference data room that the skill processed. Compare outputs.

**Acceptance criteria for Phase 4**:
- Same customers identified (count match)
- Same files covered (count match)
- Finding counts within 15% per customer (for a customer with 20 findings in the Skill run, the SDK run should produce 17-23 findings; this accounts for LLM non-determinism). Structural metrics (customer count, file count, sheet count) must match exactly.
- All 31 DoD checks pass
- Excel report has all 14 sheets
- No P0 findings missed that the skill found
- Severity distribution roughly matches (not exact -- different runs will vary)

---

## 7. Phase 5: Polish

**Goal**: Complete the production-ready package.

### Step 24: CLI Interface

- `src/dd_agents/cli.py` -- Click-based CLI: `dd-agents run`, `dd-agents status`, `dd-agents new-deal`, `dd-agents list-deals`, `dd-agents export`, `dd-agents validate`

### Step 25: Error Recovery

- `src/dd_agents/orchestrator/recovery.py` -- All 15 error scenarios from `12-error-recovery.md`
- `src/dd_agents/errors.py` -- Error taxonomy

### Step 26: Incremental Mode

- End-to-end incremental mode with customer classification, carry-forward, and merge

### Step 27: ChromaDB Integration (Optional)

- `src/dd_agents/vector_store/` -- Optional ChromaDB integration per `14-vector-store.md`

### Step 28: Documentation

- README.md with installation, quickstart, configuration
- API documentation (auto-generated from docstrings)

### Step 29: Docker Packaging

- Dockerfile, docker-compose.yml per `15-testing-deployment.md`

---

## 8. Migration Phase Dependencies

Phase durations depend on team size and familiarity with the codebase. Instead of time estimates, use the dependency graph: Phase 1 must complete before Phase 2 can start. Phases within Phase 2 can be parallelized. See `18-implementation-order.md` for the detailed dependency graph.

| Phase | Dependency | Validation Gate |
|-------|------------|-----------------|
| Phase 1: Foundation | None | Unit tests pass, `mypy --strict` clean |
| Phase 2: Core Pipeline | Phase 1 | Integration tests pass (steps 1-12 on sample data room) |
| Phase 3: Agents | Phase 2 | Full agent cycle completes on sample data room |
| Phase 4: Reporting + Validation | Phase 3 | Reference data room comparison validated |
| Phase 5: Polish | Phase 4 | CLI, Docker, documentation complete |

---

## 9. Rollback Plan

If the SDK migration encounters blocking issues:

1. The existing skill remains unchanged and fully functional throughout all phases.
2. Phase 1-2 code (models, entity resolution, extraction, pipeline) can be used as standalone libraries even if the agent layer is not complete.
3. Partial adoption is possible: use the SDK for deterministic steps (extraction, validation, reporting) while keeping the skill for agent orchestration.

---

## 10. Post-Migration Skill Deprecation

After Phase 4 validation succeeds:

1. Add a deprecation notice to SKILL.md: "This skill has been superseded by the dd-agents SDK. Use `dd-agents run` instead."
2. Keep the skill files for 3 months as reference.
3. Archive the skill directory after the retention period.
4. The skill's reference files (`domain-definitions.md`, `entity-resolution-protocol.md`, etc.) may remain as documentation even after the skill is deprecated -- their content is now encoded in the SDK but the prose is useful for onboarding.

**Skill end-of-life**: After Phase 5 (production validation), the Skill files (`~/.claude/skills/forensic-dd/`) are archived to `_index/legacy_skill/` and removed from the active skills directory. The SDK application becomes the sole execution path. A rollback procedure is documented: restore Skill files from archive and disable the SDK application in deal-config.json.
