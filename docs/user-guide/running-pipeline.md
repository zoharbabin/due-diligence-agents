# Running the Pipeline

The pipeline accelerates what traditionally takes teams of lawyers and analysts weeks of manual contract review. [DD timelines keep compressing](https://www.spellbook.legal/briefs/m-a-due-diligence) — what used to be a six-week process becomes three weeks, with no reduction in scope. The pipeline analyzes every document across four domains (Legal, Finance, Commercial, Product/Tech), cross-validates findings, and produces quality-gated structured analysis with sourced citations.

**This tool does not replace professional advisors.** Use the output alongside your advisory workstreams to accelerate search, correlation, and tracking across the data room.

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
Step 1 is effectively blocking -- if config validation fails, the pipeline halts.

**Phase 2: Discovery and Extraction (Steps 4-5)**
Discover files in the data room. Extract text from PDFs and Office documents using
pymupdf with fallback to markitdown, OCR, or Claude vision. Step 5 is a **blocking gate** --
extraction must succeed for at least a minimum threshold of files.

**Phase 3: Inventory and Resolution (Steps 6-12)**
Build customer inventory with document ranking (which version of a file to trust when
duplicates exist), match company names across documents (handling aliases, abbreviations,
and legal suffixes automatically), build reference registry, count customer mentions,
and verify inventory integrity. Steps 11-12 are conditional (database reconciliation
and incremental classification).

**Phase 4: Agent Execution (Steps 13-17)**
Create the specialist team (Legal, Finance, Commercial, ProductTech), prepare analysis
instructions with document ranking context, route references, and run agents in parallel.
Step 17 is a **blocking gate** -- coverage must meet minimum thresholds across all domains.

**Phase 5: Quality Review (Steps 18-22)**
Merge incremental results (if applicable). Optionally spawn the Judge agent for
adversarial review of specialist findings. Steps 19-22 run only when `judge.enabled`
is true in the deal config.

**Phase 6: Reporting (Steps 23-31)**
Step 23 runs pre-merge validation (cross-agent anomaly detection, citation verification,
P0/P1 follow-up). Steps 24-25 merge and deduplicate findings across agents and identify
coverage gaps. Step 26 builds the numerical manifest. Steps 27-28 run the numerical
audit (**blocking gate**) and full QA audit (**blocking gate**). Step 29 builds the
incremental diff. Step 30 generates both Excel and HTML reports, and also runs the
Executive Synthesis agent (Go/No-Go calibration), the Acquirer Intelligence agent
(when `buyer_strategy` is configured), and the Red Flag Scanner (when `--quick-scan`
is used). Step 31 is the post-generation validation **blocking gate**.

**Phase 7: Finalization (Steps 32-35)**
Write run metadata, update run history, save entity resolution cache, shut down.

## Blocking Gates

Five steps are blocking gates that halt the pipeline on failure:

| Step | Gate | What It Checks |
|------|------|---------------|
| 5 | Bulk Extraction | Minimum extraction success rate |
| 17 | Coverage Gate | Agent coverage across all domains |
| 27 | Numerical Audit | Financial figure consistency across 6 validation layers |
| 28 | Full QA Audit | 31 definition-of-done checks |
| 31 | Post-Generation Validation | Report completeness and integrity |

When a gate fails, the pipeline stops with exit code 2 and prints the reason for failure.

**How to recover from each gate failure:**

| Gate | Common Cause | How to Fix |
|------|-------------|------------|
| Bulk Extraction (step 5) | Corrupted or password-protected PDFs | Remove or replace problem files, then `--resume-from 4` |
| Coverage Gate (step 17) | Too few documents per customer for meaningful analysis | Add missing documents to the data room, then `--resume-from 6` |
| Numerical Audit (step 27) | Contradictory financial figures across documents | Review flagged findings in `audit.json`, then `--resume-from 27` |
| Full QA Audit (step 28) | Quality checks failed (missing citations, low confidence) | Review `dod_results.json` for specifics, then `--resume-from 28` |
| Post-Generation (step 31) | Report generation produced incomplete output | Check disk space, then `--resume-from 30` |

## Agents

The pipeline uses 8 specialized analyzers — 4 domain specialists that process contracts in parallel, plus 4 synthesis/validation components:

| Agent | Type | Phase | Description |
|-------|------|-------|-------------|
| Legal | Specialist | 4 | Contract clause analysis (CoC, TfC, IP, privacy, liability) with 18 canonical clause types |
| Finance | Specialist | 4 | Revenue recognition, SaaS metrics, financial risk |
| Commercial | Specialist | 4 | Customer concentration, pricing, renewal risk |
| ProductTech | Specialist | 4 | Technology dependencies, integration complexity |
| Judge | Validation | 5 | Adversarial review of specialist findings (optional) |
| Executive Synthesis | Synthesis | 6 | Go/No-Go calibration, severity recalibration |
| Acquirer Intelligence | Synthesis | 6 | Buyer thesis alignment, synergy validation (when `buyer_strategy` configured) |
| Red Flag Scanner | Triage | 6 | Quick stoplight triage (when `--quick-scan` used) |

All 4 specialists share a base execution engine (`BaseAgentRunner`) but are differentiated by substantive domain-specific prompts containing M&A-specific legal definitions, targeted extraction instructions, and relevant keyword sets.

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
        ├── pre_merge_validation.json  # Cross-agent validation report
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

When resuming from steps 3-5, the FRESH persistence tier is automatically wiped to
prevent stale inventory data from a prior interrupted run.

## Next Steps

- [Reading the Report](reading-report.md) -- Navigate the generated reports
- [Deal Configuration](deal-configuration.md) -- Adjust config settings
- [CLI Reference](cli-reference.md) -- Full command reference
