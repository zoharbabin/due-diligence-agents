#!/bin/bash
# Pre-commit gate: block git commit unless tests and type checks pass.
# This hook fires before every Bash command. It only activates for git commit.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only gate git commit commands
if echo "$COMMAND" | grep -q "git commit"; then
    cd "$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0

    # Run unit tests (stdin redirected to /dev/null to avoid depleted stdin issues)
    if ! python -m pytest tests/unit/ -x -q --tb=no </dev/null 2>/dev/null; then
        echo "BLOCKED: Unit tests must pass before committing. Run: pytest tests/unit/ -x" >&2
        exit 2
    fi

    # Run type check
    if ! python -m mypy src/ --strict --no-error-summary </dev/null 2>/dev/null; then
        echo "BLOCKED: Type check must pass before committing. Run: mypy src/ --strict" >&2
        exit 2
    fi

    # Run lint
    if ! python -m ruff check src/ tests/ --quiet </dev/null 2>/dev/null; then
        echo "BLOCKED: Lint must pass before committing. Run: ruff check src/ tests/" >&2
        exit 2
    fi
fi

exit 0
