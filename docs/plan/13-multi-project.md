# 13 — Multi-Project Isolation

## Overview

M&A due diligence involves material non-public information (MNPI). Each deal is confidential. The system must guarantee that no data leaks between deals -- not through shared state, agent context windows, log files, or filesystem access. This document defines how multiple deals coexist on the same machine with complete isolation.

Cross-reference: `01-architecture-decisions.md` ADR-02 (filesystem storage), `02-system-architecture.md` (security boundary), `03-project-structure.md` (directory layout), `05-orchestrator.md` (PipelineState), `12-error-recovery.md` (Scenario 10: shared resource contention).

---

## 1. Data Isolation Model

### 1.1 Core Principle

Each deal gets its own `_dd/` directory rooted at the data room path. There is no shared state between deals. The `entity_resolution_cache.json` is shared across DD skills within the same deal but keyed by deal -- it is NOT shared across different deals.

```
/path/to/alpha-deal/                     # Data room root for Deal A
  deal-config.json
  Subject A/
  Subject B/
  _dd/                                    # All DD artifacts for THIS deal only
    forensic-dd/
      runs/
        20260215_100000/
        latest -> 20260215_100000
      index/text/
      inventory/
    entity_resolution_cache.json          # Shared across DD skills, scoped to deal
    run_history.json                      # Shared across DD skills, scoped to deal
    framework_version.txt

/path/to/beta-deal/                      # Data room root for Deal B (fully isolated)
  deal-config.json
  Subject X/
  Subject Y/
  _dd/                                    # Completely separate artifact tree
    forensic-dd/
      runs/
      index/text/
      inventory/
    entity_resolution_cache.json          # Independent from Deal A
    run_history.json
```

### 1.2 What Is NOT Shared Between Deals

| Resource | Scope | Location |
|----------|-------|----------|
| `_dd/` directory tree | Per deal | `{data_room}/_dd/` |
| `entity_resolution_cache.json` | Per deal (shared across skills within the deal) | `{data_room}/_dd/entity_resolution_cache.json` |
| `run_history.json` | Per deal (shared across skills within the deal) | `{data_room}/_dd/run_history.json` |
| Agent context windows | Per invocation | In-memory (fresh `query()` per agent) |
| MCP tool state | Per deal run | Python closures scoped to project |
| Log files | Per deal, per run | `{data_room}/_dd/logs/` |
| Configuration | Per deal | `{data_room}/deal-config.json` |

### 1.3 The Only Shared Resource

If the optional project registry feature is used (see section 2), a single `project_registry.json` file exists at the base directory level. This file contains only metadata (deal names, paths, status, timestamps) -- never deal data. It is updated atomically after runs complete.

---

## 2. Project Registry (Optional)

### 2.1 Registry Model

For users managing multiple deals, an optional project registry provides a centralized index. This is a convenience feature, not a requirement -- each deal is fully self-contained and can run independently.

```python
# src/dd_agents/models/project.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ProjectEntry(BaseModel):
    """Registry entry for one deal project."""
    name: str                                          # Human-readable deal name
    slug: str                                          # Directory name (safe_name convention)
    path: str                                          # Absolute path to data room root
    created_at: str                                    # ISO-8601
    last_run_at: Optional[str] = None                  # ISO-8601 of most recent run
    last_run_id: Optional[str] = None
    status: str = "created"                            # created | running | completed | failed
    total_runs: int = 0
    total_subjects: int = 0
    total_findings: int = 0
    deal_type: str = ""                                # acquisition, merger, etc.
    notes: str = ""
    locked_by: Optional[str] = None                    # PID if currently running


class ProjectRegistry(BaseModel):
    """Global registry of all deal projects."""
    version: int = 1
    base_dir: str
    projects: list[ProjectEntry] = Field(default_factory=list)
    last_updated: str = ""
```

### 2.2 CLI Commands for Project Management

```bash
# Create a new deal project
dd-agents new-deal "Alpha Acquisition" --data-room /path/to/alpha-data/
# Registers in project_registry.json, copies deal-config template

# List all deals
dd-agents list-deals
# NAME                   STATUS      LAST RUN          CUSTOMERS  FINDINGS
# alpha-acquisition      completed   2026-02-15 10:00  182        412
# beta-merger            running     2026-02-21 09:30  45         --

# Run analysis directly on a data room (no registry needed)
dd-agents run /path/to/alpha-data/
# Equivalent: dd-agents run --deal "Alpha Acquisition" (if registered)

# Check run status
dd-agents status "Alpha Acquisition"
```

---

## 3. Parallel Deal Execution

### 3.1 Process-Level Isolation

Multiple CLI instances can run on different data rooms simultaneously. Each invocation is a separate Python process with no shared in-memory state.

```bash
# Terminal 1
dd-agents run /path/to/alpha-data/ &

# Terminal 2
dd-agents run /path/to/beta-data/ &

# Both run independently -- no conflicts
```

### 3.2 Lock Management

A file-based lock prevents running the same deal twice concurrently. The lock file is `{data_room}/_dd/.lock` and contains the PID of the running process.

```python
# src/dd_agents/core/project.py

import os
from pathlib import Path


class ProjectLock:
    """File-based lock for a deal project."""

    def __init__(self, project_dir: Path):
        self.lock_file = project_dir / "_dd" / ".lock"

    def acquire(self) -> bool:
        # Stale lock detection: locks include the PID of the holder.
        # On startup, if a lock file exists and the PID is not running
        # (os.kill(pid, 0) raises ProcessLookupError), the lock is
        # considered stale and automatically removed.
        if self.lock_file.exists():
            pid = int(self.lock_file.read_text().strip())
            if _process_alive(pid):
                return False  # Another run is active
            # Stale lock -- previous run crashed
            self.lock_file.unlink()
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(str(os.getpid()))
        return True

    def release(self):
        if self.lock_file.exists():
            self.lock_file.unlink()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Deal is already running (locked by another process)")
        return self

    def __exit__(self, *args):
        self.release()


def _process_alive(pid: int) -> bool:
    """Check if a process is still running.

    Agent cleanup uses os.kill(pid, signal.SIGTERM) on Unix/macOS. For
    cross-platform compatibility, the SDK's built-in agent termination
    API should be preferred over direct os.kill calls.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
```

### 3.3 No Cross-Deal Filesystem Conflicts

Deals share no filesystem resources that could conflict:
- Each deal has its own `_dd/` directory tree rooted at its data room path
- Each deal has its own `entity_resolution_cache.json` (inside its `_dd/`)
- Each deal has its own `run_history.json` (inside its `_dd/`)
- The only optionally shared file is `project_registry.json`, updated atomically after runs complete

### 3.4 Resource Limits

Configurable via environment variables or CLI flags:

| Resource | Default | Override |
|----------|---------|----------|
| Max concurrent agents per deal | 4 (specialists) | `DD_MAX_CONCURRENT_AGENTS` |
| Max budget per deal run | $20.00 | `--max-budget` CLI flag |
| Agent timeout | 30 minutes | `DD_AGENT_TIMEOUT_MINUTES` |

---

## 4. Data Isolation Mechanisms

### 4.1 Filesystem Isolation via `cwd`

Every agent spawned by the SDK receives `cwd` pointing to the deal's data room directory. This is the primary isolation mechanism. Agents' built-in tools (Read, Write, Glob, Grep) operate relative to this directory.

```python
# src/dd_agents/agents/manager.py

async def spawn_specialist(self, agent_type: str, prompt: str) -> dict:
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(self.state.project_dir),        # ISOLATION: agents see only this deal
            setting_sources=[],                      # ISOLATION: no global settings
            mcp_servers={"dd": self.tools_server},
            hooks=get_specialist_hooks(agent_type, str(self.state.run_dir),
                                       self.state.total_subjects),
            allowed_tools=SPECIALIST_TOOLS,
            permission_mode="bypassPermissions",
            model="claude-sonnet-4-20250514",
            max_turns=200,
            max_budget_usd=5.00,
        ),
    ):
        yield msg
```

### 4.2 Settings Isolation via `setting_sources=[]`

Passing `setting_sources=[]` ensures no CLAUDE.md files, no user agents, no project settings leak into agent context. Each agent gets only the system prompt and tools configured by the orchestrator.

### 4.3 Path Guard Hook (Defense in Depth)

A PreToolUse hook denies any tool call that references paths outside the project directory:

```python
# src/dd_agents/hooks/path_guard.py

from pathlib import Path
import re


def create_path_guard(project_dir: str):
    """Create a PreToolUse hook that blocks access outside project_dir."""
    project_path = Path(project_dir).resolve()

    async def path_guard_hook(input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Path guard security: All paths are canonicalized using
        # os.path.realpath() (via Path.resolve()) before boundary checking.
        # This resolves relative paths (../), symlinks, and path traversal
        # attempts. The guard rejects any path whose canonicalized form is
        # outside the project directory.

        # Check file_path for Read, Write, Edit
        file_path = tool_input.get("file_path", "")
        if file_path:
            resolved = Path(os.path.realpath(project_path / file_path))
            if not str(resolved).startswith(str(project_path)):
                return {
                    "decision": "block",
                    "reason":
                        f"Access denied: {file_path} is outside project directory",
                }

        # Check path for Glob, Grep
        search_path = tool_input.get("path", "")
        if search_path:
            resolved = (project_path / search_path).resolve()
            if not str(resolved).startswith(str(project_path)):
                return {
                    "decision": "block",
                    "reason":
                        f"Search path {search_path} is outside project directory",
                }

        # Check Bash commands for absolute paths outside project
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            if re.search(r'\bcd\s+/', cmd):
                target = re.search(r'\bcd\s+(/[^\s;|&]+)', cmd)
                if target and not target.group(1).startswith(str(project_path)):
                    return {
                        "decision": "block",
                        "reason":
                            "Cannot cd outside project directory",
                    }

        return {}

    return path_guard_hook
```

### 4.4 Context Window Isolation

Each agent spawned via `query()` gets a fresh context window. No data from other deals exists in context. Each `query()` call starts a new CLI subprocess with its own context.

### 4.5 MCP Tool State Isolation

Custom MCP tools run in the orchestrator process. Each tool receives project-scoped state via closures. Tools do not hold references to other projects.

```python
def create_dd_tools_server(project_dir: Path, state: PipelineState):
    """Create MCP tool server scoped to a specific project."""
    @tool("resolve_entity", "Resolve entity name", {"name": str})
    async def resolve_entity(args):
        cache_path = project_dir / "_dd" / "entity_resolution_cache.json"
        # Scoped to this project's cache only
        ...

    return create_sdk_mcp_server(
        name="dd", version="1.0.0", tools=[resolve_entity, ...],
    )
```

---

## 5. Shared PERMANENT Tier Files (Within a Deal)

Within a single deal, some files are shared across DD skill runs (e.g., `entity_resolution_cache.json`, `run_history.json`). These use the read-validate-write pattern for concurrency safety (see `12-error-recovery.md` Scenario 10).

```python
# src/dd_agents/persistence/shared_files.py

def read_validate_write(file_path: Path, transform, logger, max_retries=1) -> bool:
    """Safely update a shared JSON file with concurrency protection.
    See 12-error-recovery.md Scenario 10 for full implementation.
    """
    ...
```

Key rules:
- Shared PERMANENT files are only written by the DD Master orchestrator (not by specialist agents)
- Contention is limited to concurrent skill invocations on the same deal
- Pattern: read -> apply changes -> write -> re-read to verify -> retry once if changed

---

## 6. Cross-Deal Analysis

Cross-deal analysis is NOT supported. Each deal is independent. There is no mechanism to query findings from Deal A while running Deal B. This is by design -- MNPI isolation requires it.

If cross-deal reporting is needed (e.g., portfolio-level analysis for a PE firm), it must be done as a separate post-processing step that explicitly loads reports from multiple completed deals, with appropriate access controls.

---

## 7. Logging and Audit Trail

### 7.1 Per-Deal Logging

Each deal has its own log directory. No global log file that could leak deal names or data.

```
/path/to/alpha-data/
  _dd/
    logs/
      run_20260215_100000.log        # Full pipeline log
      run_20260215_100000_agents.log # Agent-level messages (costs, errors)
```

### 7.2 Console Output

Console output during `dd-agents run` shows progress without exposing deal data to other terminal sessions. Subject names and finding details are logged to the per-deal log file only. Console shows step progress and summary counts.

```
[Step  4/35] File discovery               182 subjects, 431 files
[Step  5/35] Bulk extraction              429/431 extracted (2 OCR fallback)
[Step  7/35] Entity resolution            182 matched, 0 unresolved
[Step 16/35] Spawning specialists         4 agents (legal, finance, commercial, producttech)
[Step 17/35] Coverage validation          PASS (all 182 subjects covered)
[Step 28/35] QA audit                     PASS (16/16 checks)
[Step 30/35] Excel generation             Due_Diligence_Report_20260221_093000.xlsx
[Step 35/35] Shutdown                     Complete in 47m 23s ($8.42 total)
```

---

## 8. Security Summary

| Threat | Mitigation | Mechanism |
|--------|-----------|-----------|
| Cross-deal data leakage via filesystem | `cwd` per deal + path guard hook | SDK `cwd` + PreToolUse hook |
| Cross-deal leakage via agent context | Fresh `query()` per agent | SDK process isolation |
| Cross-deal leakage via settings | `setting_sources=[]` | SDK settings isolation |
| Cross-deal leakage via logs | Per-deal log files | Structured logging |
| Cross-deal leakage via MCP tools | Project-scoped tool closures | Python scoping |
| Concurrent modification of same deal | File-based lock per project | PID lock file |
| Unauthorized access to deal data | OS-level file permissions | `chmod 700` on project dirs |

The system does not implement user-level authentication or access control. It relies on OS file permissions. If multi-user access is needed, the base directory should be configured with appropriate Unix permissions or the system should be deployed behind an authentication layer.

---

## 9. Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DD_BASE_DIR` | Root directory for project registry | `~/.dd-projects/` |
| `ANTHROPIC_API_KEY` | Claude API authentication | (required) |
| `DD_LOG_LEVEL` | Logging verbosity | `INFO` |
| `DD_MAX_CONCURRENT_AGENTS` | Max parallel agents per deal | 4 |
| `DD_AGENT_TIMEOUT_MINUTES` | Agent timeout before kill | 30 |
| `DD_DEFAULT_MAX_BUDGET` | Default max budget per run | 20.00 |

### 9.1 Per-Deal Environment

If a deal requires its own API key (e.g., client-provided key for billing), place a `.env` file in the data room directory. The orchestrator loads it before spawning agents.

```python
env_file = project_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)
```
