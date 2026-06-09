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
| `agents/prompts/` | Built-in prompt prose as editable markdown (specialists, synthesis, search, auto-config) | `loader.py` → `load_builtin_specialist()` |
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

1. **All LLM calls go through the seam** — build options with `dd_agents.llm.build_agent_options(...)`, then `claude_agent_sdk.query()`. Never construct `ClaudeAgentOptions` directly and never call other clients. The seam sets `cli_path`, the output-token clamp, and an explicit `model` when one is resolved (deal/env override); `model=None` deliberately inherits the provider/CLI default. dd-agents is provider- AND model-agnostic by config: provider/model are env-selected (Anthropic API / Bedrock / Vertex natively, or **any** model behind an Anthropic-compatible gateway via `ANTHROPIC_BASE_URL`) — never hardcode a vendor. See `dd_agents/llm/provider.py` and `docs/user-guide/model-providers.md`. Enforced by `tests/unit/test_docs_drift.py` (no `ClaudeAgentOptions(` constructed outside the seam).
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
13. **Severity thresholds are constants** — TfC/CoC/ARR numbers live only in `agents/severity_thresholds.py`. In Python build threshold strings via f-strings off them; in prompt markdown use `{COC_REVENUE_PCT}`-style placeholders resolved by `agents/prompts/loader.py:resolve_thresholds`. Never hardcode the literal number in prose.
14. **User-editable agent config is data under `dd-config/`** — one folder, one format (YAML front-matter + markdown), one merge rule (`customization/loader.py:resolve_chain`: built-in → profile `extends` chain → `dd-config/agents/{agent}.md` → deal). Inspect with `dd-agents agents describe|list|validate|preview`.
15. **Provenance is one hash** — `persistence/provenance.py:compute_provenance_hash` (config + prompt_version + persona hashes). Resume is fail-closed: a checkpoint whose provenance drifted is rejected. All config hashing routes through `compute_config_hash` (never raw file bytes).
16. **Built-in prompt prose is editable markdown** — specialist personas/focus/domain-guidance, synthesis roles, search-column templates, and auto-config prompts live in `agents/prompts/**/*.md` (the base layer the `dd-config/` chain stacks onto), loaded via `agents/prompts/loader.py`. The safety floor (rule 11) is the exception — it stays code-enforced, never in editable markdown. Editing a prompt's prose must keep assembled output stable or re-capture `tests/golden/` via `scripts/capture_prompt_golden.py` and bump `PromptBuilder.PROMPT_VERSION`.

## Key Patterns

### Adding a new specialist agent

1. Write the prose in `src/dd_agents/agents/prompts/specialists/{domain}.md` (`## Role` / `## Specialist Focus` / `## Domain Guidance`; use `{COC_REVENUE_PCT}`-style placeholders for severity numbers — rule 13)
2. Create `src/dd_agents/agents/{domain}.py`, subclass `BaseAgentRunner`, and back the prompt methods with the loader:
   ```python
   def get_agent_name(self) -> str: ...      # e.g. "legal"
   def get_system_prompt(self) -> str:        # load prose + code-append SEVERITY_PREAMBLE
       return load_builtin_specialist("legal").role + " " + SEVERITY_PREAMBLE
   def get_tools(self) -> list[str]: ...     # allowed MCP tools
   ```
3. Register via `AgentRegistry.register(AgentDescriptor(...))` at module level (source `specialist_focus`/`domain_robustness` from `load_builtin_specialist`)
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

## Documentation Standards

Docs are a contract with the reader. Edit them by the same rules as code.

**Core directives:**
1. **Zero drift.** Every claim must match current code. Verify against source before writing; never describe intended behavior as if shipped.
2. **No secrets, ever.** No real company names, people (except the author, Zohar Babin), financials, PII, tokens, or internal hostnames — in any doc, including marketing. See Sensitive Data Policy.
3. **Remove what rots.** Delete or re-frame docs that no longer reflect the code. A stale doc is worse than no doc.
4. **Point, don't duplicate.** Link to the one authoritative source (a file path, `.env.example`, another doc) instead of copying facts that will drift.

**Anti-drift — exclude these from prose** (they change without the doc changing, so they go stale silently):
- Release/package version numbers (e.g. `1.8.0`) — point to [Releases](https://github.com/zoharbabin/due-diligence-agents/releases). *Schema contracts like `"config_version": "1.0.0"` and language floors like `Python 3.12+` are stable and fine.*
- Hardcoded line counts and file counts.
- Exhaustive tool-name / CLI-command / env-var lists and env-var **default-value** tables — defer to `.env.example` and `grep DD_ src/dd_agents/utils/constants.py`.
- Dependency lists — defer to `pyproject.toml`.
- Architecture diagrams duplicated in many places — prefer the `CLAUDE.md` Architecture Map (text, source-referenced) and link to it.
- No standalone changelog file — GitHub Releases is the changelog.

Instead, reference **stable contracts**: interface/class names, file paths, enum names. Those are what the code-drift guard can check.

**Structure (user-facing docs):** one-line description → copy-paste commands (zero prose) → single-line architecture-map annotations → mechanical design rules ("if X, route to Y") → exact how-tos with file paths + function names → key patterns (signatures, pipeline stages) → environment (required vs optional, defer full list to `.env.example`) → reference guide (*when* to read which doc). CLAUDE.md (this file) is the worked example.

**Architecture-count claims** (specialists, total agents, pipeline steps, blocking gates, Excel sheets) and the **published Docker image name** are the few numbers docs may state — because `tests/unit/test_docs_drift.py` derives them from code and **fails CI** if a doc drifts. If you add a specialist / agent / step / gate / sheet, the docs that cite the count must change in the same PR or the gate blocks you. Same file enforces: every MCP `@tool` has a non-empty description, and side-effecting tools (`save_memory`, `flag_finding`, `extract_document`, `run_export_script`) declare their write/effect in the description the model sees.

**Tool annotations** (`tools/mcp_server.py`): the `@tool(name, description, schema)` description must match runtime behavior and name any side effect / write. Keep read-only and writing tools distinct; never bury a destructive action behind a generic flag.

## Reference Docs

| Doc | When to read |
|-----|-------------|
| `docs/agent-customization.md` | Customizing agent personas/severity/profiles via `dd-config/` |
| `docs/user-guide/cli-reference.md` | Adding/modifying CLI commands |
| `docs/user-guide/deal-configuration.md` | Changing config schema or adding config options |
| `docs/search-guide.md` | Working on search module — chunking, citation, precedence |
| `docs/knowledge-architecture.md` | Working on knowledge base — research foundations |

The Architecture Map and Key Patterns above are the fast orientation to the codebase; the code under `src/dd_agents/` is authoritative for current behavior.

## Don't Do This

- Don't create aggregate finding files — always per-subject
- Don't use `hookSpecificOutput` wrapper — flat format only
- Don't modify PERMANENT tier during runs
- Don't skip tests or disable them — fix them
- Don't say "board-ready" about reports — they provide analysis used as basis for deliverables
- Don't frame the tool as replacing advisors — it accelerates their work
- Don't add dependencies without checking `pyproject.toml` for existing alternatives
- Don't hardcode release versions, counts, or env-var defaults in docs — see Documentation Standards
- Don't describe planned/unshipped behavior as if it ships — docs reflect current code only

## CI/CD

Three workflows in `.github/workflows/`:
- `ci.yml` — lint, types, unit tests (3.12 + 3.13 matrix), integration, build, E2E
- `release.yml` — triggered by version tag → PyPI (OIDC) + Docker (GHCR + Docker Hub) + Homebrew formula bump + GitHub Release
- `pages.yml` — builds and deploys the MkDocs site to GitHub Pages on pushes to `main` touching `docs/`, `mkdocs.yml`, or `CONTRIBUTING.md` (also manual via `workflow_dispatch`)

Docs drift is enforced inside the unit gate: `tests/unit/test_docs_drift.py` runs in both workflows (no separate job), so a doc that contradicts code-derived architecture counts, the published Docker image, or MCP tool-annotation contracts fails CI.

**To release:** bump version in `pyproject.toml` → commit → `git tag v<version> && git push origin v<version>`

## Sensitive Data Policy

No real company names, financial data, or PII in source, tests, or docs. Tests use placeholders (`"Subject A"`, `"file_1.pdf"`). Commit messages must not reference real subject data.
