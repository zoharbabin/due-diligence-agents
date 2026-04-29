# Contributing to Due Diligence Agent SDK

## Prerequisites

- Python 3.12+
- pip
- Git
- `poppler-utils` (optional — fallback for pymupdf PDF extraction failures)
- `tesseract-ocr` (optional — OCR for scanned PDFs)

## Development Setup

```bash
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[dev,pdf]"
pre-commit install
```

This installs the package in editable mode with all dev dependencies (pytest, ruff, mypy, pre-commit).

## Branch Conventions

| Prefix | Purpose |
|--------|---------|
| `main` | Stable release branch |
| `feat/*` | Feature development (e.g., `feat/issue-27-pipeline-optimization`) |
| `fix/*` | Bug fixes |

## Running Tests

```bash
make test              # Unit + integration tests
make test-unit         # Unit tests only (fast, no API calls)
pytest tests/e2e/ -x   # End-to-end tests (requires API key, slow)
```

The project has ~3,600 unit tests, ~60 integration tests, and 24 E2E tests (some skipped without API key). Unit and integration tests require no API key.

## Quality Gates

```bash
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/   # Must pass before merge
ruff check src/ tests/                                                      # Lint only
ruff format src/ tests/                                                     # Auto-format code
```

## Code Style

- **Python 3.12+** with `from __future__ import annotations`
- **Strict mypy** -- all code must pass `mypy src/ --strict`
- **ruff** for linting and formatting
- **120 character** line limit
- **Pydantic v2** models with `Field(description=...)` on every field
- Async functions for pipeline steps
- Tests written **before** implementation (TDD)

Configuration lives in `pyproject.toml` under `[tool.ruff]`, `[tool.mypy]`, and `[tool.pytest.ini_options]`.

## Commit Messages

- Use imperative mood: "Add extraction module", not "Added extraction module"
- Reference issue numbers where applicable: "Fix entity resolution cache miss (#42)"
- Keep the first line under 72 characters
- Add a blank line before any extended description

## Pull Request Process

1. Branch from `main`.
2. Write tests first, then implement.
3. Ensure quality gates pass locally before pushing (`pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`).
4. Add or update tests for any new functionality.
5. Open a PR with a clear description of what changed and why.
6. One approval required to merge.

## Developer Onboarding

1. Read [`docs/plan/PLAN.md`](docs/plan/PLAN.md) for the executive overview.
2. Read [`docs/plan/01-architecture-decisions.md`](docs/plan/01-architecture-decisions.md) for key architectural choices.
3. Read [`docs/plan/18-implementation-order.md`](docs/plan/18-implementation-order.md) for the build sequence.
4. See [`docs/history/IMPLEMENTATION_PLAN.md`](docs/history/IMPLEMENTATION_PLAN.md) for the build sequence history (all 8 phases complete).

### Autonomous Implementation (Claude Code)

This project is structured for autonomous implementation by Claude Code:

- **`CLAUDE.md`** — Project instructions loaded automatically at session start
- **`docs/history/IMPLEMENTATION_PLAN.md`** — Phased build history (all 8 phases complete)
- **`.claude/settings.json`** — Tool permissions and quality gate hooks
- **`.claude/agents/`** — Custom subagents (code-reviewer, test-runner)
- **`scripts/`** — Quality gate scripts (lint, test, type check, pre-commit gate)
- **Quality gate command** — `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`

To start autonomous implementation:
```bash
cd due-diligence-agents
pip install -e ".[dev,pdf]"
claude    # Claude Code reads CLAUDE.md automatically
```

## License

This project is licensed under Apache 2.0. No CLA is required -- by submitting a PR, you agree that your contributions are licensed under the same terms.
