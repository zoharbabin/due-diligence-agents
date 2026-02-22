# Contributing to Due Diligence Agent SDK

## Prerequisites

- Python 3.12+
- pip
- Git
- `pdftotext` (poppler-utils) for document extraction
- `tesseract-ocr` (optional, for scanned PDFs)

## Development Setup

```bash
git clone https://github.com/<org>/due-diligence-agents.git
cd due-diligence-agents
git checkout impl-01
pip install -e ".[dev]"
pre-commit install
```

This installs the package in editable mode with all dev dependencies (pytest, ruff, mypy, pre-commit).

## Branch Conventions

| Prefix | Purpose |
|--------|---------|
| `impl-*` | Implementation phases (e.g., `impl-01`, `impl-02`) |
| `feature/*` | New features branched from an impl or main branch |
| `fix/*` | Bug fixes |

## Running Tests

```bash
make test          # Unit + integration tests
make test-unit     # Unit tests only (fast, no API calls)
make test-e2e      # End-to-end tests (requires API key, slow)
```

## Quality Gates

```bash
make verify        # Runs lint + typecheck + tests (must pass before merge)
make lint          # ruff check + format check
make format        # Auto-format code with ruff
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

1. Branch from `impl-01` (or `main` once the implementation branch is merged).
2. Write tests first, then implement.
3. Ensure `make verify` passes locally before pushing.
4. Add or update tests for any new functionality.
5. Open a PR with a clear description of what changed and why.
6. One approval required to merge.

## License

This project is licensed under Apache 2.0. No CLA is required -- by submitting a PR, you agree that your contributions are licensed under the same terms.
