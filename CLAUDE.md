# Due Diligence Agent SDK — Claude Code Instructions

## Project Overview

Python application for forensic M&A due diligence. 8 AI agents (4 domain specialists + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence) analyze contract data rooms under a 35-step pipeline with 5 blocking gates, producing a detailed cross-domain HTML report + 14-sheet Excel report. The 4 specialists (Legal, Finance, Commercial, ProductTech) share a base runner but are differentiated by substantive domain-specific prompts and 18 canonical clause types. Python orchestrates; agents are workers.

**Package**: `dd_agents` under `src/dd_agents/`
**SDK**: `claude-agent-sdk` v0.1.39+ (Python 3.12+)
**Spec**: 24 plan docs in `docs/plan/`. Start with `docs/plan/PLAN.md`.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Test (run after EVERY change)
pytest tests/unit/ -x -q                    # Unit tests (fast, no API)
pytest tests/integration/ -x -q             # Integration tests (mock agents)
pytest tests/e2e/ -x -q                     # E2E tests (requires API, expensive)

# Type check
mypy src/ --strict

# Lint
ruff check src/ tests/
ruff format src/ tests/ --check

# All quality gates at once
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/

# Run the pipeline
dd-agents run path/to/deal-config.json
```

## Architecture

- **Orchestrator** (`orchestrator/engine.py`): 35 async steps as methods on `PipelineEngine`. State machine with checkpoint/resume.
- **Agents** (`agents/`): 4 specialists (Legal, Finance, Commercial, ProductTech) + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence. Spawned via `claude-agent-sdk`.
- **Persistence**: Three tiers — PERMANENT (never wiped), VERSIONED (archived per run), FRESH (rebuilt each run).
- **Hooks** (`hooks/`): Flat return format `{"decision": "block"|"allow", "reason": "..."}` for ALL hook types. Never nest under `hookSpecificOutput`.
- **Models** (`models/`): Pydantic v2 for all schemas. `model_json_schema()` for structured outputs.
- **Validation** (`validation/`): 6-layer numerical audit, 31 substantive DoD checks (content-validated, not file-existence). Fail-closed — validation failures block the pipeline.

## Code Style

- Python 3.12+, strict mypy, ruff for lint/format
- Line length: 120 characters
- Pydantic v2 models with Field descriptions for every field
- Async functions for pipeline steps
- All JSON schemas validated via Pydantic `model_validate()`
- `customer_safe_name`: lowercase, strip legal suffixes (Inc/Corp/LLC/Ltd), replace special chars with `_`, collapse underscores. Example: "Smith & Partners, Inc." → `smith_partners`
- Reporting terminology: internal code uses "customer"; HTML/Excel report outputs use "Entity" for external-facing content
- Batch naming is 1-based: `batch_1`, `batch_2` (never `batch_0`)

## Implementation Process

IMPORTANT: Follow these steps for every module:

1. **Read the spec first** — Find the relevant doc in `docs/plan/` for the module you're building. Read it completely.
2. **Write tests first** — Create test file in `tests/unit/` before implementing. Tests define the contract.
3. **Implement minimally** — Write the minimum code to make tests pass.
4. **Run quality gates** — `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`
5. **Commit** — Small, focused commits with clear messages.

## Implementation Plan

Follow `IMPLEMENTATION_PLAN.md` in the project root. Execute ONE phase at a time. Each phase has:
- Specific files to create
- Spec docs to read for each file
- Test files to write
- Acceptance criteria to verify
- Status tracking

Update the phase status in IMPLEMENTATION_PLAN.md after completing each phase.

## Key Spec References

| Module | Primary Spec Doc |
|--------|-----------------|
| `models/*` | `docs/plan/04-data-models.md` |
| `entity_resolution/*` | `docs/plan/09-entity-resolution.md` |
| `extraction/*` | `docs/plan/08-extraction.md` + `docs/plan/22-llm-robustness.md §7` |
| `persistence/*` | `docs/plan/02-system-architecture.md §3` |
| `inventory/*` | `docs/plan/08-extraction.md §2-3` |
| `hooks/*` | `docs/plan/07-tools-and-hooks.md` |
| `tools/*` | `docs/plan/07-tools-and-hooks.md` |
| `orchestrator/*` | `docs/plan/05-orchestrator.md` |
| `agents/*` | `docs/plan/06-agents.md` |
| `reporting/*` | `docs/plan/10-reporting.md` (Excel + merge) |
| `reporting/html*.py` | `docs/plan/10-reporting.md` + PR #112 description (HTML renderers) |
| `validation/*` | `docs/plan/11-qa-validation.md` |
| `vector_store/*` | `docs/plan/14-vector-store.md` |
| `search/*` | `docs/plan/22-llm-robustness.md` + `docs/search-guide.md` |
| `errors.py` | `docs/plan/12-error-recovery.md` |
| `cli.py` | `docs/plan/03-project-structure.md` |
| `reasoning/*` | `docs/plan/21-ontology-and-reasoning.md` |
| `persistence/project_registry.py` | `docs/plan/13-multi-project.md` |
| `reporting/templates.py` | Issue #123 (Configurable Report Templates) |
| `precedence/*` | Issue #163 (Document Precedence Engine) |

## Don't Do This

- Don't implement a module without reading its spec doc first
- Don't skip tests — write tests BEFORE implementation
- Don't create aggregate files (e.g., `summary.json`, `all_findings.json`) — findings are always per-customer
- Don't use `hookSpecificOutput` wrapper — all hooks return flat `{"decision": ..., "reason": ...}`
- Don't use 0-based batch naming — batches start at 1
- Don't modify PERMANENT tier files during runs (only extraction creates them)
- Don't skip type annotations — `mypy --strict` must pass
- Don't add unnecessary dependencies — check `pyproject.toml` for approved deps
- Don't disable or skip tests — fix them instead

## LLM Call Policy

- ALL LLM calls MUST go through `claude_agent_sdk` — never call other clients directly
- Use `query()` with `ClaudeAgentOptions` for all inference
- Single-turn extraction: `max_turns=1`, `disallowed_tools=[...]`
- Multi-turn agents: `max_turns=150-300`, tools enabled per spec
- Each `query()` call is stateless — no context accumulates between calls

## Sensitive Data Policy

- No real company names, people's names, financial data, or addresses in source code, tests, or documentation
- Tests use generic placeholders (`"Customer A"`, `"file_1.pdf"`)
- Example prompts use `"[CUSTOMER]"`, `"[DOCUMENT]"`
- Commit messages must not reference real customer data
- No data room content in source, tests, or commits

## Search Module Guidelines

- **Zero files skipped for size**: chunk oversized files, never skip them
- **Page-aware chunking**: split at `--- Page N ---` markers with 15% overlap
- **Target 150K chars per chunk** (aligned with AG-1 finding: smaller context = higher accuracy)
- **4-phase analysis**: map (per chunk) → merge → synthesis (conflicts only) → validation (NOT_ADDRESSED)
- **Citation accuracy**: every answer must include file_path, page, section_ref, exact_quote
- **Cross-document precedence**: derived from contract clauses, not assumed hierarchy
- Spec docs: `docs/plan/22-llm-robustness.md`, `docs/search-guide.md`

## When Stuck (After 3 Attempts)

1. Document what failed (what you tried, specific errors, why it failed)
2. Check if there's a simpler approach that still satisfies the spec
3. Check `docs/plan/12-error-recovery.md` for error handling patterns
4. If the issue is in a dependency (claude-agent-sdk, openpyxl, etc.), check their docs
5. Create a minimal reproducer and isolate the problem

## Dependencies

All core dependencies are permissively licensed (Apache 2.0, MIT, BSD). pymupdf is AGPL-3.0 and optional.

```
claude-agent-sdk>=0.1.39   # Agent spawning, hooks, tools
pydantic>=2.0              # Data models, schema validation
openpyxl>=3.1.3            # Excel report generation
networkx>=3.0              # Governance graph (cycle detection, topological sort)
rapidfuzz>=3.0             # Entity resolution fuzzy matching
markitdown>=0.1            # PDF/Office document extraction
scikit-learn>=1.3          # TF-IDF vectorization for entity resolution
click>=8.0                 # CLI interface
rich>=13.0                 # Terminal output formatting
```

Optional: `pymupdf>=1.23` (PDF extraction, AGPL-3.0), `chromadb>=0.4` (vector search), `pytesseract>=0.3` (OCR), `mlx-vlm>=0.1` (GLM-OCR)
