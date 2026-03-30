#!/bin/bash
# Run all quality gates. Use this to verify before committing.
set -e

cd "$(git rev-parse --show-toplevel)"

echo "=== Unit Tests ==="
python -m pytest tests/unit/ -x -q

echo "=== Type Check ==="
python -m mypy src/ --strict

echo "=== Lint ==="
python -m ruff check src/ tests/

echo "=== All quality gates passed ==="
