# Project Atlas — the golden sample deal

**Project Atlas** is the canonical, end-to-end synthetic M&A deal used everywhere in this
project — the quickstart, the public sample report, the launch demo, and documentation.
It is **100% synthetic** (no real company, person, or financial data), but it is engineered
so the pipeline's headline capability — **cross-domain cross-referencing** — produces a
**real, cited finding**, not a staged one.

- **Target:** Northwind Logistics Software, Inc. — a B2B cloud freight-management (TMS) SaaS, ~$41.2M ARR.
- **Acquirer:** Summit Industrial Group, LLC (100% acquisition; codename "Atlas").
- **The hero finding:** the target's largest customer (Meridian Freight, **30.1% of ARR**) holds a
  change-of-control clause (MSA §12.3) that lets it **terminate the moment the deal closes**.
  Legal sees the clause; Finance sees the concentration; **only cross-referencing the two reveals
  the ~$12.4M revenue cliff** — surfaced at **P0** and cited to the exact quote.

## What you'll build

Running the pipeline produces a `_dd/` output directory containing extracted findings, entity
graphs, a cross-domain HTML report (with a Go/No-Go view), and a 16-sheet Excel companion.

The pipeline will:
1. Discover and inventory every document in the data room.
2. Extract clauses, financials, and governance structures.
3. Resolve entity names across documents.
4. Run the specialist agents (Legal, Finance, Commercial, ProductTech, Cybersecurity, HR, Tax, Regulatory, ESG).
5. Cross-reference findings across domains (the Legal→Finance change-of-control link is the hero).
6. Produce the HTML report + 16-sheet Excel companion.

## Prerequisites

- Python 3.12+
- Claude API access: `ANTHROPIC_API_KEY` or AWS Bedrock credentials (`AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

## Run it

```bash
pip install -e ".[dev]"

# (optional) inspect the deal before running
dd-agents validate examples/project-atlas/deal-config.json
dd-agents assess  examples/project-atlas/sample_data_room

# preview the 38-step plan without spending LLM budget
dd-agents run examples/project-atlas/deal-config.json --dry-run

# run the full pipeline
dd-agents run examples/project-atlas/deal-config.json
```

Output lands at `examples/project-atlas/sample_data_room/_dd/forensic-dd/runs/latest/report/`
(`dd_report.html` + `dd_report.xlsx`). The `_dd/` working directory is gitignored.

> Want to see the result without running anything? Open the
> [live sample report](https://zoharbabin.github.io/due-diligence-agents/sample-report/) —
> it is this exact deal's real output.

## The data room

`sample_data_room/Northwind_Logistics/` (one subject; the data room is small so the run is fast
and the cross-domain link is easy to follow):

| File | What it plants |
|------|----------------|
| `msa_meridian_freight.pdf.md` | **Hero** — §12.3 auto-terminate-on-change-of-control, largest customer |
| `arr_schedule.xlsx.md` | ARR bridge — reconciles to $41.2M; Meridian = 30.1%, top-3 = 69.9% (concentration) |
| `cap_table_summary.pdf.md` | Confirms Summit's acquisition "constitutes a Change of Control" |
| `order_form_cobalt_retail.pdf.md` | $28.8M 36-month prepaid → revenue-recognition question |
| `msa_harbor_foods.pdf.md` | Termination-for-convenience on 30 days' notice (16.5% of ARR) |
| `msa_granite_manufacturing.pdf.md` | **Control case** — benign consent-based CoC (proves agents read clauses, not keywords) |
| `dpa_tidewater.pdf.md` + `subprocessor_register.pdf.md` | GDPR sub-processor gap (US telemetry vendor, no SCCs) |
| `contractor_agreement_route_engine.pdf.md` + `employment_ip_agreement.pdf.md` | IP-assignment gap (contractor built core IP, no assignment) vs the employee contrast |
| `board_deck_excerpt.pdf.md` | Management deck that *misstates* the CoC exposure (the "humans missed it" beat) |

A full continuity reference (every number/date/entity the documents agree on) is in
[`docs/marketing/project-atlas-bible.md`](../../docs/marketing/project-atlas-bible.md).

## Verified

A real pipeline run completed all 38 steps with every blocking gate passing
(numerical audit 6/6, QA audit, DoD 23/23). It produced 44 merged findings
(2× P0, 10× P1, 17× P2, 15× P3), with the hero change-of-control cliff surfaced at P0 by both
Legal and Finance and cited to Meridian MSA §12.3 verbatim. Verdict: **Conditional Go**.
