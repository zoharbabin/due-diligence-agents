#!/bin/bash
# Harness for the "Roadmap: Discoverability & DX" milestone (issue #269 spec).
# Runs 6 independent gates, in order, and fails loud on the first non-zero exit.
# Permanent regression gate for this area — re-run on every future change here.
set -eo pipefail

cd "$(git rev-parse --show-toplevel)"

OUT_DIR=".dx-harness-out"
mkdir -p "$OUT_DIR"

echo "=== Gate 1: Lint ==="
python -m ruff check src/ tests/ | tee "$OUT_DIR/01-lint.log"

echo "=== Gate 2: SAST (bandit) ==="
python -m bandit -r src/dd_agents -ll -q | tee "$OUT_DIR/02-bandit.log"

echo "=== Gate 3: Multi-instance isolation ==="
python -m pytest tests/unit/test_dx_harness_isolation.py -x -q | tee "$OUT_DIR/03-isolation.log"

echo "=== Gate 4: Dead-code scan (vulture, diffed against known baseline) ==="
python -m vulture src/dd_agents --min-confidence 80 > "$OUT_DIR/04-vulture.log" || true
# Strip line numbers before comparing -- pre-existing findings shift lines as
# unrelated code changes; only a change in file/message signals real new dead code.
sed -E 's/^([^:]+):[0-9]+:/\1:/' "$OUT_DIR/04-vulture.log" > "$OUT_DIR/04-vulture-normalized.log"
if ! diff -u scripts/dx-harness-vulture-baseline.txt "$OUT_DIR/04-vulture-normalized.log"; then
    echo "New dead code found beyond the pre-existing baseline -- see diff above." >&2
    exit 1
fi
cat "$OUT_DIR/04-vulture.log"

echo "=== Gate 5: Unit/integration tests + strict types ==="
python -m pytest tests/unit/ -x -q | tee "$OUT_DIR/05-unit.log"
python -m mypy src/ --strict | tee -a "$OUT_DIR/05-unit.log"

echo "=== Gate 6: E2E flow (diff + --json parity, no API key needed) ==="
python -m pytest tests/e2e/test_discoverability_dx_flow.py -x -q -m "not e2e and not eval" | tee "$OUT_DIR/06-e2e.log"

echo "=== All discoverability-dx gates passed ==="
