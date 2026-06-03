# Eval Datasheet

A datasheet for the golden evaluation set that measures specialist-agent
quality. It describes what the dataset contains, how it is used, and the
regression gate that protects against quality drift.

All evaluation data is **synthetic**. No real company names, financial data, or
PII appears in the set, per the project's sensitive-data policy. Subjects use
placeholders such as "Subject A" and "Acme".

---

## What it contains

The golden set lives under `tests/evals/ground_truth/`:

- `contracts/` — synthetic contract documents, one markdown file per scenario.
  They cover golden-path cases (e.g. change-of-control, revenue schedules, SLAs,
  IP assignment, DPAs), cross-domain cases, sparse/minimal documents, and
  adversarial false-positive traps.
- `expected/{agent}/{contract}.json` — the expected result for each contract,
  per agent. Each file declares:
  - `expected_findings` — the findings an agent should produce, each with a
    `category`, a severity **range** (`min_severity`/`max_severity`),
    `must_contain_keywords` (with optional `keyword_synonyms`), a
    `citation_must_reference` file, and a `required` flag.
  - `expected_gaps` — gap types the agent should report (e.g. `Missing_Doc`).
  - `must_not_find` — adversarial guards: categories the agent must **not**
    report on this document, each with a `reason`. These catch false positives
    and category-confusion (for example, an employee-handbook document must not
    yield a contract-`termination` finding).
  - Adversarial files may also set `ambiguity_zone`, `min_expected_findings`,
    and `max_expected_findings`.

---

## Metrics

Per-agent metrics are computed by `tests/evals/metrics.py` and stored as the
baseline in `tests/evals/baselines/latest.json`:

- `finding_recall` — fraction of required expected findings that were produced.
- `finding_precision` — fraction of produced findings that were expected.
- `citation_accuracy` — fraction of findings whose citation references the
  correct source.
- `severity_accuracy` — fraction of findings whose severity falls in the
  expected range.
- `false_positive_rate` — fraction of produced findings that hit a
  `must_not_find` guard.
- `f1_score` — harmonic mean of recall and precision.

The baseline file also records a `finding_count` per agent, plus the `commit`
and `timestamp` it was captured at.

---

## How it is used

The eval suite under `tests/evals/` has two tiers:

- **Deterministic tier** — `test_contract_tier.py` and `test_trigger_evals.py`
  exercise matching/threshold logic and the cross-domain trigger rules with no
  model calls. These run in CI on every push (the `-m "not eval"` selection).
- **Model-graded tier** — `test_agent_evals.py` and `test_cross_agent_evals.py`
  run real specialist agents against the golden contracts and score them with
  the metrics above. These are marked with the `eval` pytest marker (defined in
  `pyproject.toml`) and require an API key.

Run them locally:

```bash
# Deterministic eval logic only (no API key)
pytest tests/evals/test_contract_tier.py tests/evals/test_trigger_evals.py -m "not eval"

# Full model-graded eval tier (requires ANTHROPIC_API_KEY or Bedrock creds)
pytest tests/evals/ -m eval
```

In CI, the model-graded tier runs on the main branch as a separate,
non-blocking job (it makes real model calls and reports quality regressions
without failing the build). The deterministic tier is part of the normal test
run. See `.github/workflows/ci.yml` for the exact job wiring.

---

## The F1 regression gate

`test_agent_evals.py` enforces hard per-agent thresholds (recall, citation
accuracy, severity accuracy, false-positive rate) and a **no-regression** check:
an agent's `f1_score` must not fall more than 0.05 below its stored baseline in
`tests/evals/baselines/latest.json`. If there is no baseline for an agent, the
regression check is skipped.

To intentionally move the baseline (after a deliberate, reviewed change), re-run
the eval tier with `--update-baseline` so `latest.json` captures the new
metrics, and commit the updated baseline:

```bash
pytest tests/evals/ -m eval --update-baseline
```

---

## Related Documentation

- [System Card](system-card.md) — anti-hallucination layers the evals validate
- [Agent Customization](agent-customization.md) — how agents are configured
