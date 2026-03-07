# Running the Pipeline

## Basic Execution

```bash
dd-agents run deal-config.json
```

This runs the full 35-step pipeline: config validation, document extraction, entity
resolution, specialist agent analysis, quality audits, and report generation.

## Execution Modes

### Full Mode (default)

Processes all documents from scratch. Use for first runs or when the data room has
changed significantly.

```bash
dd-agents run deal-config.json --mode full
```

### Incremental Mode

Reuses cached extraction and prior findings. Only re-analyzes new or modified files.
Faster for iterative runs on the same data room.

```bash
dd-agents run deal-config.json --mode incremental
```

## Command Options

| Option | Description |
|--------|-------------|
| `--mode full\|incremental` | Override execution mode from config |
| `--resume-from N` | Resume from step N (1-35), skipping earlier steps |
| `--dry-run` | Validate config and print step plan without executing |
| `--quick-scan` | Run steps 1-13 plus Red Flag Scanner only (fast triage) |
| `--model-profile PROFILE` | Override model tier: `economy`, `standard`, `premium` |
| `--model-override AGENT=MODEL` | Per-agent model, e.g. `--model-override legal=claude-opus-4-6` |
| `--verbose / -v` | Enable debug logging |

### Examples

Preview the step plan without running:

```bash
dd-agents run deal-config.json --dry-run
```

Resume after a failure at step 17:

```bash
dd-agents run deal-config.json --resume-from 17
```

Quick red-flag triage with economy models:

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

Use Opus for the legal agent, standard for everything else:

```bash
dd-agents run deal-config.json --model-override legal=claude-opus-4-6
```

## The 35-Step Pipeline

The pipeline is organized into 7 phases:

**Phase 1: Setup (Steps 1-3)**
Validate config, initialize persistence layer, check cross-skill dependencies.

**Phase 2: Discovery and Extraction (Steps 4-5)**
Discover files in the data room. Extract text from PDFs and Office documents using
pymupdf with fallback to markitdown, OCR, or Claude vision. Step 5 is a **blocking gate** --
extraction must succeed for at least a minimum threshold of files.

**Phase 3: Inventory (Steps 6-12)**
Build customer inventory, run entity resolution (6-pass fuzzy matching), build reference
registry, count customer mentions, and verify inventory integrity. Steps 11-12 are
conditional (database reconciliation and incremental classification).

**Phase 4: Agent Execution (Steps 13-17)**
Create the specialist team (Legal, Finance, Commercial, ProductTech), prepare prompts,
route references, and spawn agents in parallel batches. Step 17 is a **blocking gate** --
coverage must meet minimum thresholds across all domains.

**Phase 5: Quality Review (Steps 18-22)**
Merge incremental results (if applicable). Optionally spawn the Judge agent for
adversarial review of specialist findings. Steps 19-22 run only when `judge.enabled`
is true.

**Phase 6: Reporting (Steps 23-31)**
Merge and deduplicate findings across agents, build the numerical manifest, run the
numerical audit (**blocking gate**, step 27), full QA audit (**blocking gate**, step 28),
generate Excel and HTML reports, and validate the output (**blocking gate**, step 31).

**Phase 7: Finalization (Steps 32-35)**
Write run metadata, update run history, save entity resolution cache, shut down.

## Blocking Gates

Five steps are blocking gates that halt the pipeline on failure:

| Step | Gate | What It Checks |
|------|------|---------------|
| 5 | Bulk Extraction | Minimum extraction success rate |
| 17 | Coverage Gate | Agent coverage across all domains |
| 27 | Numerical Audit | Financial figure consistency |
| 28 | Full QA Audit | 30 definition-of-done checks |
| 31 | Post-Generation Validation | Report completeness and integrity |

When a gate fails, the pipeline stops with exit code 2 and prints instructions for
resuming after the issue is fixed.

## Output Directory Structure

All output goes under `_dd/forensic-dd/` relative to the data room:

```
_dd/forensic-dd/
├── index/text/                     # PERMANENT: extracted document text
├── inventory/                      # PERMANENT: customer registry, file counts
├── entity_resolution_cache.json    # PERMANENT: entity matching cache
└── runs/
    └── 20260307_143000/            # VERSIONED: timestamped per run
        ├── findings/
        │   ├── legal/              # Per-agent raw findings
        │   ├── finance/
        │   ├── commercial/
        │   ├── product_tech/
        │   └── merged/            # Deduplicated merged findings
        ├── report/
        │   ├── dd_report.html     # Interactive HTML report
        │   └── dd_report.xlsx     # 14-sheet Excel report
        ├── audit.json             # QA validation results
        ├── metadata.json          # Run metadata and costs
        └── dod_results.json       # Definition-of-done check results
```

### Persistence Tiers

- **PERMANENT**: Never wiped between runs. Extraction cache, entity resolution cache,
  customer registry. Reused across full and incremental runs.
- **VERSIONED**: Archived per run in timestamped directories. Findings, reports,
  audit results. Each run gets its own copy.
- **FRESH**: Rebuilt each run. Working state, intermediate computations.

## Handling Failures

If the pipeline fails mid-run, note the step number from the error output and resume:

```bash
dd-agents run deal-config.json --resume-from 17
```

If a blocking gate fails (exit code 2), fix the underlying issue (e.g., add missing
documents to the data room) and resume from that step.

## Next Steps

- [Reading the Report](reading-report.md) -- Navigate the generated reports
- [Deal Configuration](deal-configuration.md) -- Adjust config settings
- [CLI Reference](cli-reference.md) -- Full command reference
