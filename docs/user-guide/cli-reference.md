# CLI Reference

All commands are accessed through the `dd-agents` entry point.

```bash
dd-agents [COMMAND] [OPTIONS]
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (config invalid, pipeline failure, missing input) |
| 2 | Blocking gate failed (pipeline halted at a validation gate) |
| 130 | Interrupted by user (Ctrl+C) |

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
| `--model-profile` | `economy\|standard\|premium` | from config | Override model tier |
| `--model-override` | `AGENT=MODEL` | none | Per-agent model override (repeatable) |
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
| `--output` | path | `deal-config.json` | Output file path |
| `--dry-run` | flag | off | Print config without writing |
| `--force` | flag | off | Overwrite existing output file |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
# Basic usage
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room

# Preview without writing
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room --dry-run

# Override deal type and save to custom path
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room \
  --deal-type merger --output configs/my-deal.json --force
```

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

## `dd-agents export-pdf`

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
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd-report.html
dd-agents export-pdf report.html --output board-package.pdf
dd-agents export-pdf report.html --engine weasyprint
```

---

## `dd-agents query`

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
