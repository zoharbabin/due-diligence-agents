# 01 -- Architecture Decision Records

Six ADRs defining the foundational technical choices for the Due Diligence Agent SDK.

---

## ADR-01: Claude Agent SDK Over Claude Code Skills

**Status**: Accepted

**Context**: The existing forensic-dd system is a Claude Code Skill -- 3,102 lines of markdown instructions executed by Claude Code at runtime. The LLM controls the entire execution flow: it decides when to proceed between steps, when to retry, and how to validate. In a production retrospective (a real M&A deal, ~200 customers), all 17 quality failures were instruction-following failures:

- Agents skipped customers (produced 28 of 34 expected outputs)
- Agents produced aggregate files (`_global.json`, `batch_summary.json`) instead of per-customer output
- Agents fabricated citations (exact_quote not found in source document)
- Agents missed gap detection (no gap files despite missing referenced documents)
- Agents generated incorrect numerical counts (total_findings did not match sum of per-severity counts)
- The orchestrating LLM skipped blocking gates ("MUST" in markdown is advisory, not enforced)

This is the **enforcement paradox** (i.e., the retrospective finding that all 17 quality failures in production were instruction-following failures where the LLM ignored prose-based "MUST"/"BLOCKING" constraints — the LLM that must follow the rules is also the entity that decides whether to follow them). Markdown emphasis ("MUST", "BLOCKING", "CRITICAL") has zero enforcement power.

**Decision**: Migrate to `claude-agent-sdk` v0.1.39+ as a standalone Python application. The SDK wraps the Claude Code CLI as a subprocess, providing programmatic control over agent lifecycle while preserving Claude Code's full tool ecosystem (Read, Write, Edit, Bash, Glob, Grep, WebFetch).

> **Version enforcement**: `pyproject.toml` pins `claude-agent-sdk >= 0.1.39`. The orchestrator validates the installed SDK version at startup and raises `RuntimeError` if the minimum version is not met. This prevents silent behavioral regressions from older SDK builds.

**Rationale**:

1. **Control inversion**: Python is the orchestrator, agents are workers. The 35-step pipeline is a Python state machine. Agents cannot skip steps because they do not control the flow.
2. **Deterministic enforcement**: Validation gates are `if/else` in Python, not "MUST" in markdown. Coverage verification counts files on disk. Schema validation uses Pydantic. Numerical audit re-derives values from source files.
3. **Hook-enforced boundaries**: PreToolUse hooks block dangerous operations programmatically. Stop hooks prevent agents from finishing before processing all customers. PostToolUse hooks validate output after every write.
4. **Focused prompts**: Each agent receives a bounded prompt (< 80K tokens) with only its relevant rules, instead of the full 3,102-line specification. This is well within reliable instruction-following range.
5. **Programmatic retry**: When an agent fails or produces incomplete output, the orchestrator re-spawns automatically with the missing subset. No manual intervention.
6. **Cost controls**: `max_budget_usd` per agent prevents runaway API costs. `max_turns` bounds agent loop iterations.

**Consequences**:
- Requires Python 3.12+ runtime (the SDK supports 3.10+, but we target 3.12+ for modern syntax)
- Adds `claude-agent-sdk`, `pydantic`, `openpyxl`, `networkx`, `rapidfuzz`, `markitdown` as dependencies
- All dependencies must carry permissive open-source licenses (Apache 2.0, MIT, BSD). No commercial or subscription dependencies.
- Prompt engineering shifts from "complete specification in one context" to "focused instructions per agent"
- Debugging uses both Python logs and agent transcripts (stored at `~/.claude/projects/`)
- Same per-token API cost as the Skill approach -- the SDK does not add token overhead

**SDK API surface**:
```python
from claude_agent_sdk import (
    query, ClaudeSDKClient, ClaudeAgentOptions,
    AgentDefinition, HookMatcher,
    tool, create_sdk_mcp_server,
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
)
```

Key SDK constructs used:
- `query()` for one-shot agent invocations (specialists, Judge, Reporting Lead)
- `ClaudeAgentOptions` for per-agent configuration (tools, hooks, model, budget, cwd)
- `HookMatcher` for registering PreToolUse, PostToolUse, and Stop hooks
- `@tool` + `create_sdk_mcp_server()` for in-process custom MCP tools
- `ResultMessage` for capturing agent completion status, cost, and session ID
- `AgentDefinition` for subagent configuration (if using subagent delegation pattern)

---

## ADR-02: File-Based Storage with Three-Tier Persistence

**Status**: Accepted

**Context**: The system processes 200-500 documents across 50-200 customers. Total data volume is typically <100MB of extracted text and <50MB of JSON artifacts. Evaluated: SQLite, PostgreSQL, MongoDB, file-based JSON.

**Decision**: File-based JSON/JSONL storage using the three-tier persistence model from the existing skill. No database dependency.

**Three tiers**:

| Tier | Lifecycle | What it contains |
|------|-----------|------------------|
| **PERMANENT** | Never wiped across runs | `_dd/forensic-dd/index/text/*.md` (extracted documents), `checksums.sha256`, `extraction_quality.json`, `_dd/entity_resolution_cache.json` (shared), `_dd/forensic-dd/runs/` (all prior runs preserved), `_dd/run_history.json` (shared) |
| **VERSIONED** | Archived per run, never modified after completion | `_dd/forensic-dd/runs/{run_id}/findings/` (per-agent + merged), `audit/{agent}/audit_log.jsonl`, `audit.json`, `numerical_manifest.json`, `file_coverage.json`, `classification.json`, `contract_date_reconciliation.json`, `report_diff.json`, `judge/quality_scores.json`, `metadata.json`, `inventory_snapshot/` |
| **FRESH** | Wiped and rebuilt every run | `_dd/forensic-dd/inventory/` (tree.txt, files.txt, file_types.txt, customers.csv, counts.json, reference_files.json, customer_mentions.json, entity_matches.json), generated reports |

**Rationale**:
- At 400-document / 200-customer scale, file-based queries are fast (< 1 second for any aggregation)
- Agent outputs are naturally per-customer JSON files -- direct filesystem match
- Three-tier lifecycle maps cleanly to directory operations (mkdir, cp -r, rm -rf)
- No deployment dependency -- runs anywhere Python runs
- Agent tools (Read, Write, Glob, Grep) operate directly on the filesystem
- Audit trail is human-readable (JSONL files, not database rows)
- Each agent writes to its own isolated directory (`findings/{agent}/`), eliminating concurrent write conflicts

**Consequences**:
- Shared PERMANENT-tier files (`entity_resolution_cache.json`, `run_history.json`) use read-validate-write pattern for concurrent run safety
- No query language -- counting and aggregation done in Python (Pydantic models + list comprehensions)
- Backup is `cp -r _dd/ backup/`
- No migration tooling needed -- schema changes handled by Pydantic validators with defaults

---

## ADR-03: ChromaDB Optional, Not Required

**Status**: Accepted

**Context**: Cross-document semantic search can identify similar clauses across customers (e.g., "find all change-of-control clauses similar to this one"). Evaluated vector databases for this capability. Rejected `ruvector` (solo-developer project, 3 months old, critical bugs in SIMD inference and graph traversal). ChromaDB is mature and `pip install` simple.

**Decision**: ChromaDB is an optional enhancement. The system must function fully without it. Core analysis uses keyword search (Grep) and deterministic matching.

**When ChromaDB adds value**:
- Cross-document semantic search: "find clauses similar to this indemnification carve-out"
- Pattern detection across customers: identify non-standard clause variants
- Reference file lookup by semantic similarity when keyword matching is insufficient

**When ChromaDB is not needed** (and the system functions without it):
- Entity resolution: deterministic 6-pass cascading matcher (exact, alias, fuzzy, TF-IDF, parent-child)
- Gap detection: cross-reference, pattern-based, and checklist methods
- Governance graph resolution: explicit text matching for linkage phrases
- Cross-reference reconciliation: structured field comparison (ARR, dates, pricing)

**Implementation**: When `chromadb_enabled: true` in config, extracted text is chunked (clause-aware boundaries), embedded, and stored in a per-project ChromaDB collection during extraction. Agents receive a custom MCP tool `semantic_search` they can optionally call. The tool queries ChromaDB and returns relevant passages with source metadata.

**Consequences**:
- Zero additional dependency for the default configuration
- ChromaDB adds ~200MB to the install when enabled
- Semantic search results supplement but never override deterministic analysis

---

## ADR-04: NetworkX for Governance Graphs

**Status**: Accepted

**Context**: Each customer's contracts form a governance hierarchy. An MSA governs Order Forms, Amendments modify MSAs, SOWs reference MSAs, etc. The Legal agent builds this graph from explicit text linkages. The orchestrator needs to validate the graph (cycle detection, unreachable nodes, conflict identification) and the Reporting Lead needs to traverse it for the governance_resolved_pct metric.

At typical scale: 200 customers x ~3-5 governance edges each = ~600-1,000 edges total.

**Alternatives considered**:
- Neo4j: Full graph database. JVM dependency, server management, Cypher learning curve. Overkill for 1,000 edges.
- Custom adjacency-list JSON: Works for simple traversal but no built-in cycle detection, topological sort, or conflict analysis.
- NetworkX: Mature Python library, zero external dependencies (besides numpy), rich algorithm library.

**Decision**: Use NetworkX for all governance graph operations. Build the graph in-memory from agent-produced edge data. Serialize back to JSON for storage and reporting.

**Operations**:
- `nx.DiGraph()` -- build directed graph from `governance_graph.edges[]` in agent output
- `nx.find_cycle()` -- detect circular governance references (MSA -> Amendment -> MSA)
- `nx.topological_sort()` -- determine document precedence order
- `nx.ancestors(G, node)` -- find all governing documents for a given file
- `nx.descendants(G, node)` -- find all documents governed by a given MSA
- Isolate detection -- find documents with no governance link (unreachable nodes)
- Multi-parent detection -- find documents claimed by multiple governing docs (precedence conflicts)

**Consequences**:
- Graph validation is a deterministic Python function, not an LLM judgment
- Governance completeness audit is exact: `unreachable_nodes / total_nodes`
- Graph serialization to JSON for the Excel Governance sheet
- Adds ~10MB to install (NetworkX + numpy)

---

## ADR-05: Pydantic v2 for All Data Schemas

**Status**: Accepted

**Context**: The existing system defines 20+ JSON schemas as prose in markdown files (finding.schema.json format, gap schema, manifest schema, quality scores, etc.). Agents produce JSON that may or may not conform. Validation happens via LLM-based QA checks -- circular, because the LLM validates its own output using the same reasoning that produced the errors.

**Decision**: Define every JSON artifact as a Pydantic v2 model. Use `model_json_schema()` for SDK structured outputs. Use `model_validate()` for deterministic validation of all agent outputs.

**Models** (full definitions in `04-data-models.md`):

| Model | Source schema | Used by |
|-------|--------------|---------|
| `DealConfig` | deal-config.schema.json | Step 1 (config validation) |
| `Finding` | finding.schema.json | Agent output, merge, reporting |
| `Gap` | domain-definitions.md section 6d | Agent output, gap merge |
| `Citation` | finding.schema.json (nested) | Finding validation |
| `FileHeader` | domain-definitions.md section 1 | Agent output |
| `GovernanceEdge` | domain-definitions.md section 5b | Graph construction |
| `CustomerJSON` | agent-prompts.md section 4c | Per-customer agent output |
| `CoverageManifest` | coverage-manifest.schema.json | Step 17 coverage gate |
| `AuditEntry` | audit-entry.schema.json | Agent audit logs |
| `NumericalManifest` | numerical-validation.md section 1 | Step 27 numerical gate |
| `QualityScores` | quality-score.schema.json | Judge output |
| `SpotCheck` | quality-score.schema.json (nested) | Judge output |
| `Contradiction` | quality-score.schema.json (nested) | Judge output |
| `Classification` | SKILL.md section 0e | Incremental mode |
| `EntityCache` | entity-resolution-protocol.md section 7 | Entity resolution |
| `ReportDiff` | reporting-protocol.md section 4 | Run comparison |
| `ExtractionQuality` | SKILL.md section 1b | Extraction tracking |
| `RunMetadata` | SKILL.md step 3/32 | Per-run metadata |
| `RunHistory` | run-metadata.schema.json | Cross-run tracking |

**Rationale**:
- Agent outputs validated deterministically at read time, not at reporting time
- Invalid outputs trigger immediate re-spawn with specific Pydantic error messages
- `model_json_schema()` generates JSON Schema for SDK `output_format` parameter
- Self-documenting: the model IS the specification, not a separate markdown file
- Field additions/renames handled by Pydantic validators with backward-compatible defaults

**Consequences**:
- Every file read goes through `Model.model_validate_json(path.read_text())`
- Every file write goes through `path.write_text(model.model_dump_json(indent=2))`
- Schema violations caught at the point of read, with file path and field-level errors
- No silent data corruption -- malformed JSON from agents is rejected immediately

---

## ADR-06: Programmatic Orchestration (Python Controls Flow)

**Status**: Accepted

**Context**: In the Skill architecture, the "DD Master" (Claude Code itself) drives the 35-step pipeline. It decides when to proceed, when to retry, when to validate, and when to stop. The DD Master is an LLM interpreting a 638-line SKILL.md file -- it can skip steps, miscount outputs, or proceed past failed gates. All 17 retrospective failures were control-flow failures, not analytical failures.

**Decision**: The orchestrator is a Python async state machine. Each of the 35 pipeline steps is a Python function. Transitions are code. Agents are invoked at specific steps (15-16 for specialists, 19-22 for Judge, 23 for Reporting Lead) and their outputs are validated by Python before the pipeline advances.

**Pattern**:
```python
async def run_pipeline(project_dir: Path, resume: bool = False):
    state = load_or_create_state(project_dir, resume)

    for step in PipelineStep:
        if step in state.completed_steps:
            continue  # Resume support

        state.current_step = step
        state.save_checkpoint()

        try:
            result = await STEP_FUNCTIONS[step](state)
            state.completed_steps.append(step)
        except BlockingGateError as e:
            log_and_halt(state, step, e)
            raise
```

**Six blocking gates** (pipeline halts if any fails):

| Gate | Step | Condition |
|------|------|-----------|
| Config validation | 1 | `config_version` present, required sections exist |
| Extraction gate | 5 | < 50% systemic extraction failure rate |
| Customer coverage | 17 | All customers have output from all 4 agents |
| Numerical audit | 27 | All 5 validation layers pass |
| QA audit | 28 | All applicable DoD checks pass |
| Post-gen validation | 31 | Excel matches report_schema.json |

**Consequences**:
- Pipeline progress is deterministic and auditable (checkpoint JSON at every step)
- Resume-from-checkpoint after any failure (no re-running completed steps)
- Retry logic is programmatic with configurable limits
- Step timing and cost tracked automatically via `ResultMessage`
- No risk of the orchestrator "forgetting" to run a validation gate
