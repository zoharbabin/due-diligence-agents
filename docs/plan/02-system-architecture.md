# 02 -- System Architecture

High-level component architecture, control and data flow, three-tier persistence model, agent interaction model, and hook enforcement points for the Due Diligence Agent SDK.

> **Historical note**: This document references the ReportingLead agent which was removed in v0.4.0. Step 23 is now deterministic pre-merge validation (`validation/pre_merge.py`). See `06-agents.md` §11.

---

## Component Diagram

```
+------------------------------------------------------------------+
|                        CLI Entry Point                            |
|                   python -m dd_agents run <config>                |
+-------------------------------+----------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                      PYTHON ORCHESTRATOR                          |
|                      (core/engine.py)                             |
|                                                                   |
|  +------------+  +----------+  +-----------+  +----------------+ |
|  | Pipeline   |  |  State   |  |  Config   |  |    Error       | |
|  |  Engine    |--|  Machine |--|  Loader   |--|   Recovery     | |
|  | (35 steps) |  |          |  | (Pydantic)|  |   Manager      | |
|  +------------+  +----------+  +-----------+  +----------------+ |
|                                                                   |
|  +------------+  +----------+  +-----------+  +----------------+ |
|  |  Agent     |  |Validation|  |  Prompt   |  |  Persistence   | |
|  |  Runner    |--|  Gates   |--|  Builder  |--|   Manager      | |
|  | (spawner)  |  |(6 gates) |  | (per-agent)|  | (3-tier)      | |
|  +------------+  +----------+  +-----------+  +----------------+ |
+-------------------------------+----------------------------------+
                                |
             +------------------+------------------+
             |                  |                  |
             v                  v                  v
+----------------+   +----------------+   +------------------+
|  MCP Tool      |   |  Hook          |   |  Agent           |
|  Server        |   |  Registry      |   |  Definitions     |
|  (dd_tools)    |   |                |   |                  |
| validate_find  |   | PreToolUse:    |   | Legal   (Sonnet) |
| validate_gap   |   |  path_guard    |   | Finance (Sonnet) |
| validate_manif |   |  bash_guard    |   | Commercl(Sonnet) |
| verify_citation|   |  json_validate |   | ProdTech(Sonnet) |
| resolve_entity |   | Stop:          |   | Judge   (Opus)   |
| get_cust_files |   |  coverage_chk  |   | Reporting(Sonnet)|
| report_progress|   |                |   |                  |
| semantic_srch¹ |   |                |   |                  |
+----------------+   +----------------+   +------------------+
             |                  |                  |
             +------------------+------------------+
                                |
                                v
+------------------------------------------------------------------+
|                    Claude Agent SDK Layer                          |
|                                                                   |
|   query()    ClaudeAgentOptions    HookMatcher    @tool           |
|   ClaudeSDKClient    AgentDefinition    create_sdk_mcp_server     |
|                                                                   |
|              +-----------------------------+                      |
|              | Claude Code CLI Subprocess  |                      |
|              | (stdin/stdout JSON protocol)|                      |
|              +-----------------------------+                      |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                   File System (Three-Tier)                        |
|                                                                   |
|   PERMANENT           VERSIONED              FRESH                |
|   (never wiped)       (archived per run)     (rebuilt every run)  |
|                                                                   |
|   _dd/forensic-dd/    _dd/forensic-dd/       _dd/forensic-dd/    |
|     index/text/*.md     runs/{id}/findings/    inventory/         |
|     index/text/         runs/{id}/audit/         tree.txt         |
|      checksums.sha256   runs/{id}/judge/         files.txt        |
|     index/              runs/{id}/report/        file_types.txt   |
|      extraction_        runs/{id}/metadata.json  subjects.csv    |
|      quality.json       runs/{id}/audit.json     counts.json      |
|                         runs/{id}/numerical_     reference_files.  |
|   _dd/entity_            manifest.json             json           |
|     resolution_         runs/{id}/file_          subject_        |
|     cache.json           coverage.json             mentions.json  |
|                         runs/{id}/               entity_matches.  |
|   _dd/run_history.       classification.json       json           |
|     json                runs/{id}/                                |
|                          inventory_snapshot/                       |
|   _dd/forensic-dd/                                                |
|     runs/ (all prior                                              |
|     runs preserved)                                               |
+------------------------------------------------------------------+
```

> ¹ `semantic_srch` is optional -- only available when ChromaDB is enabled (`[project.optional-dependencies] vector`).

---

## Control Flow: 35-Step Pipeline

The pipeline executes as a linear sequence with conditional branches. Each step is a Python async function. The state machine tracks progress and supports resume-from-checkpoint.

**Resume semantics**: Resume loads `PipelineState` from the latest checkpoint, skips completed steps, and resumes from the first incomplete step. PERMANENT tier data is always available. VERSIONED tier data from the interrupted run is preserved. FRESH tier is NOT rebuilt on resume -- it uses the data from the original run start.

```
PHASE 1: SETUP (Steps 1-3)
  Step  1: Load deal-config.json, validate against Pydantic DealConfig model
           *** BLOCKING GATE: halt if config invalid or version incompatible ***
  Step  2: Generate run_id, create RUN_DIR tree, snapshot prior inventory, wipe FRESH tier
  Step  3: Cross-skill check (scan _dd/{other-skill}/runs/latest/), write initial metadata.json

PHASE 2: DISCOVERY & EXTRACTION (Steps 4-5)
  Step  4: File discovery (tree, find, file --mime-type) -> tree.txt, files.txt, file_types.txt
  Step  5: Bulk pre-extraction (markitdown + fallback chain, checksum cache)
           *** BLOCKING GATE: block if any file has checksum mismatch or extraction_quality.json reports failure for any file ***

PHASE 3: INVENTORY (Steps 6-12)
  Step  6: Build inventory -> subjects.csv, counts.json
  Step  7: Entity resolution (cache check first, then 6-pass matcher) -> entity_matches.json
  Step  8: Reference file registry -> reference_files.json
  Step  9: Subject-mention index -> subject_mentions.json
  Step 10: Inventory integrity verification (total files = subject + reference, no orphans)
  Step 11: [IF source_of_truth.subject_database] Contract date reconciliation
  Step 12: [IF incremental mode] Subject classification -> classification.json

PHASE 4: AGENT EXECUTION (Steps 13-17)
  Step 13: Create team and tasks
  Step 14: Prepare agent prompts (token estimation, batching if > 80K tokens)
  Step 15: Route reference files to agents per category
  Step 16: Spawn 4 specialists IN PARALLEL (Legal, Finance, Commercial, ProductTech)
  Step 17: Validate subject coverage
           *** BLOCKING GATE: every subject must have output from all 4 agents ***
           - Count {subject_safe_name}.json files per agent directory
           - Re-spawn for missing subjects (one retry)
           - Verify no aggregate files (_global.json, batch_summary.json)
           - Verify coverage_manifest.json exists per agent
           - Spot-check clean-result entries for subjects with zero findings

PHASE 5: QUALITY REVIEW (Steps 18-22)
  Step 18: [IF incremental mode] Merge new findings with carried-forward findings
  Step 19: [IF judge enabled] Spawn Judge agent
  Step 20: [IF judge enabled] Judge samples, spot-checks, scores per 5 dimensions
  Step 21: [IF judge enabled] If any agent < threshold: re-spawn with targeted feedback
  Step 22: [IF judge enabled] Round 2. Force finalize with caveats if still below threshold.

PHASE 6: REPORTING (Steps 23-31)
  Step 23: Spawn pre-merge validation
  Step 24: Merge and deduplicate findings per subject
  Step 25: Merge gap files (collect from all agents, dedup by missing_item)
  Step 26: Build numerical manifest (N001-N010 minimum entries)
  Step 27: Numerical audit (6-layer validation)
           *** BLOCKING GATE: all layers must pass ***
  Step 28: Full QA audit (16+ checks mapping to 31 DoD items)
           *** BLOCKING GATE: audit_passed must be true ***
  Step 29: [IF prior run exists] Build report diff
  Step 30: Generate Excel from report_schema.json via build_report.py
  Step 31: Post-generation validation (schema match + cross-format parity)
           *** BLOCKING GATE: Excel must match schema ***

PHASE 7: FINALIZATION (Steps 32-35)
  Step 32: Finalize metadata.json, update latest symlink
  Step 33: Append to _dd/run_history.json
  Step 34: Save entity resolution cache to _dd/entity_resolution_cache.json
  Step 35: Shutdown all agents, clean up CLI subprocesses
```

---

## Data Flow

```
deal-config.json
    |
    v
[Step 1: Config Loader] --> DealConfig (Pydantic model in memory)
    |
    v
[Steps 4-5: Discovery + Extraction]
    |
    +--> _dd/forensic-dd/inventory/tree.txt
    +--> _dd/forensic-dd/inventory/files.txt
    +--> _dd/forensic-dd/inventory/file_types.txt
    +--> _dd/forensic-dd/index/text/*.md          (PERMANENT: extracted documents)
    +--> _dd/forensic-dd/index/text/checksums.sha256
    +--> _dd/forensic-dd/index/extraction_quality.json
    |
    v
[Steps 6-10: Inventory Construction]
    |
    +--> _dd/forensic-dd/inventory/subjects.csv
    +--> _dd/forensic-dd/inventory/counts.json
    +--> _dd/forensic-dd/inventory/reference_files.json
    +--> _dd/forensic-dd/inventory/subject_mentions.json
    +--> _dd/forensic-dd/inventory/entity_matches.json
    |
    v
[Steps 14-15: Prompt Builder + Route References]
    |
    +--> 4 specialist prompts (constructed in memory, not written to disk)
    |    Each contains: deal context, full subject list with safe_names,
    |    reference file text, extraction rules, governance rules,
    |    gap detection rules, cross-reference rules, output schema
    |
    v
[Steps 16-17: 4 Specialist Agents in Parallel]
    |
    |  Legal Agent --->  {RUN_DIR}/findings/legal/{subject_safe_name}.json
    |                    {RUN_DIR}/findings/legal/gaps/{subject_safe_name}.json
    |                    {RUN_DIR}/findings/legal/coverage_manifest.json
    |                    {RUN_DIR}/audit/legal/audit_log.jsonl
    |
    |  Finance Agent --> {RUN_DIR}/findings/finance/{subject_safe_name}.json
    |                    {RUN_DIR}/findings/finance/gaps/{subject_safe_name}.json
    |                    {RUN_DIR}/findings/finance/coverage_manifest.json
    |                    {RUN_DIR}/audit/finance/audit_log.jsonl
    |
    |  Commercial ----> {RUN_DIR}/findings/commercial/{subject_safe_name}.json
    |                   {RUN_DIR}/findings/commercial/gaps/{subject_safe_name}.json
    |                   {RUN_DIR}/findings/commercial/coverage_manifest.json
    |                   {RUN_DIR}/audit/commercial/audit_log.jsonl
    |
    |  ProductTech ---> {RUN_DIR}/findings/producttech/{subject_safe_name}.json
    |                   {RUN_DIR}/findings/producttech/gaps/{subject_safe_name}.json
    |                   {RUN_DIR}/findings/producttech/coverage_manifest.json
    |                   {RUN_DIR}/audit/producttech/audit_log.jsonl
    |
    v
[Steps 19-22: Judge Agent (optional)]
    |
    +--> {RUN_DIR}/judge/quality_scores.json
    |    (contains agent_scores, unit_scores, spot_checks[], contradictions[] inline)
    |
    v
[Steps 23-31: pre-merge validation + Validation Gates]
    |
    +--> {RUN_DIR}/findings/merged/{subject_safe_name}.json
    +--> {RUN_DIR}/findings/merged/gaps/{subject_safe_name}.json
    +--> {RUN_DIR}/numerical_manifest.json
    +--> {RUN_DIR}/file_coverage.json
    +--> {RUN_DIR}/audit.json
    +--> {RUN_DIR}/report_diff.json (if prior run)
    +--> {RUN_DIR}/audit/reporting_lead/audit_log.jsonl
    +--> {RUN_DIR}/report/build_report.py
    +--> {RUN_DIR}/report/Due_Diligence_Report_{run_id}.xlsx
    |
    v
[Steps 32-35: Finalization]
    |
    +--> {RUN_DIR}/metadata.json (finalized with checksums, counts, scores)
    +--> _dd/run_history.json (appended)
    +--> _dd/entity_resolution_cache.json (updated)
    +--> latest symlink updated: _dd/forensic-dd/runs/latest -> {run_id}
```

---

## Three-Tier Persistence Model

### PERMANENT Tier (never wiped)

Files that persist indefinitely across all runs. Wiping these forces expensive re-computation.

| File | Purpose | Created by |
|------|---------|------------|
| `_dd/forensic-dd/index/text/*.md` | Extracted document text (one .md per source file) | Step 5 (extraction) |
| `_dd/forensic-dd/index/text/checksums.sha256` | SHA-256 hashes mapping source files to extraction cache | Step 5 (extraction) |
| `_dd/forensic-dd/index/extraction_quality.json` | Per-file extraction method, byte count, confidence | Step 5 (extraction) |
| `_dd/entity_resolution_cache.json` | Learned entity matches across runs (shared across skills) | Step 34 (finalization) |
| `_dd/forensic-dd/runs/` | Directory containing all prior run directories (never deleted) | Step 2 (persistence setup) |
| `_dd/run_history.json` | Chronological log of all runs across all DD skills (shared) | Step 33 (finalization) |

### VERSIONED Tier (archived per run)

Each run creates `_dd/forensic-dd/runs/{run_id}/` with immutable artifacts. Never modified after the run completes.

| File | Purpose |
|------|---------|
| `findings/legal/*.json` | Legal agent per-subject output |
| `findings/finance/*.json` | Finance agent per-subject output |
| `findings/commercial/*.json` | Commercial agent per-subject output |
| `findings/producttech/*.json` | ProductTech agent per-subject output |
| `findings/{agent}/gaps/*.json` | Per-agent per-subject gap files |
| `findings/{agent}/coverage_manifest.json` | Per-agent coverage manifest |
| `findings/merged/*.json` | Merged per-subject findings |
| `findings/merged/gaps/*.json` | Merged per-subject gaps |
| `audit/{agent}/audit_log.jsonl` | Per-agent audit trail (one per specialist + reporting_lead + judge) |
| `audit.json` | Consolidated QA audit results (16+ checks, 31 DoD items) |
| `numerical_manifest.json` | All numbers used in report with source traceability |
| `file_coverage.json` | File-to-agent coverage mapping |
| `classification.json` | Subject classification (incremental mode only) |
| `contract_date_reconciliation.json` | Date reconciliation (if subject_database exists) |
| `report_diff.json` | Changes vs prior run (if prior run exists) |
| `judge/quality_scores.json` | Judge output with spot_checks and contradictions inline |
| `metadata.json` | Run metadata: config hash, timestamps, counts, scores |
| `inventory_snapshot/` | Copy of FRESH inventory at time of run |
| `report/build_report.py` | Generated Excel builder script |
| `report/Due_Diligence_Report_{run_id}.xlsx` | Final Excel report |

### FRESH Tier (rebuilt every run)

Wiped at the start of each run and rebuilt from the current data room state.

| File | Purpose |
|------|---------|
| `_dd/forensic-dd/inventory/tree.txt` | Directory tree of data room |
| `_dd/forensic-dd/inventory/files.txt` | Flat file list (sorted) |
| `_dd/forensic-dd/inventory/file_types.txt` | MIME types per file |
| `_dd/forensic-dd/inventory/subjects.csv` | Subject registry (group, name, path, file count) |
| `_dd/forensic-dd/inventory/counts.json` | Aggregate counts (files, subjects, by extension, by group) |
| `_dd/forensic-dd/inventory/reference_files.json` | Global reference file catalog with routing |
| `_dd/forensic-dd/inventory/subject_mentions.json` | Subject names found in reference files |
| `_dd/forensic-dd/inventory/entity_matches.json` | Entity resolution results for this run |

**Note**: `entity_matches.json` is FRESH (rebuilt every run from current inventory + cache). The PERMANENT tier holds `entity_resolution_cache.json` (the learned match cache that accumulates across runs). This is intentional -- `entity_matches.json` is a per-run artifact derived from the current inventory state.

---

## Run Initialization Sequence

Executed by the orchestrator at Step 2 (Python code, not agent-driven):

```python
async def setup_persistence(state: PipelineState) -> None:
    skill_dir = state.project_dir / "_dd" / "forensic-dd"
    run_dir = skill_dir / "runs" / state.run_id

    # Create run directory tree
    for subdir in [
        "findings/legal/gaps", "findings/finance/gaps",
        "findings/commercial/gaps", "findings/producttech/gaps",
        "findings/merged/gaps",
        "judge", "report",
        "audit/legal", "audit/finance",
        "audit/commercial", "audit/producttech",
        "audit/reporting_lead", "audit/judge",
    ]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Ensure PERMANENT directories exist
    (skill_dir / "index" / "text").mkdir(parents=True, exist_ok=True)
    (skill_dir / "inventory").mkdir(parents=True, exist_ok=True)

    # Snapshot prior inventory before wiping FRESH tier
    latest_link = skill_dir / "runs" / "latest"
    if latest_link.is_symlink():
        prior_run_id = latest_link.resolve().name
        prior_run_dir = skill_dir / "runs" / prior_run_id
        inventory_dir = skill_dir / "inventory"
        snapshot_dir = prior_run_dir / "inventory_snapshot"
        if inventory_dir.exists() and not snapshot_dir.exists():
            shutil.copytree(inventory_dir, snapshot_dir)

    # DO NOT update latest symlink here -- updated at Step 32 after success

    # Wipe FRESH tier
    inventory_dir = skill_dir / "inventory"
    if inventory_dir.exists():
        shutil.rmtree(inventory_dir)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    state.run_dir = run_dir
    state.skill_dir = skill_dir
```

---

## Agent Interaction Model

### Specialist Agents (4, parallel)

Each specialist is spawned via `query()` as a one-shot invocation. All four run concurrently using `asyncio.gather()`.

```python
async def spawn_specialists(state: PipelineState) -> list[ResultMessage]:
    agent_types = ["legal", "finance", "commercial", "producttech"]

    tasks = []
    for agent_type in agent_types:
        prompt = build_specialist_prompt(
            agent_type=agent_type,
            subjects=state.subjects,
            reference_files=state.reference_files_for(agent_type),
            run_dir=state.run_dir,
            deal_config=state.deal_config,
        )

        task = run_agent(
            prompt=prompt,
            options=ClaudeAgentOptions(
                system_prompt=SPECIALIST_SYSTEM_PROMPTS[agent_type],
                allowed_tools=["Read", "Write", "Grep", "Glob",
                               "mcp__dd_tools__validate_finding",
                               "mcp__dd_tools__resolve_entity",
                               "mcp__dd_tools__get_subject_files",
                               "mcp__dd_tools__report_progress"],
                permission_mode="bypassPermissions",
                cwd=str(state.project_dir),
                max_turns=200,
                max_budget_usd=5.00,
                mcp_servers={"dd_tools": dd_tools_server},
                hooks=get_specialist_hooks(
                    agent_name=agent_type,
                    run_dir=str(state.run_dir),
                    subject_count=len(state.subjects),
                ),
                model="claude-sonnet-4-20250514",
                setting_sources=[],  # Isolated from user settings
            ),
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle failures
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            await handle_agent_failure(state, agent_types[i], result)

    return results
```

### Judge Agent (optional, sequential after specialists)

Spawned only if `deal_config.judge.enabled` is True. Receives all specialist outputs, extracted text, and reference files. Produces a single `quality_scores.json` with spot_checks and contradictions inline.

### pre-merge validation (sequential, after Judge or specialists)

Receives all findings directories, the inventory, Judge scores (if available), the report schema path, and the deal config. Produces merged findings, numerical manifest, audit.json, and the final Excel report.

### Agent Flow Summary

```
                     Orchestrator
                         |
         +-------+-------+-------+-------+
         |       |       |       |
         v       v       v       v
      Legal   Finance  Commerc  ProdTech    <-- parallel (asyncio.gather)
         |       |       |       |
         +-------+-------+-------+
                         |
                         v
                   Coverage Gate (Python)    <-- BLOCKING: re-spawn if incomplete
                         |
                         v
                      Judge (optional)       <-- sequential
                         |
                         v
                   Quality Gate (Python)     <-- trigger iteration if below threshold
                         |
                         v
                   pre-merge validation            <-- sequential
                         |
                         v
                   QA Gates (Python)         <-- BLOCKING: numerical, audit, schema
                         |
                         v
                   Finalization (Python)
```

---

## Hook Enforcement Points

Hooks provide deterministic enforcement at every agent interaction. They run in the orchestrator's Python process, not in the agent's context.

> **All hooks return flat format** — `{"decision": "block"|"allow", "reason": "..."}`. This applies to Stop, PreToolUse, and PostToolUse hooks. Do not nest under `hookSpecificOutput`. This is the canonical format per SDK v0.1.39+.

### PreToolUse Hooks

| Hook | Matcher | What it enforces |
|------|---------|-----------------|
| `block_dangerous_commands` | `Bash` | Denies `rm -rf`, `git push`, `chmod 777`, and other destructive patterns |
| `enforce_output_paths` | `Write` | Specialists can only write to `{RUN_DIR}/findings/{agent}/`; pre-merge validation to `{RUN_DIR}/findings/merged/` and `{RUN_DIR}/report/` |
| `validate_json_on_write` | `Write` | Rejects writes to `.json` files with invalid JSON |

### Stop Hooks (flat format)

| Hook | Agent type | What it enforces |
|------|-----------|-----------------|
| `verify_coverage_before_stop` | Specialists | Blocks stop if `count({subject_safe_name}.json) < expected_subjects` |
| `verify_manifest_before_stop` | Specialists | Blocks stop if `coverage_manifest.json` does not exist |
| `verify_audit_before_stop` | Specialists | Blocks stop if `audit_log.jsonl` is empty or missing |

**Format**: Stop hooks return flat `{"decision": "block", "reason": "..."}`, not nested under `hookSpecificOutput`. This is the canonical format for Stop and SubagentStop events per SDK v0.1.39+.

```python
async def verify_coverage_before_stop(input_data, tool_use_id, context):
    """Prevent specialist from stopping before processing all subjects."""
    output_dir = Path(run_dir) / "findings" / agent_name
    actual = len([f for f in output_dir.glob("*.json")
                  if f.name != "coverage_manifest.json"])
    if actual < expected_subjects:
        return {
            "decision": "block",
            "reason": (
                f"Produced {actual}/{expected_subjects} subject JSONs. "
                f"Continue processing remaining subjects."
            ),
        }
    return {}
```

### PostToolUse Hooks

| Hook | Matcher | What it enforces |
|------|---------|-----------------|
| `track_output_count` | `Write` | Increments per-agent subject output counter |
| `validate_subject_json` | `Write` | Validates written subject JSON against SubjectJSON Pydantic model |

### How Hooks Enforce Quality at Every Step

```
Agent attempts: Write to findings/legal/acme_corp.json
  1. PreToolUse fires:
     - enforce_output_paths: path starts with {RUN_DIR}/findings/legal/ -> ALLOW
     - validate_json_on_write: content parses as valid JSON -> ALLOW
  2. Write executes (file written to disk)
  3. PostToolUse fires:
     - track_output_count: increment legal agent counter to N
     - validate_subject_json: parse file, check required fields -> feedback if invalid

Agent attempts: Stop (finish execution)
  4. Stop hook fires:
     - verify_coverage_before_stop: count = 28, expected = 34 -> BLOCK
     - Agent receives: "Produced 28/34 subject JSONs. Continue processing."
  5. Agent continues processing remaining 6 subjects
  6. Agent attempts Stop again
  7. Stop hook fires:
     - verify_coverage_before_stop: count = 34, expected = 34 -> ALLOW
  8. Agent stops. Orchestrator receives ResultMessage.
  9. Orchestrator runs Python validation gate (Step 17):
     - Counts files on disk independently of hooks
     - Verifies coverage_manifest.json exists
     - Verifies no aggregate files
     - Verifies audit_log.jsonl exists
```
