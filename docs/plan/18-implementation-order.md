# 18 — Implementation Order (Phased Build Plan)

## Overview

This document defines the phased build plan with explicit dependency ordering. Each phase builds on the previous one. Within each phase, modules can be built in parallel where dependencies allow. The critical path determines the minimum time to production.

Cross-reference: `03-project-structure.md` (file layout), `16-migration.md` (migration phases), `15-testing-deployment.md` (testing at each phase).

---

## 1. Phase Diagram

```
Phase 1: Foundation ─────────────────────────────────────────────────────────
  (no external deps except pydantic, rapidfuzz, networkx, openpyxl)

    models/*                 All Pydantic data models
    ├── config.py            DealConfig, Buyer, Target, Deal, JudgeConfig, ExecutionConfig
    ├── finding.py           Finding, Citation, Gap, FileHeader
    ├── coverage.py          CoverageManifest, FileCoverage
    ├── quality.py           QualityScore, SpotCheck, Contradiction
    ├── audit.py             AuditEntry, ConsolidatedAudit
    ├── inventory.py         CustomerEntry, CountsJson, ReferenceFile, EntityMatch
    ├── classification.py    CustomerClassification (incremental mode)
    └── report.py            NumericalManifest, ReportDiff

    entity_resolution/*      6-pass cascading matcher + cache
    ├── matcher.py           EntityMatcher (6 passes)
    ├── normalization.py     Name normalization, legal suffix stripping
    └── cache.py             Cache load/save with corruption handling

    extraction/*             Document extraction pipeline
    ├── pipeline.py          Fallback chain (markitdown → pdftotext → read → tesseract)
    ├── checksum.py          SHA-256 computation, cache check
    ├── quality.py           ExtractionQuality model, extraction_quality.json writer
    ├── tabular.py           Smart Excel extraction (22-llm-robustness.md §7)
    └── chunking.py          Clause-aware chunking for vector store (22-llm-robustness.md §2)

    utils/*                  Shared utilities
    ├── naming.py            customer_safe_name convention
    └── constants.py         Shared constants (tier names, agent names, etc.)

    config/
    └── deal-config.template.json


Phase 2: Infrastructure ─────────────────────────────────────────────────────
  (adds claude-agent-sdk dependency)

    persistence/*            Three-tier persistence model
    ├── tiers.py             PERMANENT, VERSIONED, FRESH tier management
    ├── run_manager.py       Run initialization (mkdir, snapshot, wipe FRESH)
    ├── shared_files.py      read-validate-write for concurrency safety
    └── incremental.py       Customer classification algorithm

    inventory/*              File discovery + customer registry
    ├── discovery.py         tree.txt, files.txt, file_types.txt
    ├── customers.py         customers.csv, counts.json
    ├── references.py        reference_files.json
    └── mentions.py          customer_mentions.json (using entity resolution)

    hooks/*                  SDK hooks for deterministic enforcement
    ├── path_guard.py        PreToolUse: block outside project directory
    ├── bash_guard.py        PreToolUse: block dangerous bash commands
    ├── output_validator.py  PostToolUse: validate JSON on Write
    └── stop_hook.py         Stop: block premature agent stop

    tools/*                  Custom MCP tools for agents
    ├── server.py            MCP server factory (project-scoped)
    ├── validate_finding.py  Validate finding against schema
    ├── resolve_entity.py    Entity resolution lookup
    ├── check_governance.py  Governance graph validation
    ├── get_customer_list.py Return customer list
    └── report_progress.py   Agent progress reporting

    orchestrator/
    └── state.py             PipelineState dataclass

    models/
    └── ontology.py          ContractNode, ContractRelationship, ContractOntology (21-ontology-and-reasoning.md §2)

    reasoning/*              Graph-based reasoning (21-ontology-and-reasoning.md)
    ├── contract_graph.py    ContractReasoningGraph using NetworkX (21-ontology-and-reasoning.md §3)
    └── verification.py      Hallucination prevention verification protocol (21-ontology-and-reasoning.md §10)


Phase 3: Pipeline Engine ────────────────────────────────────────────────────
  (wires infrastructure into executable pipeline)

    orchestrator/
    ├── engine.py            35-step state machine (run_step, run_steps)
    ├── team.py              Agent lifecycle management (spawn, monitor, collect)
    └── checkpoints.py       Checkpoint save/load for resume-after-failure

    agents/
    └── base.py              Base agent config (model, budget, tools, hooks)

    errors.py                Error taxonomy (AgentError, PipelineError, ErrorRecord)


Phase 4: Agent Implementation ──────────────────────────────────────────────
  (the LLM-facing layer)

    agents/
    ├── prompt_builder.py    Prompt assembly engine (deal context + customers + rules)
    ├── specialists.py       Specialist spawning (4 agents in parallel)
    ├── judge.py             Judge agent with iteration loop
    └── reporting_lead.py    Reporting Lead with checkpoint support

    orchestrator/
    ├── coverage.py          Step 17 coverage gate (aggregate detection, re-spawn)
    └── recovery.py          Error recovery manager (all 15 scenarios)


Phase 5: Reporting + Validation ────────────────────────────────────────────
  (post-agent processing)

    reporting/*              Report generation
    ├── merge.py             Per-customer merge + deduplication
    ├── diff.py              Report diff (current vs prior run)
    ├── excel.py             14-sheet Excel from report_schema.json
    ├── schema.py            Load and interpret report_schema.json
    └── contract_dates.py    Contract date reconciliation

    validation/*             QA and validation gates
    ├── coverage.py          File coverage audit
    ├── numerical_audit.py   5-layer numerical validation
    ├── qa_audit.py          Full QA audit (30 DoD checks)
    ├── dod.py               Definition of Done checker
    └── schema_validator.py  Post-generation schema validation


Phase 6: Integration ───────────────────────────────────────────────────────
  (user-facing layer + optional features)

    cli.py                   Click-based CLI interface
    core/
    └── project.py           Project management (new-deal, list, archive)

    vector_store/*           Optional ChromaDB integration
    ├── client.py            VectorStore wrapper
    ├── chunker.py           Document chunking
    └── __init__.py          Conditional import

    Full E2E testing + reference data room comparison
```

---

## 2. Dependency Graph

```
                    ┌─────────────────────────────────────────────────────┐
                    │                     models/*                         │
                    │  (config, finding, coverage, quality, audit,         │
                    │   inventory, classification, report)                 │
                    └──────────┬──────────┬──────────┬───────────────────┘
                               │          │          │
              ┌────────────────┤          │          ├────────────────────┐
              │                │          │          │                    │
              ▼                ▼          ▼          ▼                    │
    ┌──────────────┐ ┌───────────────┐ ┌──────────────┐                 │
    │   utils/*    │ │entity_        │ │ extraction/* │                 │
    │ naming.py    │ │resolution/*   │ │ pipeline.py  │                 │
    │ constants.py │ │ matcher.py    │ │ checksum.py  │                 │
    └──────┬───────┘ │ cache.py      │ │ quality.py   │                 │
           │         │ normalization │ └──────┬───────┘                 │
           │         └──────┬────────┘        │                         │
           │                │                 │                         │
           │    ┌───────────┼─────────────────┼─────────────────┐      │
           │    │           │                 │                 │      │
           ▼    ▼           ▼                 ▼                 ▼      │
    ┌─────────────────────────────────────────────────────────────┐    │
    │                    persistence/*                             │    │
    │  tiers.py, run_manager.py, shared_files.py, incremental.py  │    │
    └─────────────────────────┬───────────────────────────────────┘    │
                              │                                        │
           ┌──────────────────┼──────────────────┐                    │
           │                  │                  │                    │
           ▼                  ▼                  ▼                    │
    ┌──────────────┐ ┌──────────────┐ ┌────────────────┐             │
    │ inventory/*  │ │   hooks/*    │ │   tools/*      │             │
    │ discovery    │ │ path_guard   │ │ server.py      │             │
    │ customers    │ │ bash_guard   │ │ validate_find. │             │
    │ references   │ │ output_val.  │ │ resolve_entity │             │
    │ mentions     │ │ stop_hook    │ │ check_govern.  │             │
    └──────┬───────┘ └──────┬───────┘ └───────┬────────┘             │
           │                │                 │                      │
           └────────────────┼─────────────────┘                      │
                            │                                        │
                            ▼                                        │
    ┌─────────────────────────────────────────────────────────────┐  │
    │                  orchestrator/*                               │  │
    │  state.py ─── engine.py ─── team.py ─── checkpoints.py      │  │
    └─────────────────────────┬───────────────────────────────────┘  │
                              │                                      │
                              ▼                                      │
    ┌─────────────────────────────────────────────────────────────┐  │
    │                     agents/*                                 │  │
    │  base.py ─── prompt_builder.py ─── specialists.py            │  │
    │              judge.py ─── reporting_lead.py                  │  │
    ├─────────────────────────────────────────────────────────────┤  │
    │  orchestrator/coverage.py + orchestrator/recovery.py        │  │
    │  errors.py                                                   │  │
    └─────────────────────────┬───────────────────────────────────┘  │
                              │                                      │
                              ▼                                      │
    ┌─────────────────────────────────────────────────────────────┐  │
    │                  validation/* + reporting/*                   │◄─┘
    │  coverage.py, numerical_audit.py, qa_audit.py, dod.py, schema_val.py   │
    │  merge.py, diff.py, excel.py, schema.py, contract_dates.py │
    └─────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                     cli.py + project.py                      │
    │                     vector_store/* (optional)                │
    └─────────────────────────────────────────────────────────────┘
```

---

## 3. Critical Path

The critical path determines the minimum time to a working pipeline. Everything on this path must be done sequentially. Everything off this path can be parallelized.

```
models ──► entity_resolution ──► extraction ──► inventory ──►
persistence ──► orchestrator/state ──► orchestrator/engine ──►
agents/base ──► agents/prompt_builder ──► agents/specialists ──►
orchestrator/coverage ──► agents/judge ──► agents/reporting_lead ──►
validation/* ──► reporting/* ──► cli
```

Each module on the critical path is considered complete when its unit tests pass AND it integrates with the previous module (import + basic functional test). See Phase deliverables table for specific acceptance criteria per module.

### Off Critical Path (Can Be Parallelized)

These modules can be built concurrently with the critical path:

| Module | Can Start After | Independent Of |
|--------|----------------|---------------|
| `hooks/*` | `models` | Everything except `orchestrator/pipeline` |
| `tools/*` | `models` + `entity_resolution` | Everything except `orchestrator/pipeline` |
| `errors.py` | `models` | Everything except `orchestrator/recovery` |
| `persistence/incremental.py` | `persistence/tiers.py` | Agents |
| `reporting/diff.py` | `reporting/merge.py` | Agents |
| `reporting/contract_dates.py` | `models` | Most of pipeline |
| `vector_store/*` | `extraction` | Entire pipeline (optional) |
| `core/project.py` | `models` | Entire pipeline |

**Note**: While hooks and tools are off the critical path for code completion, they are required for integration testing. Plan to complete `hooks/*` and `tools/*` before starting Phase 3 integration tests.

---

## 4. Per-Phase Deliverables and Acceptance Criteria

### Phase 1: Foundation

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| Pydantic models | `src/dd_agents/models/*.py` | `pytest tests/unit/test_models.py` passes |
| Entity resolution | `src/dd_agents/entity_resolution/*.py` | `pytest tests/unit/test_entity_resolution.py` passes |
| Extraction pipeline | `src/dd_agents/extraction/*.py` | `pytest tests/unit/test_extraction.py` passes |
| Safe name utility | `src/dd_agents/utils/naming.py` | `pytest tests/unit/test_safe_name.py` passes |
| Type checking | All `src/` files | `mypy src/ --strict` passes |
| Lint | All files | `ruff check src/ tests/` clean |

### Phase 2: Infrastructure

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| Persistence tiers | `src/dd_agents/persistence/*.py` | Run init creates correct dirs. FRESH wipe preserves PERMANENT. |
| Inventory building | `src/dd_agents/inventory/*.py` | customers.csv, counts.json correct for sample data room |
| Hooks | `src/dd_agents/hooks/*.py` | `pytest tests/unit/test_hooks.py` passes |
| MCP tools | `src/dd_agents/tools/*.py` | Tools return expected output for sample inputs |
| Pipeline state | `src/dd_agents/orchestrator/state.py` | State serializes and deserializes correctly |
| Integration tests | `tests/integration/test_pipeline.py` | Steps 1-12 pass on sample data room |

### Phase 3: Pipeline Engine

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| Pipeline engine | `src/dd_agents/orchestrator/engine.py` | All 35 steps registered and callable |
| Agent manager | `src/dd_agents/orchestrator/team.py` | Agent lifecycle (spawn, monitor, collect) works |
| Checkpoints | `src/dd_agents/orchestrator/checkpoints.py` | Save at step N, resume from step N+1 |
| Error taxonomy | `src/dd_agents/errors.py` | All error types instantiable and serializable |

### Phase 4: Agent Implementation

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| Prompt builder | `src/dd_agents/agents/prompt_builder.py` | Prompts include all required sections |
| Specialist spawning | `src/dd_agents/agents/specialists.py` | 4 agents spawn and produce output |
| Coverage gate | `src/dd_agents/orchestrator/coverage.py` | Missing customers detected and re-spawned |
| Judge | `src/dd_agents/agents/judge.py` | Quality scores produced, iteration works |
| Reporting Lead | `src/dd_agents/agents/reporting_lead.py` | Excel report generated |
| Error recovery | `src/dd_agents/orchestrator/recovery.py` | All 15 scenarios handled |
| E2E test | `tests/e2e/test_full_run.py` | Full pipeline on sample data room succeeds |

### Phase 5: Reporting + Validation

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| Merge/dedup | `src/dd_agents/reporting/merge.py` | Correct merge from 4 agents per customer |
| Numerical validation | `src/dd_agents/validation/numerical_audit.py` | 5 layers validate correctly |
| QA audit | `src/dd_agents/validation/qa_audit.py` | All 30 DoD checks pass on valid data |
| Excel generation | `src/dd_agents/reporting/excel.py` | 14-sheet Excel matches report_schema.json |
| Report diff | `src/dd_agents/reporting/diff.py` | Diff detects changes between runs |
| Production comparison | N/A | Reference data room output matches within tolerance |

### Phase 6: Integration

| Deliverable | Files | Acceptance |
|-------------|-------|------------|
| CLI | `src/dd_agents/cli.py` | All commands work: run, status, new-deal, list, export |
| Project management | `src/dd_agents/core/project.py` | Multi-deal lifecycle correct |
| ChromaDB (optional) | `src/dd_agents/vector_store/*.py` | semantic_search tool returns results when enabled |
| Docker | `Dockerfile`, `docker-compose.yml` | `docker build` and `docker run` succeed |

---

## 5. Module Size Estimates

Approximate lines of code per module (excluding tests):

| Module | Estimated LoC | Complexity |
|--------|--------------|------------|
| `models/*` | 600 | Low (Pydantic declarations) |
| `entity_resolution/*` | 400 | Medium (6-pass logic) |
| `extraction/*` | 800 | Medium (subprocess management, smart Excel via tabular.py, clause-aware chunking via chunking.py) |
| `persistence/*` | 350 | Low-Medium |
| `inventory/*` | 400 | Medium (file parsing) |
| `hooks/*` | 200 | Low |
| `tools/*` | 300 | Low-Medium |
| `orchestrator/*` | 800 | High (state machine, coverage gate) |
| `agents/*` | 600 | High (prompt assembly, retry logic) |
| `reporting/*` | 700 | High (merge logic, Excel generation) |
| `validation/*` | 500 | High (30 DoD checks, 5-layer numerical) |
| `reasoning/*` | 250 | Medium (NetworkX graph queries, verification tiers) |
| `errors.py` | 100 | Low |
| `cli.py` | 200 | Low |
| `vector_store/*` | 250 | Medium |
| **Total** | **~6,450** | |

For context: the existing skill is 3,100+ lines across 9 files. The SDK version is larger because it includes enforcement logic (hooks, validation gates, error recovery) that was previously expressed as advisory prose.

---

## 6. Build Order Checklist

Use this checklist to track progress. Each item is a discrete, testable unit.

```
Phase 1: Foundation
  [ ] pyproject.toml + project structure
  [ ] models/config.py (DealConfig)
  [ ] models/finding.py (Finding, Citation, Gap)
  [ ] models/coverage.py (CoverageManifest)
  [ ] models/quality.py (QualityScore, SpotCheck)
  [ ] models/audit.py (AuditEntry, ConsolidatedAudit)
  [ ] models/inventory.py (CustomerEntry, CountsJson, ReferenceFile)
  [ ] models/classification.py (CustomerClassification)
  [ ] models/report.py (NumericalManifest, ReportDiff)
  [ ] utils/naming.py (customer_safe_name)
  [ ] utils/constants.py
  [ ] entity_resolution/normalization.py
  [ ] entity_resolution/matcher.py (6 passes)
  [ ] entity_resolution/cache.py
  [ ] extraction/checksum.py
  [ ] extraction/quality.py
  [ ] extraction/pipeline.py (fallback chain)
  [ ] extraction/tabular.py (smart Excel extraction — 22-llm-robustness.md §7)
  [ ] extraction/chunking.py (clause-aware chunking for vector store — 22-llm-robustness.md §2)
  [ ] config/deal-config.template.json
  [ ] Unit tests: models, entity resolution, safe name, extraction, tabular, chunking
  [ ] mypy --strict passes
  [ ] ruff clean

Phase 2: Infrastructure
  [ ] persistence/tiers.py
  [ ] persistence/run_manager.py
  [ ] persistence/shared_files.py
  [ ] persistence/incremental.py
  [ ] inventory/discovery.py
  [ ] inventory/customers.py
  [ ] inventory/references.py
  [ ] inventory/mentions.py
  [ ] hooks/path_guard.py
  [ ] hooks/bash_guard.py
  [ ] hooks/output_validator.py
  [ ] hooks/stop_hook.py
  [ ] tools/server.py
  [ ] tools/validate_finding.py
  [ ] tools/resolve_entity.py
  [ ] tools/check_governance.py
  [ ] tools/get_customer_list.py
  [ ] tools/report_progress.py
  [ ] orchestrator/state.py
  [ ] models/ontology.py (contract ontology — 21-ontology-and-reasoning.md §2)
  [ ] reasoning/contract_graph.py (graph-based reasoning — 21-ontology-and-reasoning.md §3)
  [ ] reasoning/verification.py (verification protocol — 21-ontology-and-reasoning.md §10)
  [ ] Integration tests: steps 1-12, hooks, tools

Phase 3: Pipeline Engine
  [ ] orchestrator/engine.py (35 steps)
  [ ] orchestrator/team.py (agent lifecycle)
  [ ] orchestrator/checkpoints.py
  [ ] agents/base.py
  [ ] errors.py

Phase 4: Agent Implementation
  [ ] agents/prompt_builder.py (prompt builder)
  [ ] agents/specialists.py (parallel spawn)
  [ ] orchestrator/coverage.py (step 17 gate)
  [ ] orchestrator/recovery.py (15 error scenarios)
  [ ] agents/judge.py (iteration loop)
  [ ] agents/reporting_lead.py (with checkpoints)
  [ ] E2E test: full run on sample data room

Phase 5: Reporting + Validation
  [ ] reporting/merge.py
  [ ] reporting/diff.py
  [ ] reporting/excel.py
  [ ] reporting/schema.py
  [ ] reporting/contract_dates.py
  [ ] validation/coverage.py
  [ ] validation/numerical_audit.py
  [ ] validation/qa_audit.py (30 DoD checks)
  [ ] validation/dod.py
  [ ] validation/schema_validator.py
  [ ] Reference data room comparison test

Phase 6: Integration
  [ ] cli.py
  [ ] core/project.py
  [ ] vector_store/client.py (optional)
  [ ] vector_store/chunker.py (optional)
  [ ] Dockerfile
  [ ] docker-compose.yml
  [ ] Final E2E suite
```
