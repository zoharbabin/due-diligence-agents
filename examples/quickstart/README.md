# Quickstart: Run DD-Agents on a Sample Data Room

This guide walks you through running the due-diligence agent pipeline on a minimal sample data room. By the end, you will have a `_dd/` output directory containing extracted findings, entity graphs, a detailed cross-domain HTML report, and a 14-sheet Excel companion report.

## What You'll Build

You will run `dd-agents` against a small data room with four contracts spread across two subject groups, plus a reference document. The pipeline will:

1. Discover and inventory every document.
2. Extract clauses, financials, and governance structures.
3. Resolve entity names across documents.
4. Run specialist agents (Legal, Finance, Commercial, ProductTech, Cybersecurity, HR, Tax, Regulatory, ESG).
5. Produce a detailed cross-domain HTML report and a 14-sheet Excel companion report.

## Prerequisites

- Python 3.12+
- Claude API access: `ANTHROPIC_API_KEY` or AWS Bedrock credentials (`AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)

## Step 1: Install

Clone the repository and install in development mode:

```bash
cd due-diligence-agents
pip install -e ".[dev]"
```

Verify the CLI is available:

```bash
dd-agents version
```

## Step 2: Generate Config with Auto-Config (Recommended)

The fastest way to get started is `auto-config`. It scans your data room and uses Claude to produce a complete `deal-config.json` — resolving legal entity names, subsidiaries, historical names, entity variants, and focus areas automatically.

```bash
dd-agents auto-config "Meridian Holdings" "NovaBridge Solutions" \
  --data-room examples/quickstart/sample_data_room
```

This will:

1. Scan the data room directory structure and catalog every file.
2. Send the directory tree, file metadata, and company names to Claude.
3. Generate a `deal-config.json` with buyer/target details, entity aliases, focus areas, and data room mapping.

Use `--dry-run` to preview the output without writing a file:

```bash
dd-agents auto-config "Meridian Holdings" "NovaBridge Solutions" \
  --data-room examples/quickstart/sample_data_room --dry-run
```

### Auto-Config Options

| Flag | Description |
|------|-------------|
| `--data-room PATH` | Path to the data room folder (required) |
| `--deal-type TYPE` | Override inferred deal type (e.g., `merger`, `divestiture`) |
| `--output PATH` | Where to save the config (default: `deal-config.json`) |
| `--dry-run` | Print the config without writing to disk |
| `--force` | Overwrite output file if it already exists |

### Alternative: Use the Example Config

If you prefer to skip auto-config and use a pre-filled config directly:

```bash
cp examples/quickstart/deal-config.json .
```

This config defines a fictional deal where **Meridian Holdings** is acquiring **NovaBridge Solutions**. The data room path is set to `examples/quickstart/sample_data_room/`.

## Step 3: Validate the Config

Whether you generated or copied the config, validate it:

```bash
dd-agents validate deal-config.json
```

Expected output:

```
Config valid: deal-config.json
  Buyer:  Meridian Holdings
  Target: NovaBridge Solutions
  Data room: examples/quickstart/sample_data_room/ (5 documents found)
  Judge: disabled
  Mode: full
```

## Step 4: Dry Run

Preview what the pipeline will do without calling any LLM:

```bash
dd-agents run deal-config.json --dry-run
```

The dry run will:

- Scan the data room and print the file inventory.
- Show which agents would be invoked and in what order.
- Validate all schemas and report any issues.
- Estimate token usage.

No API calls are made. No output files are written.

## Step 5: Full Run

Run the complete pipeline (requires `ANTHROPIC_API_KEY`):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
dd-agents run deal-config.json
```

This will execute all 35 orchestrator steps.

## What to Expect

After a successful run, you will find a `_dd/` directory:

```
_dd/
└── forensic-dd/
    ├── index/
    │   └── text/                    # Extracted text (PERMANENT, cached across runs)
    │       ├── subject_1.md
    │       └── ...
    ├── inventory/                   # File discovery (FRESH, rebuilt each run)
    │   ├── tree.txt
    │   ├── files.txt
    │   ├── subjects.csv
    │   ├── counts.json
    │   └── entity_matches.json
    ├── entity_resolution_cache.json # Entity cache (PERMANENT)
    ├── run_history.json             # All prior runs (PERMANENT)
    └── runs/
        ├── latest -> 20260222_143000/
        └── 20260222_143000/         # Per-run output (VERSIONED, immutable)
            ├── findings/
            │   ├── legal/           # Per-subject findings from each specialist
            │   ├── finance/
            │   ├── commercial/
            │   ├── producttech/
            │   ├── cybersecurity/
            │   ├── hr/
            │   ├── tax/
            │   ├── regulatory/
            │   ├── esg/
            │   └── merged/          # Deduplicated findings across all agents
            ├── report/
            │   ├── dd_report.html   # Interactive cross-domain HTML report
            │   └── dd_report.xlsx   # 14-sheet Excel companion report
            ├── audit/               # Validation logs per agent
            ├── audit.json           # QA audit results
            ├── numerical_manifest.json
            ├── file_coverage.json
            └── metadata.json
```

Key outputs:

- **`runs/latest/report/dd_report.html`** -- The interactive HTML report with cross-domain findings, risk heatmaps, and drill-down to exact contract clauses. **Review all high-severity findings with your domain experts before acting on them.**
- **`runs/latest/report/dd_report.xlsx`** -- The 14-sheet Excel companion report with findings, risk matrix, entity map, financial summaries, and more.
- **`runs/latest/findings/`** -- Per-subject JSON findings from each specialist agent plus merged results.
- **`inventory/`** -- File discovery, subject registry, and entity resolution matches.
- **`runs/latest/audit.json`** -- QA audit trail and Definition of Done checks.

## Troubleshooting

### `dd-agents: command not found`

The CLI entry point was not installed. Re-run:

```bash
pip install -e ".[dev]"
```

Make sure you are in the `due-diligence-agents/` root directory.

### `Config validation failed: data_room path not found`

The `data_room.path` in your config points to a directory that does not exist relative to where you run the command. Either:

- Run from the repository root, or
- Update `data_room.path` in `deal-config.json` to an absolute path.

### API key not set

The full run requires Claude API access. Set one of:

```bash
# Option 1: Anthropic API
export ANTHROPIC_API_KEY="sk-ant-..."

# Option 2: AWS Bedrock
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

### `ModuleNotFoundError: No module named 'dd_agents'`

You have not installed the package. Run `pip install -e ".[dev]"` from the repo root.

### Run seems stuck or slow

- The pipeline processes documents sequentially by default. Large data rooms take longer.
- Check `_dd/run_*/metadata/run_summary.json` for progress.
- Use `--dry-run` first to estimate scope.

### Want to re-run only changed documents?

Use incremental mode:

```bash
dd-agents run deal-config.json --mode incremental
```

This skips documents whose checksums have not changed since the last run.
