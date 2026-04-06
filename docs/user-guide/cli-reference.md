# CLI Reference

All commands are accessed through the `dd-agents` entry point.

```bash
dd-agents [COMMAND] [OPTIONS]
```

## Exit Codes

| Code | Meaning | What to Do |
|------|---------|------------|
| 0 | Success | Nothing — the pipeline completed normally |
| 1 | Error (invalid config, missing input, unexpected failure) | Check the error message and fix the issue |
| 2 | Quality gate failed (pipeline halted because a quality check did not pass) | See [blocking gate recovery](running-pipeline.md#blocking-gates) for specific guidance |
| 130 | Interrupted by user (Ctrl+C) | Resume with `--resume-from <step>` |

---

## run

Run the due diligence pipeline.

```
dd-agents run CONFIG_PATH [OPTIONS]
```

**Arguments:**
- `CONFIG_PATH` -- Path to the deal-config.json file

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--mode` | `full\|incremental` | from config | Override execution mode |
| `--resume-from` | int (1-35) | 0 (beginning) | Resume from a specific step |
| `--dry-run` | flag | off | Print step plan without executing |
| `--quick-scan` | flag | off | Run steps 1-13 + Red Flag Scanner only |
| `--model-profile` | `economy\|standard\|premium` | from config | Model quality: `economy` (fastest, cheapest), `standard` (balanced), `premium` (most accurate, most expensive) |
| `--model-override` | `AGENT=MODEL` | none | Per-agent model override (repeatable) |
| `--no-knowledge` | flag | off | Skip knowledge compilation after pipeline run |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
# Full pipeline run
dd-agents run deal-config.json

# Dry run to preview steps
dd-agents run deal-config.json --dry-run

# Resume from step 17 after fixing a blocking gate failure
dd-agents run deal-config.json --resume-from 17

# Quick triage with cheap models
dd-agents run deal-config.json --quick-scan --model-profile economy

# Premium legal analysis, standard for the rest
dd-agents run deal-config.json --model-override legal=claude-opus-4-6
```

---

## validate

Validate a deal-config.json file without running the pipeline.

```
dd-agents validate CONFIG_PATH
```

**Arguments:**
- `CONFIG_PATH` -- Path to the deal-config.json file

**Examples:**

```bash
dd-agents validate deal-config.json
```

Prints "Config is valid" with a summary table on success, or detailed validation
errors on failure.

---

## version

Print the installed dd-agents version.

```
dd-agents version
```

---

## init

Generate a deal-config.json by scanning a data room. Supports interactive and
scripted modes.

```
dd-agents init [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--data-room` | path | prompted | Path to the data room folder |
| `--buyer` | string | prompted | Acquiring company name |
| `--target` | string | prompted | Target company name |
| `--deal-type` | choice | prompted | `acquisition`, `merger`, `divestiture`, `investment`, `joint_venture`, `other` |
| `--focus-areas` | string | prompted | Comma-separated focus areas |
| `--name-variants` | string | prompted | Comma-separated alternate target names |
| `--output` | path | `deal-config.json` | Output file path |
| `--non-interactive` | flag | off | Skip prompts, use flags only |
| `--force` | flag | off | Overwrite existing output file |

**Examples:**

```bash
# Interactive mode
dd-agents init

# Fully scripted
dd-agents init --non-interactive --data-room ./data_room \
  --buyer "Acme Corp" --target "Target Inc" \
  --deal-type acquisition \
  --focus-areas "ip_ownership,change_of_control_clauses" \
  --name-variants "Target,Target Incorporated"
```

---

## auto-config

Auto-generate a deal-config.json by analyzing a data room with AI. Claude inspects
the directory structure, file names, and metadata to produce a complete configuration
including entity aliases and recommended focus areas.

```
dd-agents auto-config BUYER TARGET [OPTIONS]
```

**Arguments:**
- `BUYER` -- Name of the acquiring company
- `TARGET` -- Name of the company being acquired

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--data-room` | path | required | Path to the data room folder |
| `--deal-type` | choice | inferred | Override the AI-inferred deal type |
| `--buyer-docs` | path | none | Buyer business description files (10-K, annual report). Repeatable. |
| `--spa` | path | none | SPA draft/redline for deal structure extraction |
| `--press-release` | path | none | Acquisition press release for strategic context |
| `--buyer-docs-dir` | string | `_buyer` | Folder name for converted buyer files in data room |
| `--interactive` | flag | off | Enable interactive follow-up questions for strategy refinement |
| `--output` | path | `deal-config.json` | Output file path |
| `--dry-run` | flag | off | Print config without writing |
| `--force` | flag | off | Overwrite existing output file |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
# Basic usage (backward compatible)
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room

# Preview without writing
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room --dry-run

# Override deal type and save to custom path
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room \
  --deal-type merger --output configs/my-deal.json --force

# Deep auto-config with buyer strategy generation
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room \
  --buyer-docs ./10k.docx --spa ./spa-draft.pdf --press-release ./pr.docx

# Multiple buyer docs with interactive refinement
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room \
  --buyer-docs ./10k.docx --buyer-docs ./earnings-call.docx \
  --spa ./spa.pdf --interactive
```

When `--buyer-docs`, `--spa`, or `--press-release` are provided, the command runs
a multi-turn AI analysis to generate a `buyer_strategy` section. This enables the
Acquirer Intelligence Agent and buyer-specific report sections. Buyer documents are
converted to markdown and placed in `{data_room}/_buyer/` for agent access at runtime.

---

## search

Search customer contracts using custom prompts. Produces an Excel report with
answers and precise citations without running the full pipeline.

```
dd-agents search PROMPTS_PATH [OPTIONS]
```

**Arguments:**
- `PROMPTS_PATH` -- Path to the prompts JSON file

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--data-room` | path | required | Path to the data room folder |
| `--output` | path | auto-named | Excel output path |
| `--groups` | string | all | Comma-separated group names to include |
| `--customers` | string | all | Comma-separated customer names to filter |
| `--concurrency` | int (1-20) | 5 | Maximum parallel API calls |
| `--yes / -y` | flag | off | Skip cost confirmation prompt |
| `--no-file` | flag | off | Skip filing search results back to Knowledge Base |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
# Analyze all customers
dd-agents search prompts.json --data-room ./data_room

# Filter to specific customers, skip confirmation
dd-agents search prompts.json --data-room ./data_room \
  --customers "Acme,Beta Corp" -y

# Save to specific file with higher concurrency
dd-agents search prompts.json --data-room ./data_room \
  --output results.xlsx --concurrency 10
```

---

## assess

Assess data room quality and completeness before running the pipeline.

```
dd-agents assess DATA_ROOM [OPTIONS]
```

**Arguments:**
- `DATA_ROOM` -- Path to the data room folder

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
dd-agents assess ./data_room
```

Outputs a health report with overall score (0-100), file type distribution,
extraction readiness, issues, and recommendations.

---

## export-pdf

Export an HTML DD report to a print-optimized PDF.

```bash
dd-agents export-pdf <html_path> [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | Path | Same name with `.pdf` | Output PDF file path |
| `--engine` | Choice | `auto` | PDF engine: `auto`, `playwright`, `weasyprint` |

**Engine detection**: Prefers Playwright (highest fidelity), falls back to WeasyPrint. Install one:

```bash
pip install playwright && playwright install chromium
# OR
pip install weasyprint
```

**Examples:**

```bash
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd_report.html
dd-agents export-pdf report.html --output board-package.pdf
dd-agents export-pdf report.html --engine weasyprint
```

---

## query

Ask natural-language questions about the DD report findings.

```bash
dd-agents query --report <run_dir> [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--report` | Path | (required) | Path to the pipeline run directory |
| `--question`, `-q` | String | None | Single question (omit for interactive mode) |
| `--verbose`, `-v` | Flag | Off | Enable verbose logging |

Indexes merged findings from the run directory and answers questions using keyword matching (fast path for counts and filters) or Claude (for complex analysis questions).

**Examples:**

```bash
# Single question
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many P0 findings?"

# Interactive REPL mode
dd-agents query --report _dd/forensic-dd/runs/latest
> How many customers have CoC risk?
> What are the top liability concerns?
> quit
```

---

## portfolio

Manage multiple DD projects and compare across deals.

```
dd-agents portfolio COMMAND [OPTIONS]
```

### portfolio add

Register a new DD project.

```
dd-agents portfolio add NAME [OPTIONS]
```

**Arguments:**
- `NAME` -- Human-readable project name

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--data-room` | path | required | Path to the data room folder |
| `--deal-type` | string | none | Deal type (acquisition, merger, etc.) |
| `--buyer` | string | none | Buyer company name |
| `--target` | string | none | Target company name |

**Examples:**

```bash
dd-agents portfolio add "Alpha Acquisition" --data-room ./alpha --deal-type acquisition
dd-agents portfolio add "Beta Merger" --data-room ./beta --buyer "Acme" --target "Beta Inc"
```

### portfolio list

List all registered projects with status, finding counts, and risk scores.

```
dd-agents portfolio list
```

Displays a table with name, status, deal type, customer count, finding count,
risk score, and last run date for each project.

### portfolio compare

Compare risk profiles across deals.

```
dd-agents portfolio compare [SLUGS...]
```

**Arguments:**
- `SLUGS` -- Optional project slugs to compare (omit to compare all active projects)

Outputs total findings, average risk score, severity distribution, and
risk benchmarks (min/median/max).

**Examples:**

```bash
# Compare all active projects
dd-agents portfolio compare

# Compare specific projects
dd-agents portfolio compare alpha_acquisition beta_merger
```

### portfolio remove

Remove a project from the registry (does not delete data room files).

```
dd-agents portfolio remove SLUG
```

**Arguments:**
- `SLUG` -- Project slug (shown in `portfolio list`)

---

## templates

Browse and inspect pre-built report templates.

```
dd-agents templates COMMAND
```

### templates list

List all available report templates.

```
dd-agents templates list
```

Built-in templates:

| Template ID | Name | Audience |
|-------------|------|----------|
| `full_report` | Full DD Report | Complete analysis with all sections |
| `board_summary` | Board Summary | Condensed executive summary — KPIs, Go/No-Go, top findings only |
| `legal_deep_dive` | Legal Deep Dive | Detailed legal analysis (CoC, TfC, privacy, IP) |
| `financial_analysis` | Financial Analysis | Revenue, SaaS metrics, valuation |
| `technical_assessment` | Technical Assessment | Product and technology focused |

### templates show

Show details of a specific template (sections included, branding, detail level).

```
dd-agents templates show TEMPLATE_ID
```

**Arguments:**
- `TEMPLATE_ID` -- Template identifier (from `templates list`)

**Examples:**

```bash
dd-agents templates list
dd-agents templates show board_summary
dd-agents templates show legal_deep_dive
```

---

## log

View the analysis chronicle — an append-only timeline of all pipeline runs, searches, and queries.

```
dd-agents log [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project-dir` | path | `.` | Project directory |
| `--type` | string | all | Filter by interaction type (pipeline_run, search, query, annotation, manual) |
| `--entity` | string | all | Filter by entity safe name |
| `--limit` | int | 50 | Maximum entries to display |

**Examples:**

```bash
dd-agents log
dd-agents log --type search --limit 10
dd-agents log --entity acme_corp
```

---

## annotate

Add a user annotation to the Deal Knowledge Base. Annotations capture analyst observations, corrections, or notes that enrich future analysis.

```
dd-agents annotate ENTITY TEXT [OPTIONS]
```

**Arguments:**
- `ENTITY` -- Entity safe name (e.g., `acme_corp`)
- `TEXT` -- Annotation text

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project-dir` | path | `.` | Project directory |

**Examples:**

```bash
dd-agents annotate acme_corp "CFO confirmed revenue recognition change in Q3 call"
```

---

## lineage

View finding lineage — how findings evolve across pipeline runs.

```
dd-agents lineage [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project-dir` | path | `.` | Project directory |
| `--entity` | string | all | Filter by entity safe name |
| `--status` | string | all | Filter by status (active, resolved, recurring, escalated, de-escalated) |

**Examples:**

```bash
dd-agents lineage
dd-agents lineage --entity acme_corp --status escalated
```

---

## health

Run automated integrity checks against the Deal Knowledge Base.

```
dd-agents health [OPTIONS]
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--project-dir` | path | `.` | Project directory |
| `--auto-fix` | flag | off | Automatically fix broken links and orphan articles |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
dd-agents health
dd-agents health --auto-fix
```

Checks 7 categories: staleness, orphans, broken links, missing coverage, citation drift, graph integrity, and lineage gaps.

---

## Global Options

The `--version` flag is available on the top-level group:

```bash
dd-agents --version
```

## Related Documentation

- [Getting Started](getting-started.md) -- Installation and first run
- [Deal Configuration](deal-configuration.md) -- Config file structure
- [Running the Pipeline](running-pipeline.md) -- Pipeline execution details
- [Reading the Report](reading-report.md) -- Report navigation guide
