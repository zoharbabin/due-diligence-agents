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
| `--resume-from` | int (0-38) | 0 (beginning) | Resume from a specific step |
| `--no-narrative` | flag | off | Skip LLM narrative generation (deterministic report only) |
| `--dry-run` | flag | off | Print step plan without executing |
| `--quick-scan` | flag | off | Add a Red Flag Scanner stoplight-triage pass (full pipeline runs; scanner reads merged findings) |
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
dd-agents run deal-config.json --model-override legal=claude-opus-4-8
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
dd-agents version --json    # machine-readable: {"version": "..."}
```

---

## doctor

Verify the configured LLM provider/model routing before a run. Prints the
active provider/gateway (secret-free — embedded credentials are stripped),
checks that a credential is present, and exits non-zero on misconfiguration.

```
dd-agents doctor            # show routing + credential check
dd-agents doctor --probe    # also issue one minimal live query
dd-agents doctor --json     # machine-readable routing receipt
```

See [Model Providers](model-providers.md) for the full provider/model story.

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
| `--deal-type` | choice | prompted | `acquisition`, `asset_sale`, `merger`, `divestiture`, `investment`, `joint_venture`, `other` |
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

Search subject contracts using custom prompts. Produces an Excel report with
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
| `--subjects` | string | all | Comma-separated subject names to filter |
| `--concurrency` | int (1-20) | 5 | Maximum parallel API calls |
| `--yes / -y` | flag | off | Skip cost confirmation prompt |
| `--no-file` | flag | off | Skip filing search results back to Knowledge Base |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
# Analyze all subjects
dd-agents search prompts.json --data-room ./data_room

# Filter to specific subjects, skip confirmation
dd-agents search prompts.json --data-room ./data_room \
  --subjects "Acme,Beta Corp" -y

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
| `--config` | Path | none | Optional `deal-config.json` — enables request-list reconciliation. Reports received / missing-required / unexpected documents against the config's `request_list`. |
| `--verbose / -v` | flag | off | Enable debug logging |

**Examples:**

```bash
dd-agents assess ./data_room
dd-agents assess ./data_room --config deal-config.json   # + request-list completeness
```

Outputs a health report with overall score (0-100), file type distribution,
extraction readiness, issues, recommendations, a detected VDR layout (when the
data room uses a numbered convention), and — with `--config` — a request-list
received-vs-missing view.

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

## memo

Generate an Investment Committee memo from a completed run.

```bash
dd-agents memo --report <run_dir> [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--report` | Path | (required) | Pipeline run directory (contains `findings/merged/`) |
| `--output` | Path | `<run>/report/ic_memo.md` | Output memo path (Markdown); an `.html` sibling is also written |
| `--deal-config` | Path | auto-discovered | `deal-config.json` for the memo header; found by walking up from the run dir if omitted |

Deterministically assembles a memo (Markdown + HTML) from the run's merged
findings — Go/No-Go signal, key takeaways, top risks with cited evidence,
recommendations, and a methodology appendix. No new analysis pass. Convert to
PDF with `dd-agents export-pdf` on the emitted `.html`.

**Examples:**

```bash
dd-agents memo --report _dd/forensic-dd/runs/latest
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/ic_memo.html
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
> How many subjects have CoC risk?
> What are the top liability concerns?
> quit
```

---

## chat

Interactive multi-turn chat about due diligence findings. Explore results, drill into source documents, verify citations, and save insights that persist across sessions.

```bash
dd-agents chat [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--report` | Path | `runs/latest` | Path to the pipeline run directory |
| `--model` | String | SDK default | Override the LLM model (e.g. `claude-sonnet-4-6`) |
| `--max-cost` | Float | 10.00 | Maximum session cost in USD |
| `--max-turns` | Int | 200 | Max tool-use turns per question (max: 500) |
| `--no-limit` | Flag | Off | Remove per-turn caps for complex tasks (session cost is the only brake) |
| `--no-tools` | Flag | Off | Disable document tools (findings-only mode) |
| `--question / -q` | String | — | Ask a single question non-interactively and exit (scriptable; no TTY needed) |
| `--verbose / -v` | Flag | Off | Enable verbose logging |

Chat mode provides MCP document tools (citation verification, page reading, entity resolution), persistent memory, and document export. The model can save key insights during conversation, recall them in future sessions, and generate Excel workbooks, Word documents, and CSV files on request using the `run_export_script` tool. Exported files are saved to `_dd/exports/`.

**In-session commands:**
- `cost` — show current session cost
- `history` — show turn count and history size
- `quit` / `exit` / `q` — end session

**Examples:**

```bash
# Start chatting about the latest run
dd-agents chat

# Specify a run directory
dd-agents chat --report _dd/forensic-dd/runs/latest

# Findings-only mode (no document tools, faster responses)
dd-agents chat --no-tools

# Unlimited turns for heavy analysis (set cost cap as safety brake)
dd-agents chat --no-limit --max-cost 25.0

# Higher budget with specific model
dd-agents chat --max-cost 20.0 --model claude-sonnet-4-6

# Single question, non-interactively (scriptable — prints the answer and exits)
dd-agents chat -q "What are the top 3 P0 findings and their citations?"
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

Displays a table with name, status, deal type, subject count, finding count,
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
| `--data-room` | path | required | Path to the data room folder |
| `--type` | string | all | Filter by interaction type (pipeline_run, search, query, annotation, knowledge_compilation, chat) |
| `--limit` | int | 20 | Maximum entries to display |

**Examples:**

```bash
dd-agents log --data-room ./data_room
dd-agents log --data-room ./data_room --limit 5 --type search
```

---

## annotate

Add a user annotation to the Deal Knowledge Base. Annotations capture analyst observations, corrections, or notes that enrich future analysis.

```
dd-agents annotate [OPTIONS] NOTE
```

**Arguments:**
- `NOTE` -- Annotation text

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--data-room` | path | required | Path to the data room folder |
| `--entity` | string | none | Entity safe_name to link this annotation to |

**Examples:**

```bash
dd-agents annotate --data-room ./data_room "Key risk: vendor lock-in clause in Acme MSA"
dd-agents annotate --data-room ./data_room --entity acme_corp "Needs legal review"
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
| `--data-room` | path | required | Path to the data room folder |
| `--entity` | string | all | Filter by entity safe name |
| `--active-only` | flag | off | Show only active findings |
| `--format` | `table\|json\|csv` | `table` | Output format |
| `--output` | path | stdout | Write output to file instead of stdout |

**Examples:**

```bash
dd-agents lineage --data-room ./data_room
dd-agents lineage --data-room ./data_room --entity acme_corp --active-only
dd-agents lineage --data-room ./data_room --format json --output lineage.json
dd-agents lineage --data-room ./data_room --format csv --output lineage.csv
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
| `--data-room` | path | required | Path to the data room folder |
| `--auto-fix` | flag | off | Automatically fix broken links and orphan articles |

**Examples:**

```bash
dd-agents health --data-room ./data_room
dd-agents health --data-room ./data_room --auto-fix
```

Checks 7 categories: staleness, orphans, broken links, missing coverage, citation drift, graph integrity, and lineage gaps.

---

## agents

Inspect, describe, validate, and preview specialist agents. Every subcommand is
**read-only** — none writes files or calls the model.

```
dd-agents agents COMMAND [OPTIONS]
```

### agents list

List every registered specialist agent with its enabled/disabled status, and
(when a config is passed) the resolved model tier.

```
dd-agents agents list [--config PATH]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--config` | path | none | Optional `deal-config.json`; reflects `specialists.disabled` and model tiers |

```bash
dd-agents agents list
dd-agents agents list --config ./deal-config.json
```

Reads `agents/registry.py` (and the deal config if given). Writes nothing.

### agents describe

Render an agent's persona, focus areas, and the non-removable safety floor as
markdown.

```
dd-agents agents describe --agent NAME [--format text|md]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--agent` | string | required | Agent name (e.g. `legal`, `finance`) |
| `--format` | choice | `text` | Output format: `text` (rendered for the terminal) or `md` (raw markdown) |

```bash
dd-agents agents describe --agent legal
```

Reads the agent descriptor and the assembled safety floor. Writes nothing. Exits
non-zero on an unknown agent name.

### agents validate

Lint the `dd-config/` customizations under a project directory. Fail-closed:
exits non-zero if any error-level issue is found.

```
dd-agents agents validate PROJECT_DIR
```

| Argument | Type | Description |
|----------|------|-------------|
| `PROJECT_DIR` | path | Directory containing the `dd-config/` folder |

```bash
dd-agents agents validate ./my-project
```

Checks unknown agent names, unknown front-matter keys/headings, malformed
severity tokens, empty persona overrides, broken `extends` chains, and
safety-floor-negation patterns. Reads `dd-config/agents/*.md`; writes nothing.

### agents preview

Print the fully assembled specialist prompt — customizations, profiles, and
safety floor folded together — byte-identical to what the pipeline sends.

```
dd-agents agents preview --agent NAME [--config PATH] [--project-dir DIR] [--output FILE]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--agent` | string | required | Agent name to preview |
| `--config` | path | none | Optional `deal-config.json`; its directory is used as the project dir (so `dd-config/` is picked up) |
| `--project-dir` | path | `--config`'s dir, else cwd | Directory containing `dd-config/` |
| `--output`, `-o` | path | stdout | Write the assembled prompt to a file instead of stdout |

```bash
dd-agents agents preview --agent legal
dd-agents agents preview --agent legal --config ./deal-config.json
dd-agents agents preview --agent legal --project-dir ./my-deal -o legal-prompt.txt
```

Reads the registry, safety floor, and any `dd-config/` customizations. Writes
nothing unless `--output` is given. Exits non-zero on an unknown agent name.

See [Agent Customization](../agent-customization.md) for the full customization
workflow.

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
- [Troubleshooting](troubleshooting.md) -- Common errors, exit codes, recovery steps
