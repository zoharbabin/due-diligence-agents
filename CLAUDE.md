# Due Diligence Agent SDK — Claude Code Instructions

## Project Overview

Python application for forensic M&A due diligence. Analyzes contract data rooms across 4 domains (Legal, Finance, Commercial, ProductTech) using 8 AI agents under a 35-step pipeline with 5 blocking gates. Produces a detailed cross-domain HTML report + 14-sheet Excel report with structured findings, citations, and audit trail. The reports provide granular analysis that deal teams use as the basis for their own deliverables — IC memos, advisor reports, negotiation checklists, or integration plans.

**Package**: `dd-agents` on [PyPI](https://pypi.org/project/dd-agents/) / `dd_agents` under `src/dd_agents/`
**Version**: see `pyproject.toml` (bump version there before tagging a release)
**SDK**: `claude-agent-sdk>=0.1.56` (Python 3.12+, tested on 3.12 and 3.13)
**Spec**: 24 plan docs in `docs/plan/`. Start with `docs/plan/PLAN.md`.

## Commands

```bash
# Install (end users)
pip install dd-agents[pdf]

# Install (development)
pip install -e ".[dev,pdf]"

# Test (run after EVERY change)
pytest tests/unit/ -x -q                    # Unit tests (~3,300, fast, no API)
pytest tests/integration/ -x -q             # Integration tests (mock agents)
pytest tests/e2e/ -x -q                     # E2E tests (requires API, expensive)

# Type check
mypy src/ --strict

# Lint
ruff check src/ tests/
ruff format src/ tests/ --check

# All quality gates at once
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/

# Build package locally
python -m build && twine check dist/*

# Run the pipeline
dd-agents run path/to/deal-config.json
```

## Architecture

- **Orchestrator** (`orchestrator/engine.py`): 35 async steps as methods on `PipelineEngine`. State machine with checkpoint/resume.
- **Agents** (`agents/`): 4 specialists (Legal, Finance, Commercial, ProductTech) + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence. Spawned via `claude-agent-sdk`.
- **Persistence**: Three tiers — PERMANENT (never wiped), VERSIONED (archived per run), FRESH (rebuilt each run).
- **Hooks** (`hooks/`): PreToolUse hooks return flat `{"decision": "block"|"allow", "reason": "..."}`. Stop hooks use SDK format `{"continue_": bool, "stopReason": "..."}`. Never nest under `hookSpecificOutput`. PreToolUse chain: (1) bash_guard, (2) path_guard, (3) file_size_guard, (4) aggregate_file_guard, (5) finding_schema_guard — validates finding JSON structure on Write to `findings/{agent}/*.json`, blocking wrong field names like `evidence` instead of `citations`. Stop hook: check_coverage + check_manifest (relaxed — allows stop when all subject JSONs are written; orchestrator backfills manifests post-session).
- **Models** (`models/`): Pydantic v2 for all schemas. `model_json_schema()` for structured outputs. Note: some BaseModel subclasses live outside `models/` by design — agent output schemas (`agents/*.py`), report templates (`reporting/templates.py`), query models (`query/*.py`), and internal helpers (`orchestrator/batch_scheduler.py`, `validation/pre_merge.py`, `extraction/coordinates.py`) are co-located with their consumers for cohesion.
- **Validation** (`validation/`): 6-layer numerical audit, 31 substantive DoD checks (content-validated, not file-existence). Fail-closed — validation failures block the pipeline.
- **Knowledge** (`knowledge/`): Deal Knowledge Base — persistent knowledge layer that compounds across runs. 12 modules: `base.py` (article CRUD + atomic writes), `articles.py` (Pydantic models), `compiler.py` (findings → articles), `graph.py` (NetworkX knowledge graph), `chronicle.py` (append-only JSONL timeline), `lineage.py` (SHA-256 finding fingerprinting), `health.py` (7-category integrity checks), `prompt_enrichment.py` (agent context builder), `filing.py` (file-back to data room), `search_context.py` (search enrichment interface), `index.py` (auto-maintained JSON index), `_utils.py` (shared helpers). Compiled automatically in step 32 unless `--no-knowledge` is passed.

## Code Style

- Python 3.12+, strict mypy, ruff for lint/format
- Line length: 120 characters
- Pydantic v2 models with Field descriptions for every field
- Async functions for pipeline steps
- All JSON schemas validated via Pydantic `model_validate()`
- `subject_safe_name`: lowercase, strip legal suffixes (Inc/Corp/LLC/Ltd), replace special chars with `_`, collapse underscores. Example: "Smith & Partners, Inc." → `smith_partners`
- Reporting terminology: internal code uses "subject"; HTML/Excel report outputs use "Entity" for external-facing content
- Batch naming is 1-based: `batch_1`, `batch_2` (never `batch_0`)

## CI/CD

Two GitHub Actions workflows in `.github/workflows/`:

### CI (`ci.yml`) — runs on every push/PR to `main`

```
Stage 1 (parallel):   Lint & Format, Type Check (mypy --strict)
Stage 2 (parallel):   Unit Tests (Python 3.12 + 3.13 matrix)
Stage 3 (after 1+2):  Integration Tests
Stage 4 (after 1+2):  Build Package (sdist + wheel + twine check + CLI verify), Build Docker Image
Stage 5 (after 3+4):  E2E Tests (main branch only, requires ANTHROPIC_API_KEY secret)
```

### Release (`release.yml`) — triggered by version tag or manual dispatch

```
Quality Gate → Build Package → Publish to PyPI (OIDC) + Publish Docker to GHCR → GitHub Release
```

**To release a new version:**
1. Bump `version` in `pyproject.toml`
2. Commit and push to `main`
3. `git tag v<version> && git push origin v<version>`

PyPI uses OIDC trusted publishing (no API token needed). Docker images go to `ghcr.io/zoharbabin/due-diligence-agents`. GitHub Release includes wheel + sdist + auto-generated changelog.

## Distribution

| Channel | Install | Automated |
|---------|---------|-----------|
| **PyPI** | `pip install dd-agents[pdf]` | Yes, on version tag |
| **Homebrew** | `brew install zoharbabin/due-diligence-agents/dd-agents` | Yes, formula auto-updated on version tag |
| **Docker (GHCR)** | `docker pull ghcr.io/zoharbabin/due-diligence-agents:latest` | Yes, on version tag |
| **GitHub Releases** | Download wheel/sdist from Releases page | Yes, on version tag |
| **Source** | `git clone` + `pip install -e ".[dev,pdf]"` | N/A |

## Implementation Process

IMPORTANT: Follow these steps for every module:

1. **Read the spec first** — Find the relevant doc in `docs/plan/` for the module you're building. Read it completely.
2. **Write tests first** — Create test file in `tests/unit/` before implementing. Tests define the contract.
3. **Implement minimally** — Write the minimum code to make tests pass.
4. **Run quality gates** — `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`
5. **Commit** — Small, focused commits with clear messages.

## Implementation Plan

All 8 original phases are complete. See `docs/history/IMPLEMENTATION_PLAN.md` for the build history. New features follow the same process (spec → tests → implement → quality gates) but are tracked via GitHub issues and CHANGELOG.md.

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
| `knowledge/*` | Epic #186 (Issues #178-#185, Knowledge Compounding) |

## Don't Do This

- Don't implement a module without reading its spec doc first
- Don't skip tests — write tests BEFORE implementation
- Don't create aggregate files (e.g., `summary.json`, `all_findings.json`) — findings are always per-subject
- Don't use `hookSpecificOutput` wrapper — PreToolUse hooks return flat `{"decision": ..., "reason": ...}`, Stop hooks use `{"continue_": ..., "stopReason": ...}`
- Don't use 0-based batch naming — batches start at 1
- Don't modify PERMANENT tier files during runs (only extraction creates them)
- Don't skip type annotations — `mypy --strict` must pass
- Don't add unnecessary dependencies — check `pyproject.toml` for approved deps
- Don't disable or skip tests — fix them instead
- Don't say "board-ready" about the reports — they produce granular cross-domain analysis used as the basis for deliverables
- Don't frame the tool as replacing advisors — it accelerates their work

## LLM Call Policy

- ALL LLM calls MUST go through `claude_agent_sdk` — never call other clients directly
- Use `query()` with `ClaudeAgentOptions` for all inference
- Single-turn extraction: `max_turns=1`, `disallowed_tools=[...]`
- Multi-turn agents: `max_turns=150-300`, tools enabled per spec
- Each `query()` call is stateless — no context accumulates between calls
- CLI path override: all `ClaudeAgentOptions` must include `cli_path=resolve_sdk_cli_path()` from `dd_agents.utils`. This prefers the system-installed `claude` CLI over the SDK's bundled copy (avoids version-specific bugs). Set `DD_AGENTS_CLI_PATH` env var to override.

## Sensitive Data Policy

- No real company names, people's names, financial data, or addresses in source code, tests, or documentation
- Tests use generic placeholders (`"Subject A"`, `"file_1.pdf"`)
- Example prompts use `"[SUBJECT]"`, `"[DOCUMENT]"`
- Commit messages must not reference real subject data
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
claude-agent-sdk>=0.1.56        # Agent spawning, hooks, tools (>=0.1.56 fixes stream-closed hook errors)
pydantic>=2.0                   # Data models, schema validation
openpyxl>=3.1.3                 # Excel report generation + .xlsx extraction
networkx>=3.0                   # Governance graph (cycle detection, topological sort)
rapidfuzz>=3.0                  # Entity resolution fuzzy matching
markitdown[docx,xlsx,pptx]>=0.1 # PDF/Office document extraction
xlrd>=2.0                       # Legacy .xls (BIFF) extraction
scikit-learn>=1.3               # TF-IDF vectorization for entity resolution
click>=8.0                      # CLI interface
rich>=13.0                      # Terminal output formatting
```

Optional: `pymupdf>=1.23` (PDF extraction, AGPL-3.0), `chromadb>=0.4` (vector search), `pytesseract>=0.3` + `Pillow>=12.1` + `pdf2image>=1.16` (OCR), `mlx-vlm>=0.1` + `pypdfium2>=4.0` (GLM-OCR)

## Repo Structure (non-code files)

| File | Purpose |
|------|---------|
| `README.md` | Public-facing project overview and quick start |
| `CLAUDE.md` | This file — Claude Code instructions |
| `CONTRIBUTING.md` | Development setup, code style, PR process |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.0 |
| `SECURITY.md` | Vulnerability reporting policy |
| `CHANGELOG.md` | Version history |
| `docs/history/IMPLEMENTATION_PLAN.md` | Phased build plan (archived — all 8 phases complete) |
| `.github/workflows/ci.yml` | CI pipeline (lint, types, tests, build) |
| `.github/workflows/release.yml` | Release pipeline (PyPI, Docker, GitHub Release) |
| `.github/FUNDING.yml` | GitHub Sponsors configuration |
| `Dockerfile` | Multi-stage Docker build |
| `pyproject.toml` | Package metadata, dependencies, tool config |
