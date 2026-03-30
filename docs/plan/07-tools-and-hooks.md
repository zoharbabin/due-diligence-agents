# 07 — Custom MCP Tools and Hook Implementations

## Overview

The Agent SDK provides two distinct enforcement mechanisms:
1. **Custom MCP tools** -- functions exposed to agents via `create_sdk_mcp_server` that agents call voluntarily (validation, lookup, verification)
2. **Hooks** -- Python callbacks that fire automatically at specific lifecycle events (PreToolUse, PostToolUse, Stop) and enforce rules the agent cannot bypass

Tools help agents do the right thing. Hooks prevent agents from doing the wrong thing.

---

## 1. Custom MCP Tools

Six tools (plus `report_progress`) are exposed to agents. These run in-process within the orchestrator's Python runtime via the SDK's MCP server mechanism (`dd_tools` server key). Agents invoke them by name; results return inline.

### 1.1 Tool Registration

```python
# src/dd_agents/tools/mcp_server.py

from claude_agent_sdk import tool, create_sdk_mcp_server

def build_mcp_server(run_dir: Path, skill_dir: Path, customers_csv: list[dict]):
    """Build the in-process MCP server with all 6 DD tools."""

    tools = [
        build_validate_finding_tool(),
        build_validate_gap_tool(),
        build_validate_manifest_tool(customers_csv),
        build_verify_citation_tool(skill_dir),
        build_get_customer_files_tool(customers_csv),
        build_resolve_entity_tool(skill_dir),
        build_report_progress_tool(),
    ]

    return create_sdk_mcp_server(
        name="dd_tools",
        version="1.0.0",
        tools=tools,
    )
```

The server is registered per-agent in `ClaudeAgentOptions.mcp_servers`:

```python
options = ClaudeAgentOptions(
    mcp_servers={"dd_tools": mcp_server},
    allowed_tools=[
        "mcp__dd_tools__validate_finding",
        "mcp__dd_tools__validate_gap",
        "mcp__dd_tools__validate_manifest",
        "mcp__dd_tools__verify_citation",
        "mcp__dd_tools__get_customer_files",
        "mcp__dd_tools__resolve_entity",
        "mcp__dd_tools__report_progress",
        # Plus built-in tools
        "Read", "Write", "Bash", "Glob", "Grep",
    ],
)
```

### 1.2 validate_finding

Validates a finding JSON string against the Pydantic `AgentFinding` model (the agent-internal format, not the full `Finding` schema -- agents produce pre-transformation output). Called by agents before writing customer JSONs to catch schema violations early.

```python
# src/dd_agents/tools/validate_finding.py

from dd_agents.models.finding import Severity, Confidence
from dd_agents.models.customer import AgentFinding
from pydantic import ValidationError

def build_validate_finding_tool():

    @tool(
        "validate_finding",
        "Validate a finding JSON against the schema. Returns 'valid' or error details.",
        {
            "type": "object",
            "properties": {
                "finding_json": {
                    "type": "string",
                    "description": "JSON string of a single finding object"
                }
            },
            "required": ["finding_json"]
        }
    )
    async def validate_finding(args):
        finding_json = args["finding_json"]
        try:
            finding = AgentFinding.model_validate_json(finding_json)

            # Additional domain checks beyond Pydantic
            errors = []

            # P0/P1 require exact_quote in all citations
            if finding.severity in (Severity.P0, Severity.P1):
                for i, cit in enumerate(finding.citations):
                    if not cit.exact_quote:
                        errors.append(
                            f"citations[{i}]: {finding.severity} finding requires "
                            f"non-empty exact_quote"
                        )

            # Category must be a recognized value
            valid_categories = {
                "change_of_control", "assignment", "termination", "liability",
                "indemnification", "governing_law", "ip_ownership", "non_compete",
                "exclusivity", "mfn", "pricing", "payment_terms", "discount",
                "revenue_recognition", "renewal", "sla", "service_credits",
                "territory", "dpa", "security", "data_residency", "regulatory",
                "missing_document", "data_gap", "domain_reviewed_no_issues", "Other",
            }
            if finding.category not in valid_categories:
                errors.append(
                    f"category '{finding.category}' not in recognized categories"
                )

            if errors:
                return {
                    "content": [{"type": "text", "text": f"invalid: {errors}"}]
                }

            return {"content": [{"type": "text", "text": "valid"}]}

        except ValidationError as e:
            return {
                "content": [{"type": "text", "text": f"invalid: {e.errors()}"}]
            }

    return validate_finding
```

### 1.3 validate_gap

Validates a gap JSON string against the Pydantic `Gap` model. Enforces the 6 valid gap types and 7 valid detection methods.

```python
# src/dd_agents/tools/validate_gap.py

from dd_agents.models.gap import Gap, GapType, DetectionMethod
from pydantic import ValidationError

VALID_GAP_TYPES = {gt.value for gt in GapType}
VALID_DETECTION_METHODS = {dm.value for dm in DetectionMethod}

def build_validate_gap_tool():

    @tool(
        "validate_gap",
        "Validate a gap JSON against the schema. Returns 'valid' or error details.",
        {
            "type": "object",
            "properties": {
                "gap_json": {
                    "type": "string",
                    "description": "JSON string of a single gap object"
                }
            },
            "required": ["gap_json"]
        }
    )
    async def validate_gap(args):
        gap_json = args["gap_json"]
        try:
            gap = Gap.model_validate_json(gap_json)

            errors = []

            if gap.gap_type.value not in VALID_GAP_TYPES:
                errors.append(
                    f"gap_type '{gap.gap_type}' not in "
                    f"{sorted(VALID_GAP_TYPES)}"
                )

            if gap.detection_method.value not in VALID_DETECTION_METHODS:
                errors.append(
                    f"detection_method '{gap.detection_method}' not in "
                    f"{sorted(VALID_DETECTION_METHODS)}"
                )

            # missing_item max 200 chars enforced by Pydantic Field(max_length=200)

            if errors:
                return {
                    "content": [{"type": "text", "text": f"invalid: {errors}"}]
                }

            return {"content": [{"type": "text", "text": "valid"}]}

        except ValidationError as e:
            return {
                "content": [{"type": "text", "text": f"invalid: {e.errors()}"}]
            }

    return validate_gap
```

### 1.4 validate_manifest

Validates a coverage manifest JSON. Checks `files_assigned` length against expected file count, `coverage_pct >= 0.90`, and that every customer entry has a status.

```python
# src/dd_agents/tools/validate_manifest.py

from dd_agents.models.manifest import CoverageManifest
from pydantic import ValidationError

def build_validate_manifest_tool(customers_csv: list[dict]):

    expected_customer_count = len(customers_csv)
    expected_customer_names = {c["customer_safe_name"] for c in customers_csv}

    @tool(
        "validate_manifest",
        "Validate a coverage_manifest.json. Returns 'valid' or error details.",
        {
            "type": "object",
            "properties": {
                "manifest_json": {
                    "type": "string",
                    "description": "JSON string of coverage_manifest.json"
                }
            },
            "required": ["manifest_json"]
        }
    )
    async def validate_manifest(args):
        manifest_json = args["manifest_json"]
        try:
            manifest = CoverageManifest.model_validate_json(manifest_json)

            errors = []

            # Coverage percentage gate
            if manifest.coverage_pct < 0.90:
                errors.append(
                    f"coverage_pct is {manifest.coverage_pct:.2f}, "
                    f"must be >= 0.90"
                )

            # Customer count check
            if manifest.analysis_units_assigned != expected_customer_count:
                errors.append(
                    f"analysis_units_assigned={manifest.analysis_units_assigned}, "
                    f"expected={expected_customer_count}"
                )

            if manifest.analysis_units_completed < manifest.analysis_units_assigned:
                errors.append(
                    f"analysis_units_completed ({manifest.analysis_units_completed}) < "
                    f"analysis_units_assigned ({manifest.analysis_units_assigned})"
                )

            # Every customer must have a status
            manifest_names = set()
            for cust in manifest.customers:
                manifest_names.add(cust.name)
                if cust.status not in ("complete", "partial"):
                    errors.append(
                        f"customer '{cust.name}' has invalid status "
                        f"'{cust.status}'"
                    )

            # No duplicate customers
            if len(manifest_names) != len(manifest.customers):
                errors.append("duplicate customer entries in manifest")

            # files_failed must have fallback_attempted=True
            for ff in manifest.files_failed:
                if not ff.fallback_attempted:
                    errors.append(
                        f"files_failed entry '{ff.path}' has "
                        f"fallback_attempted=False (must try fallback chain)"
                    )

            if errors:
                return {
                    "content": [{"type": "text", "text": f"invalid: {errors}"}]
                }

            return {"content": [{"type": "text", "text": "valid"}]}

        except ValidationError as e:
            return {
                "content": [{"type": "text", "text": f"invalid: {e.errors()}"}]
            }

    return validate_manifest
```

### 1.5 verify_citation

Given a `source_path` and `exact_quote`, checks whether the quote exists in the pre-extracted text. Uses exact substring match after whitespace normalization, then falls back to fuzzy matching (>85% similarity by default). This is the tool-level analog of the Judge's citation_verification dimension -- agents can self-check before writing.

Fuzzy match threshold defaults to 85% (`rapidfuzz.fuzz.ratio`). Configurable via `deal-config.json` at `tools.verify_citation.fuzzy_threshold` (range: 70-100).

```python
# src/dd_agents/tools/verify_citation.py

import re
import unicodedata
from pathlib import Path
from rapidfuzz import fuzz

def _normalize(text: str) -> str:
    """Normalize whitespace and Unicode for comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text

def _get_text_path(source_path: str, skill_dir: Path) -> Path:
    """Convert original file path to extracted text path.

    Convention: replace '/' with '__', strip leading './', append '.md'.
    """
    safe_name = source_path.lstrip("./").replace("/", "__")
    return skill_dir / "index" / "text" / f"{safe_name}.md"

def build_verify_citation_tool(skill_dir: Path, fuzzy_threshold: float = 0.85):

    @tool(
        "verify_citation",
        "Verify that exact_quote exists in the source document's extracted text. "
        "Returns 'verified', 'verified_fuzzy', 'source_not_found', or 'not_found'.",
        {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Original file path (e.g., './Above 200K/Acme/MSA.pdf')"
                },
                "exact_quote": {
                    "type": "string",
                    "description": "The exact quote to verify"
                }
            },
            "required": ["source_path", "exact_quote"]
        }
    )
    async def verify_citation(args):
        source_path = args["source_path"]
        exact_quote = args["exact_quote"]

        text_path = _get_text_path(source_path, skill_dir)

        if not text_path.exists():
            return {
                "content": [{
                    "type": "text",
                    "text": f"source_not_found: no extracted text at {text_path}"
                }]
            }

        text = text_path.read_text(encoding="utf-8")
        norm_text = _normalize(text)
        norm_quote = _normalize(exact_quote)

        # Exact substring match (after normalization)
        if norm_quote in norm_text:
            return {
                "content": [{"type": "text", "text": "verified"}]
            }

        # Fuzzy match: slide a window across the text
        # Window size = 2x the quote length to allow for insertions
        quote_len = len(norm_quote)
        best_ratio = 0.0

        if quote_len > 20:
            # For longer quotes, use partial_ratio which handles substrings
            best_ratio = fuzz.partial_ratio(norm_quote, norm_text) / 100.0
        else:
            # For short quotes, scan with sliding window
            window_size = min(quote_len * 2, len(norm_text))
            for i in range(0, len(norm_text) - quote_len + 1, max(1, quote_len // 4)):
                window = norm_text[i : i + window_size]
                ratio = fuzz.ratio(norm_quote, window) / 100.0
                best_ratio = max(best_ratio, ratio)
                if best_ratio > fuzzy_threshold:
                    break

        if best_ratio > fuzzy_threshold:
            return {
                "content": [{
                    "type": "text",
                    "text": f"verified_fuzzy (score={best_ratio:.2f})"
                }]
            }

        return {
            "content": [{
                "type": "text",
                "text": f"not_found (best_fuzzy_score={best_ratio:.2f})"
            }]
        }

    return verify_citation
```

### 1.6 get_customer_files

Returns the number of files associated with a given customer name. Agents use this to verify they have processed all files for a customer before writing output.

```python
# src/dd_agents/tools/get_customer_files.py

def build_get_customer_files_tool(customers_csv: list[dict]):

    # Build lookup: customer_safe_name -> file_count
    customer_file_counts = {}
    customer_file_lists = {}
    for row in customers_csv:
        safe_name = row["customer_safe_name"]
        files = row.get("file_list", [])
        customer_file_counts[safe_name] = len(files)
        customer_file_lists[safe_name] = files

    @tool(
        "get_customer_files",
        "Return the number of files for a customer. "
        "Use customer_safe_name (e.g., 'acme_corp').",
        {
            "type": "object",
            "properties": {
                "customer_safe_name": {
                    "type": "string",
                    "description": "The customer_safe_name from the assignment"
                }
            },
            "required": ["customer_safe_name"]
        }
    )
    async def get_customer_files(args):
        safe_name = args["customer_safe_name"]

        if safe_name not in customer_file_counts:
            return {
                "content": [{
                    "type": "text",
                    "text": f"unknown_customer: '{safe_name}' not in inventory"
                }]
            }

        count = customer_file_counts[safe_name]
        files = customer_file_lists[safe_name]
        file_list_str = "\n".join(f"  - {f}" for f in files)
        return {
            "content": [{
                "type": "text",
                "text": f"file_count: {count}\nfiles:\n{file_list_str}"
            }]
        }

    return get_customer_files
```

### 1.7 resolve_entity

Looks up a name in the entity resolution cache and match log. Agents use this when they encounter a customer name in a reference file and need to find the canonical name from `customers.csv`.

```python
# src/dd_agents/tools/resolve_entity.py

import json
from pathlib import Path

def build_resolve_entity_tool(skill_dir: Path):

    @tool(
        "resolve_entity",
        "Look up a name in the entity resolution cache to find the canonical "
        "customer name. Returns the canonical name and match method, or 'not_found'.",
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The entity name to look up"
                }
            },
            "required": ["name"]
        }
    )
    async def resolve_entity(args):
        name = args["name"]

        # Check entity resolution cache (PERMANENT tier)
        cache_path = skill_dir.parent.parent / "entity_resolution_cache.json"
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = cache.get("entries", {})
            if name in entries:
                entry = entries[name]
                return {
                    "content": [{
                        "type": "text",
                        "text": (
                            f"cache_hit: canonical='{entry['canonical']}', "
                            f"pass={entry['match_pass']}, "
                            f"method={entry['match_type']}, "
                            f"confidence={entry['confidence']}"
                        )
                    }]
                }

        # Check current run's entity_matches.json (FRESH tier)
        matches_path = skill_dir / "inventory" / "entity_matches.json"
        if matches_path.exists():
            matches_data = json.loads(matches_path.read_text(encoding="utf-8"))
            for match in matches_data.get("matches", []):
                if match["source_name"] == name:
                    return {
                        "content": [{
                            "type": "text",
                            "text": (
                                f"matched: canonical='{match['canonical_name']}', "
                                f"pass={match['match_pass']}, "
                                f"method={match['match_method']}, "
                                f"confidence={match['confidence']}"
                            )
                        }]
                    }

            # Check unmatched
            for unmatched in matches_data.get("unmatched", []):
                if unmatched["source_name"] == name:
                    return {
                        "content": [{
                            "type": "text",
                            "text": f"unmatched: '{name}' could not be resolved"
                        }]
                    }

        return {
            "content": [{
                "type": "text",
                "text": f"not_found: '{name}' not in cache or match log"
            }]
        }

    return resolve_entity
```

---

## 2. Hook Implementations

> **Hook Return Format (all hook types)**: All hooks return flat JSON: `{"decision": "block" | "allow", "reason": "..."}`. This applies uniformly to Stop, PreToolUse, and PostToolUse hooks. Do NOT nest under `hookSpecificOutput`. The SDK internally wraps the flat format in its envelope -- hook implementations must return only the flat format.

Hooks fire automatically at lifecycle events. Unlike tools (which agents choose to call), hooks are enforced by the SDK -- agents cannot skip or disable them.

### 2.1 Hook Architecture

```
                  Agent wants to call a tool
                           |
                  +--------v--------+
                  | PreToolUse Hook |  <-- Python decides: allow/block
                  +--------+--------+
                           |
                  (if allowed)
                           |
                  +--------v--------+
                  |  Tool Executes  |
                  +--------+--------+
                           |
                  +--------v--------+
                  | PostToolUse Hook| <-- Python validates output
                  +--------+--------+
                           |
                           ...
                  (agent produces final answer)
                           |
                  +--------v--------+
                  |    Stop Hook    | <-- Python checks: all work done?
                  +--------+--------+
                           |
                  (if allowed, agent exits)
```

### 2.2 Hook Factory

Each agent gets its own set of hooks, configured with the agent's name, run directory, and expected customer count. The factory returns a dict suitable for `ClaudeAgentOptions.hooks`.

```python
# src/dd_agents/hooks/factory.py

from pathlib import Path
from claude_agent_sdk import HookMatcher

from dd_agents.hooks.pre_tool import (
    build_bash_guard,
    build_write_guard,
    build_aggregate_file_guard,
)
from dd_agents.hooks.post_tool import build_json_validator
from dd_agents.hooks.stop import build_stop_guard

def build_hooks_for_agent(
    agent_name: str,
    run_dir: Path,
    project_dir: Path,
    expected_customers: int,
) -> dict[str, list[HookMatcher]]:
    """Build the complete hook set for a specialist agent."""

    return {
        "PreToolUse": [
            HookMatcher(
                matcher="Bash",
                hooks=[build_bash_guard(project_dir)],
                timeout=5.0,
            ),
            HookMatcher(
                matcher="Write",
                hooks=[
                    build_write_guard(agent_name, run_dir, project_dir),
                    build_aggregate_file_guard(agent_name),
                ],
                timeout=5.0,
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher="Write",
                hooks=[build_json_validator(agent_name, run_dir)],
                timeout=10.0,
            ),
        ],
        "Stop": [
            HookMatcher(
                hooks=[build_stop_guard(agent_name, run_dir, expected_customers)],
                timeout=10.0,
            ),
        ],
    }
```

---

## 3. PreToolUse Hooks

### 3.1 Block Destructive Bash Commands

Prevents agents from running commands that could destroy data, modify git state, or touch files outside the project directory.

```python
# src/dd_agents/hooks/pre_tool.py

from pathlib import Path

# Commands that are never allowed
BASH_BLOCKLIST = [
    "rm -rf",
    "rm -r ",
    "git push",
    "git reset",
    "git checkout .",
    "git restore .",
    "git clean",
    "chmod",
    "chown",
    "kill ",
    "killall",
    "pkill",
    "sudo ",
    "mkfs",
    "dd if=",
    "> /dev/",
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
]

# Commands allowed only within project scope
SCOPE_CHECKED_PREFIXES = ["mv ", "cp ", "ln ", "mkdir "]

def build_bash_guard(project_dir: Path):

    project_str = str(project_dir.resolve())

    async def bash_guard(input_data, tool_use_id, context):
        tool_input = input_data.get("tool_input", {})
        command = tool_input.get("command", "")

        # Check blocklist
        cmd_lower = command.lower().strip()
        for dangerous in BASH_BLOCKLIST:
            if dangerous in cmd_lower:
                return {
                    "decision": "block",
                    "reason": (
                        f"Blocked dangerous command pattern: "
                        f"'{dangerous}' in: {command[:100]}"
                    ),
                }

        # Check scope: any path argument must be within project_dir or _dd/
        # This is a heuristic -- parse simple path references
        for prefix in SCOPE_CHECKED_PREFIXES:
            if prefix in cmd_lower:
                # Extract paths after the command prefix
                parts = command.split()
                for part in parts[1:]:
                    if part.startswith("/"):
                        resolved = str(Path(part).resolve())
                        if not resolved.startswith(project_str):
                            return {
                                "decision": "block",
                                "reason": (
                                    f"Command references path outside project: "
                                    f"{part}"
                                ),
                            }

        # Allow
        return {}

    return bash_guard
```

### 3.2 Enforce Output Paths

Ensures agents only write to their designated output directories. An agent named "legal" can only write to `{RUN_DIR}/findings/legal/`, `{RUN_DIR}/findings/legal/gaps/`, and `{RUN_DIR}/audit/legal/`. No writes to PERMANENT tier, no writes to other agents' directories.

Path guard resolves symlinks using `os.path.realpath()` before checking path boundaries. This prevents symlink-based escapes from the project directory.

```python
# src/dd_agents/hooks/pre_tool.py  (continued)

def build_write_guard(agent_name: str, run_dir: Path, project_dir: Path):

    # Allowed write paths for this agent
    allowed_prefixes = [
        str(run_dir / "findings" / agent_name),
        str(run_dir / "audit" / agent_name),
    ]

    async def write_guard(input_data, tool_use_id, context):
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return {}

        # Resolve to absolute
        resolved = str(Path(file_path).resolve())

        # Check: must start with one of the allowed prefixes
        for prefix in allowed_prefixes:
            if resolved.startswith(str(Path(prefix).resolve())):
                return {}  # Allowed

        # Block writes to PERMANENT tier
        permanent_dir = str((project_dir / "_dd").resolve())
        if resolved.startswith(permanent_dir):
            return {
                "decision": "block",
                "reason": (
                    f"Agent '{agent_name}' cannot write to PERMANENT tier. "
                    f"Attempted: {file_path}"
                ),
            }

        # Block writes anywhere else
        return {
            "decision": "block",
            "reason": (
                f"Agent '{agent_name}' can only write to "
                f"findings/{agent_name}/ or audit/{agent_name}/. "
                f"Attempted: {file_path}"
            ),
        }

    return write_guard
```

### 3.3 Block Aggregate File Creation

Prevents agents from creating aggregate/batch files instead of per-customer files. This was one of the most common failures in the skill-based system: agents consolidating multiple customers into a single file to save effort.

Aggregate file detection uses exact filename matching against the blocklist, not substring matching, to avoid false positives (e.g., blocking a file named `summary_for_acme.json` when `summary.json` is blocklisted).

```python
# src/dd_agents/hooks/pre_tool.py  (continued)

# Filenames that indicate aggregate output (not per-customer)
BLOCKED_FILENAMES = [
    "_global.json",
    "batch_summary.json",
    "other_customers.json",
    "pipeline_items.json",
    "remaining_customers.json",
    "all_customers.json",
    "combined.json",
    "summary.json",
    "batch_1.json",
    "batch_2.json",
    "batch_3.json",
    "miscellaneous.json",
    "misc.json",
    "overflow.json",
]

# Allowed non-customer filenames (exact match)
ALLOWED_SPECIAL_FILES = [
    "coverage_manifest.json",
    "audit_log.jsonl",
]

def build_aggregate_file_guard(agent_name: str):

    async def aggregate_file_guard(input_data, tool_use_id, context):
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return {}

        filename = Path(file_path).name

        # Allow known special files
        if filename in ALLOWED_SPECIAL_FILES:
            return {}

        # Block known aggregate patterns
        if filename.lower() in [f.lower() for f in BLOCKED_FILENAMES]:
            return {
                "decision": "block",
                "reason": (
                    f"Blocked aggregate file creation: '{filename}'. "
                    f"You MUST produce exactly one JSON per customer named "
                    f"{{customer_safe_name}}.json. Do NOT create aggregate "
                    f"files."
                ),
            }

        # Block files starting with underscore (except special files)
        if filename.startswith("_") and filename not in ALLOWED_SPECIAL_FILES:
            return {
                "decision": "block",
                "reason": (
                    f"Blocked file starting with underscore: '{filename}'. "
                    f"Only {ALLOWED_SPECIAL_FILES} are allowed as non-customer "
                    f"files. Use {{customer_safe_name}}.json for customer output."
                ),
            }

        # Allow everything else (customer-named files, gap files, etc.)
        return {}

    return aggregate_file_guard
```

---

## 4. PostToolUse Hooks

### 4.1 JSON Validation After Write

After any `.json` write to the findings directory, parse the content and validate basic structural requirements. This catches malformed JSON before it reaches the QA phase.

```python
# src/dd_agents/hooks/post_tool.py

import json
from pathlib import Path

def build_json_validator(agent_name: str, run_dir: Path):

    findings_dir = run_dir / "findings" / agent_name

    async def json_validator(input_data, tool_use_id, context):
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return {}

        path = Path(file_path)

        # Only validate JSON files in findings directory
        if path.suffix != ".json":
            return {}
        if not str(path.resolve()).startswith(str(findings_dir.resolve())):
            return {}

        # Skip manifest -- validated separately
        if path.name == "coverage_manifest.json":
            return {}

        # Read and validate the written file
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            return {
                "decision": "block",
                "reason": (
                    f"WARNING: File '{path.name}' contains invalid JSON: {e}. "
                    f"Re-write this file with valid JSON."
                ),
            }

        # Check if this is a gap file (in gaps/ subdirectory)
        if "gaps" in path.parts:
            return _validate_gap_structure(data, path.name)

        # Validate customer JSON structure
        errors = []

        if "customer" not in data:
            errors.append("missing 'customer' field")

        if "findings" not in data:
            errors.append("missing 'findings' array")
        elif not isinstance(data["findings"], list):
            errors.append("'findings' must be an array")

        if "file_headers" not in data:
            errors.append("missing 'file_headers' array")
        elif not isinstance(data["file_headers"], list):
            errors.append("'file_headers' must be an array")

        if "customer_safe_name" not in data:
            errors.append("missing 'customer_safe_name' field")

        if errors:
            return {
                "decision": "block",
                "reason": (
                    f"WARNING: Customer JSON '{path.name}' has structural "
                    f"issues: {errors}. Fix and re-write."
                ),
            }

        return {}

    return json_validator


def _validate_gap_structure(data: dict | list, filename: str) -> dict:
    """Validate a gap file structure."""
    gaps = data if isinstance(data, list) else data.get("gaps", data)
    if isinstance(gaps, list):
        for i, gap in enumerate(gaps):
            required = ["customer", "priority", "gap_type", "missing_item",
                        "why_needed", "risk_if_missing", "request_to_company",
                        "evidence", "detection_method"]
            missing = [f for f in required if f not in gap]
            if missing:
                return {
                    "decision": "block",
                    "reason": (
                        f"WARNING: Gap [{i}] in '{filename}' missing required "
                        f"fields: {missing}. Fix and re-write."
                    ),
                }
    return {}
```

---

## 5. Stop Hooks

### 5.1 Stop Guard (Prevent Premature Exit)

The stop hook fires when an agent signals it wants to finish. The hook checks:
1. Has the agent produced a customer JSON for every assigned customer?
2. Has the agent written `coverage_manifest.json`?
3. Has the agent written `audit_log.jsonl`?

If any check fails, the hook blocks the stop and tells the agent what remains.

**CRITICAL**: The stop hook return format is FLAT -- `{"decision": "block", "reason": "..."}` or `{"decision": "allow", "reason": ""}`. This is the same flat format used by all hook types (PreToolUse, PostToolUse, Stop).

```python
# src/dd_agents/hooks/stop.py

from pathlib import Path

def build_stop_guard(
    agent_name: str,
    run_dir: Path,
    expected_customers: int,
):
    """Build a stop hook that prevents premature agent exit.

    Return format (flat -- same as all hook types):
        {"decision": "block", "reason": "..."}
        {"decision": "allow", "reason": ""}
    """

    async def stop_guard(input_data, tool_use_id, context):
        output_dir = run_dir / "findings" / agent_name
        gaps_dir = output_dir / "gaps"
        audit_dir = run_dir / "audit" / agent_name

        # Count customer JSON files (exclude manifest and directories)
        customer_jsons = [
            f for f in output_dir.glob("*.json")
            if f.name != "coverage_manifest.json"
        ]
        actual_count = len(customer_jsons)

        # Check 1: All customers have output
        if actual_count < expected_customers:
            produced = sorted(f.stem for f in customer_jsons)
            return {
                "decision": "block",
                "reason": (
                    f"Only {actual_count}/{expected_customers} customer JSONs "
                    f"found in findings/{agent_name}/. "
                    f"Produced so far: {produced[:10]}{'...' if len(produced) > 10 else ''}. "
                    f"Continue processing remaining customers."
                ),
            }

        # Check 2: Manifest exists
        manifest_path = output_dir / "coverage_manifest.json"
        if not manifest_path.exists():
            return {
                "decision": "block",
                "reason": (
                    f"coverage_manifest.json not written yet. "
                    f"You have produced {actual_count} customer JSONs. "
                    f"Write the coverage_manifest.json before stopping."
                ),
            }

        # Check 3: Audit log exists and is non-empty
        audit_log_path = audit_dir / "audit_log.jsonl"
        if not audit_log_path.exists():
            return {
                "decision": "block",
                "reason": (
                    f"audit_log.jsonl not written at {audit_dir}/. "
                    f"Write your audit log before stopping."
                ),
            }
        if audit_log_path.stat().st_size == 0:
            return {
                "decision": "block",
                "reason": (
                    f"audit_log.jsonl exists but is empty. "
                    f"Log your actions before stopping."
                ),
            }

        # All checks passed
        return {"decision": "allow"}

    return stop_guard
```

### 5.2 Reporting Lead Stop Guard

The Reporting Lead has different stop conditions -- it must have produced merged outputs, the audit.json, the numerical manifest, and the Excel report.

```python
# src/dd_agents/hooks/stop.py  (continued)

def build_reporting_lead_stop_guard(
    run_dir: Path,
    expected_customers: int,
):
    """Stop guard for the Reporting Lead agent."""

    async def reporting_lead_stop_guard(input_data, tool_use_id, context):
        merged_dir = run_dir / "findings" / "merged"
        audit_dir = run_dir / "audit" / "reporting_lead"

        # Check 1: Merged customer files
        merged_jsons = list(merged_dir.glob("*.json"))
        if len(merged_jsons) < expected_customers:
            return {
                "decision": "block",
                "reason": (
                    f"Only {len(merged_jsons)}/{expected_customers} merged "
                    f"customer JSONs. Complete the merge before stopping."
                ),
            }

        # Check 2: audit.json
        audit_json = run_dir / "audit.json"
        if not audit_json.exists():
            return {
                "decision": "block",
                "reason": (
                    "audit.json not written yet. Run all QA checks and write "
                    "the consolidated audit output before stopping."
                ),
            }

        # Check 3: numerical_manifest.json
        num_manifest = run_dir / "numerical_manifest.json"
        if not num_manifest.exists():
            return {
                "decision": "block",
                "reason": (
                    "numerical_manifest.json not written yet. Build and validate "
                    "the numerical manifest before stopping."
                ),
            }

        # Check 4: Excel report
        report_dir = run_dir / "report"
        xlsx_files = list(report_dir.glob("Due_Diligence_Report_*.xlsx"))
        if not xlsx_files:
            return {
                "decision": "block",
                "reason": (
                    "No Excel report found in report/. Generate the Excel "
                    "report before stopping."
                ),
            }

        # Check 5: Reporting Lead audit log
        rl_audit_log = audit_dir / "audit_log.jsonl"
        if not rl_audit_log.exists() or rl_audit_log.stat().st_size == 0:
            return {
                "decision": "block",
                "reason": (
                    "Reporting Lead audit_log.jsonl missing or empty. "
                    "Write your audit log before stopping."
                ),
            }

        return {"decision": "allow"}

    return reporting_lead_stop_guard
```

### 5.3 Judge Stop Guard

The Judge must have produced `quality_scores.json` with all required sections.

```python
# src/dd_agents/hooks/stop.py  (continued)

import json

def build_judge_stop_guard(run_dir: Path, expected_agents: int = 4):
    """Stop guard for the Judge agent."""

    async def judge_stop_guard(input_data, tool_use_id, context):
        judge_dir = run_dir / "judge"
        scores_path = judge_dir / "quality_scores.json"

        if not scores_path.exists():
            return {
                "decision": "block",
                "reason": (
                    "quality_scores.json not written yet. Complete your review "
                    "and write the quality scores before stopping."
                ),
            }

        try:
            scores = json.loads(scores_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "decision": "block",
                "reason": (
                    "quality_scores.json contains invalid JSON. "
                    "Re-write with valid content."
                ),
            }

        # Must have agent_scores for all 4 specialists
        agent_scores = scores.get("agent_scores", {})
        if len(agent_scores) < expected_agents:
            return {
                "decision": "block",
                "reason": (
                    f"quality_scores.json has scores for {len(agent_scores)} "
                    f"agents, expected {expected_agents}. Score all agents."
                ),
            }

        # Must have spot_checks array
        if "spot_checks" not in scores:
            return {
                "decision": "block",
                "reason": (
                    "quality_scores.json missing 'spot_checks' array. "
                    "Include your spot check results."
                ),
            }

        # Must have contradictions array (even if empty)
        if "contradictions" not in scores:
            return {
                "decision": "block",
                "reason": (
                    "quality_scores.json missing 'contradictions' array. "
                    "Include contradictions (empty array if none found)."
                ),
            }

        return {"decision": "allow"}

    return judge_stop_guard
```

---

## 6. Hook Registration Per Agent Type

### 6.1 Specialist Agents (Legal, Finance, Commercial, ProductTech)

```python
# src/dd_agents/agents/specialist.py  (hook setup excerpt)

def build_specialist_options(
    agent_name: str,
    run_dir: Path,
    project_dir: Path,
    expected_customers: int,
    mcp_server,
    system_prompt: str,
) -> ClaudeAgentOptions:

    hooks = build_hooks_for_agent(
        agent_name=agent_name,
        run_dir=run_dir,
        project_dir=project_dir,
        expected_customers=expected_customers,
    )

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"dd_tools": mcp_server},
        allowed_tools=[
            "Read", "Write", "Bash", "Glob", "Grep",
            "mcp__dd_tools__validate_finding",
            "mcp__dd_tools__validate_gap",
            "mcp__dd_tools__validate_manifest",
            "mcp__dd_tools__verify_citation",
            "mcp__dd_tools__get_customer_files",
            "mcp__dd_tools__resolve_entity",
            "mcp__dd_tools__report_progress",
        ],
        hooks=hooks,
        permission_mode="bypassPermissions",
        cwd=str(project_dir),
        max_turns=200,         # Large customer lists need many turns
    )
```

### 6.2 Judge Agent

```python
# src/dd_agents/agents/judge.py  (hook setup excerpt)

def build_judge_options(
    run_dir: Path,
    project_dir: Path,
    mcp_server,
    system_prompt: str,
) -> ClaudeAgentOptions:

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"dd_tools": mcp_server},
        allowed_tools=[
            "Read", "Write", "Bash", "Glob", "Grep",
            "mcp__dd_tools__verify_citation",
        ],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher="Bash",
                    hooks=[build_bash_guard(project_dir)],
                ),
                HookMatcher(
                    matcher="Write",
                    hooks=[build_write_guard("judge", run_dir, project_dir)],
                ),
            ],
            "Stop": [
                HookMatcher(
                    hooks=[build_judge_stop_guard(run_dir)],
                ),
            ],
        },
        permission_mode="bypassPermissions",
        cwd=str(project_dir),
    )
```

### 6.3 Reporting Lead

```python
# src/dd_agents/agents/reporting_lead.py  (hook setup excerpt)

def build_reporting_lead_options(
    run_dir: Path,
    project_dir: Path,
    expected_customers: int,
    mcp_server,
    system_prompt: str,
) -> ClaudeAgentOptions:

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"dd_tools": mcp_server},
        allowed_tools=[
            "Read", "Write", "Bash", "Glob", "Grep",
            "mcp__dd_tools__validate_finding",
            "mcp__dd_tools__validate_gap",
            "mcp__dd_tools__verify_citation",
            "mcp__dd_tools__resolve_entity",
        ],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher="Bash",
                    hooks=[build_bash_guard(project_dir)],
                ),
                HookMatcher(
                    matcher="Write",
                    hooks=[
                        build_write_guard("reporting_lead", run_dir, project_dir),
                    ],
                ),
            ],
            "Stop": [
                HookMatcher(
                    hooks=[
                        build_reporting_lead_stop_guard(run_dir, expected_customers),
                    ],
                ),
            ],
        },
        permission_mode="bypassPermissions",
        cwd=str(project_dir),
    )
```

Note: The Reporting Lead write guard allows writes to `{RUN_DIR}/findings/merged/`, `{RUN_DIR}/findings/merged/gaps/`, `{RUN_DIR}/audit/reporting_lead/`, `{RUN_DIR}/report/`, `{RUN_DIR}/audit.json`, `{RUN_DIR}/numerical_manifest.json`, and `{RUN_DIR}/file_coverage.json`. Its allowed prefixes are broader than specialist agents.

---

## 7. File Layout Summary

```
src/dd_agents/
  tools/
    __init__.py
    mcp_server.py            # build_mcp_server() factory
    validate_finding.py      # Tool 1
    validate_gap.py          # Tool 2
    validate_manifest.py     # Tool 3
    verify_citation.py       # Tool 4
    get_customer_files.py    # Tool 5 (get_customer_files)
    resolve_entity.py        # Tool 6 (resolve_entity)
    report_progress.py       # Tool 7 (report_progress)
  hooks/
    __init__.py
    factory.py               # build_hooks_for_agent()
    pre_tool.py              # bash_guard, write_guard, aggregate_file_guard
    post_tool.py             # json_validator
    stop.py                  # stop_guard, reporting_lead_stop_guard, judge_stop_guard
```

---

## 8. Hook Return Format Reference

This section summarizes the return format for all hook types. Getting these wrong causes silent failures.

**All hook types (Stop, PreToolUse, PostToolUse) return the same flat format:**

```python
# Block (deny the tool call / force agent to continue / reject output)
return {
    "decision": "block",
    "reason": "Human-readable explanation shown to agent",
}

# Allow (permit the tool call / let agent exit / accept output)
return {
    "decision": "allow",
    "reason": "",
}

# No opinion (fall through to next hook or default behavior)
return {}
```

> **Note:** The SDK internally wraps this in its envelope format (e.g., `hookSpecificOutput`). Hook implementations must return only the flat format shown above. Do NOT nest under `hookSpecificOutput` -- the SDK handles that translation automatically.
