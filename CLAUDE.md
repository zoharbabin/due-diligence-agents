# Due Diligence Agent SDK

Forensic M&A due diligence pipeline — analyzes contract data rooms with specialist AI agents, enforces quality gates, produces cross-domain HTML + Excel reports.

## Commands

```bash
pip install -e ".[dev,pdf]"                                          # Dev install
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/  # Quality gate (run after EVERY change)
dd-agents run path/to/deal-config.json                               # Run pipeline
dd-agents run path/to/deal-config.json --dry-run                     # Preview steps
dd-agents validate path/to/deal-config.json                          # Validate config
```

## Architecture Map

All source lives under `src/dd_agents/`. Each package has one job:

| Package | Purpose | Entry point |
|---------|---------|-------------|
| `orchestrator/` | 38-step async pipeline with checkpoint/resume | `engine.py` → `PipelineEngine.run()` |
| `agents/` | Specialist agent runners + extensible registry | `base.py` → `BaseAgentRunner` (abstract) |
| `models/` | Pydantic v2 schemas for all data | `__init__.py` re-exports ~100 classes |
| `reporting/` | HTML + Excel report generation | `html_base.py` → `SectionRenderer` (abstract) |
| `hooks/` | Pre/post tool-use guards (allow/block) | `pre_tool.py` → guard functions |
| `persistence/` | Three-tier data lifecycle | `tiers.py` → `TierManager` |
| `knowledge/` | Deal knowledge base (compounds across runs) | `base.py` → `DealKnowledgeBase` |
| `customization/` | User-editable agent personas/profiles (`dd-config/`) | `loader.py` → `resolve_chain()`, `profiles/*.md` |
| `extraction/` | PDF/Office text extraction pipeline | `pipeline.py` → fallback chain |
| `entity_resolution/` | Cross-document name deduplication | `matcher.py` → `EntityResolver` |
| `inventory/` | Data room scanning and classification | `discovery.py`, `subjects.py` |
| `validation/` | QA audit + DoD checks (fail-closed) | `dod.py`, `numerical_audit.py` |
| `search/` | Contract search with citation verification | `runner.py` → `SearchRunner` |
| `tools/` | MCP server + custom tool implementations | `mcp_server.py` |
| `chat/` | Interactive chat mode | `engine.py` |
| `cli.py` | Click CLI command groups | `dd-agents` entry point |

## Design Rules

These are mechanical constraints, not guidelines:

1. **All LLM calls go through `claude_agent_sdk`** — `query()` with `ClaudeAgentOptions`. Never call other clients. Always include `cli_path=resolve_sdk_cli_path()` from `dd_agents.utils`.
2. **Findings are per-subject** — one JSON file per subject at `findings/{agent_name}/{subject_safe_name}.json`. Never create aggregate files (`summary.json`, `all_findings.json`).
3. **Hook format is flat** — PreToolUse: `{"decision": "allow"|"block", "reason": "..."}`. Stop: `{"continue_": bool, "stopReason": "..."}`. Never nest under `hookSpecificOutput`.
4. **Three persistence tiers** — PERMANENT (never wiped: text index, entity cache), VERSIONED (archived per run: findings, reports), FRESH (rebuilt each run: inventory). Never modify PERMANENT tier during pipeline runs.
5. **Batch naming is 1-based** — `batch_1`, `batch_2`. Never `batch_0`.
6. **`subject_safe_name` transform** — lowercase, strip legal suffixes (Inc/Corp/LLC/Ltd), replace special chars with `_`, collapse underscores. "Smith & Partners, Inc." → `smith_partners`.
7. **Reporting terminology** — internal code: "subject". HTML/Excel output: "Entity".
8. **Quality gates are fail-closed** — validation failures block the pipeline. No bypass.
9. **Tests before implementation** — write test file in `tests/unit/` first. Tests define the contract.
10. **Strict types** — `mypy --strict` must pass. No `type: ignore` without justification.
11. **One safety floor, appended last** — every assembled prompt ends with `assemble_safety_floor()` (`agents/prompt_constants.py`): anti-sub-agent constraints, citation mandate, anti-fabrication, untrusted-document rule. It is concatenated after all user customization, so config can never remove it. Wrap untrusted data-room content with `wrap_untrusted()`.
12. **One severity authority** — final severity is decided once by `resolve_severity()` (`reporting/severity_resolver.py`) in the merge write path: `llm → recalibration (down-only) → bounded user_override`. Records `metadata.provenance.severity_source` + `severity_chain`. `computed_metrics._recalibrate_severity` is a read-only guard that no-ops when `severity_source` is set. Never re-derive severity elsewhere.
13. **Severity thresholds are constants** — TfC/CoC/ARR numbers live only in `agents/severity_thresholds.py`. Build threshold strings via f-strings off them; never hardcode the literal in prose.
14. **User-editable agent config is data under `dd-config/`** — one folder, one format (YAML front-matter + markdown), one merge rule (`customization/loader.py:resolve_chain`: built-in → profile `extends` chain → `dd-config/agents/{agent}.md` → deal). Inspect with `dd-agents agents describe|list|validate|preview`.
15. **Provenance is one hash** — `persistence/provenance.py:compute_provenance_hash` (config + prompt_version + persona hashes). Resume is fail-closed: a checkpoint whose provenance drifted is rejected. All config hashing routes through `compute_config_hash` (never raw file bytes).

## Key Patterns

### Adding a new specialist agent

1. Create `src/dd_agents/agents/{domain}.py`
2. Subclass `BaseAgentRunner` — implement three abstract methods:
   ```python
   def get_agent_name(self) -> str: ...      # e.g. "legal"
   def get_system_prompt(self) -> str: ...   # domain-specific prompt
   def get_tools(self) -> list[str]: ...     # allowed MCP tools
   ```
3. Register via `AgentRegistry.register(AgentDescriptor(...))` at module level
4. Agent auto-discovered when module imported (built-in) or via `dd_agents.specialists` entry-point (external)

### Adding a new HTML report section

1. Create `src/dd_agents/reporting/html_{section}.py`
2. Subclass `SectionRenderer` — implement `render(self) -> str`
3. Use inherited helpers: `self.escape(text)`, `self.severity_badge(sev)`, `self.render_alert(level, title, body)`
4. `render_alert` already escapes — do NOT pre-escape strings passed to it
5. Wire into `src/dd_agents/reporting/html.py` render pipeline

### Adding a new pipeline step

1. Add enum value to `src/dd_agents/orchestrator/steps.py` → `PipelineStep`
2. Add async method `_step_NN_name(self, state: PipelineState) -> PipelineState` on `PipelineEngine`
3. Register in `_build_step_registry()` mapping

### Pre-tool hook guard pattern

```python
# src/dd_agents/hooks/pre_tool.py
def my_guard(tool_name: str, tool_input: dict[str, Any], ...) -> dict[str, str]:
    if should_block:
        return {"decision": "block", "reason": "why"}
    return {"decision": "allow", "reason": ""}
```

Wire in `src/dd_agents/hooks/factory.py`.

## Environment

**Required:** `ANTHROPIC_API_KEY` (or AWS Bedrock credentials for `claude-agent-sdk`)

**Optional overrides:** All use `DD_` prefix. See `src/dd_agents/utils/constants.py` for defaults. Key ones:
- `DD_AGENTS_CLI_PATH` — override SDK CLI binary path
- `DD_QUOTE_MATCH_THRESHOLD` — fuzzy citation match score (default 80)
- `DD_FUZZY_THRESHOLD_LONG` — entity resolution threshold for long names (default 88)

Full list: grep `DD_` in `src/dd_agents/utils/constants.py` and `src/dd_agents/search/analyzer.py`.

## Reference Docs

| Doc | When to read |
|-----|-------------|
| `docs/plan/PLAN.md` | First time touching this codebase — executive overview of WHY |
| `docs/plan/01-architecture-decisions.md` | When questioning a design choice — ADRs with rationale |
| `docs/agent-customization.md` | Customizing agent personas/severity/profiles via `dd-config/` |
| `docs/user-guide/cli-reference.md` | Adding/modifying CLI commands |
| `docs/user-guide/deal-configuration.md` | Changing config schema or adding config options |
| `docs/search-guide.md` | Working on search module — chunking, citation, precedence |
| `docs/knowledge-architecture.md` | Working on knowledge base — research foundations |
| `docs/plan/12-error-recovery.md` | Adding error handling — 15 error scenarios with patterns |

Plan docs (`docs/plan/02-22`) are **historical design specs**. Code is authoritative for current behavior; plan docs explain design rationale only.

## Don't Do This

- Don't implement without reading the relevant plan doc for WHY context
- Don't create aggregate finding files — always per-subject
- Don't use `hookSpecificOutput` wrapper — flat format only
- Don't modify PERMANENT tier during runs
- Don't skip tests or disable them — fix them
- Don't say "board-ready" about reports — they provide analysis used as basis for deliverables
- Don't frame the tool as replacing advisors — it accelerates their work
- Don't add dependencies without checking `pyproject.toml` for existing alternatives

## CI/CD

Two workflows in `.github/workflows/`:
- `ci.yml` — lint, types, unit tests (3.12 + 3.13 matrix), integration, build, E2E
- `release.yml` — triggered by version tag → PyPI (OIDC) + Docker (GHCR) + GitHub Release

**To release:** bump version in `pyproject.toml` → commit → `git tag v<version> && git push origin v<version>`

## Sensitive Data Policy

No real company names, financial data, or PII in source, tests, or docs. Tests use placeholders (`"Subject A"`, `"file_1.pdf"`). Commit messages must not reference real subject data.
