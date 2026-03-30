#!/bin/bash
# Post-edit hook: run ruff on edited Python files
# This hook runs after every Edit/Write operation on Python files.
# It does NOT block — just provides feedback.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)

# Only lint Python files
if [[ "$FILE" == *.py ]]; then
    cd "$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0
    ruff check "$FILE" --fix --quiet 2>/dev/null || true
    ruff format "$FILE" --quiet 2>/dev/null || true
fi

exit 0
