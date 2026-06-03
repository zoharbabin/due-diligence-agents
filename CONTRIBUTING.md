# Contributing to Due Diligence Agent SDK

## Prerequisites

- Python 3.12+ and pip
- Git
- Optional system packages for extraction: `poppler-utils`, `tesseract-ocr`

## Development Setup

```bash
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[dev,pdf]"
pre-commit install
```

This installs the package in editable mode with all dev dependencies.

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

Unit and integration tests require no API key. E2E tests require `ANTHROPIC_API_KEY`.

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

## Quick Contributions

For documentation fixes, typo corrections, or small improvements that don't change
runtime behavior:

1. Fork the repo and make your change.
2. Run `ruff check src/ tests/` (no test suite needed for doc-only changes).
3. Open a PR with a one-line description.

Look for issues labeled [`good first issue`](https://github.com/zoharbabin/due-diligence-agents/labels/good%20first%20issue) for
beginner-friendly tasks.

## Pull Request Process

1. Branch from `main`.
2. Write tests first, then implement.
3. Ensure quality gates pass locally: `make verify` (or `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/`).
4. Add or update tests for any new functionality.
5. Open a PR with a clear description of what changed and why.
6. One approval required to merge.

## Developer Onboarding

1. Read [`CLAUDE.md`](CLAUDE.md) — the Architecture Map, Design Rules, and Key Patterns are the fast orientation to the codebase, commands, and code style.
2. The code under `src/dd_agents/` is authoritative for current behavior; each package's entry point is listed in the Architecture Map.

### Autonomous Implementation (Claude Code)

This project is structured for autonomous implementation by Claude Code:

- **`CLAUDE.md`** — Project instructions loaded automatically at session start
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
