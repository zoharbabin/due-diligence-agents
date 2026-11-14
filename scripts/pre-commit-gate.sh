#!/bin/bash
# Pre-commit gate: block git commit unless tests, type checks and lint pass.
# Registered as a PreToolUse hook on Bash with `if: Bash(git commit *)`.
# `if` is best-effort, so the command check below stays as the enforcing guard.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only gate git commit commands
if echo "$COMMAND" | grep -q "git commit"; then
    cd "$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0

    # Run a check; on failure, print the last lines of its output and block (exit 2).
    run_gate() {
        local label="$1"; shift
        local out
        if ! out=$("$@" </dev/null 2>&1); then
            {
                echo "BLOCKED: $label failed. Fix it before committing."
                echo "$out" | tail -n 30
            } >&2
            exit 2
        fi
    }

    run_gate "Unit tests (pytest tests/unit/ -x)" python -m pytest tests/unit/ -x -q --tb=short
    run_gate "Type check (mypy src/ --strict)" python -m mypy src/ --strict --no-error-summary
    run_gate "Lint (ruff check src/ tests/)" python -m ruff check src/ tests/ --quiet
fi

exit 0
