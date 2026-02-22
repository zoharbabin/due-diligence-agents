# Quickstart: Run DD-Agents on a Sample Data Room

This guide walks you through running the due-diligence agent pipeline on a minimal sample data room. By the end, you will have a `_dd/` output directory containing extracted findings, entity graphs, and a 14-sheet Excel report.

## What You'll Build

You will run `dd-agents` against a small data room with four contracts spread across two customer groups, plus a reference document. The pipeline will:

1. Discover and inventory every document.
2. Extract clauses, financials, and governance structures.
3. Resolve entity names across documents.
4. Run specialist agents (Contract, Financial, Operational, Compliance).
5. Produce a consolidated Excel report.

## Prerequisites

- Python 3.12+
- An `ANTHROPIC_API_KEY` (or AWS Bedrock credentials) for the full run

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
├── run_20260222_143000/
│   ├── inventory/
│   │   ├── file_manifest.json
│   │   └── customer_registry.json
│   ├── extraction/
│   │   ├── GroupA/Acme_Corp/contract_acme.pdf.json
│   │   ├── GroupA/Beta_Inc/agreement_beta.pdf.json
│   │   └── ...
│   ├── findings/
│   │   ├── contract_agent_findings.json
│   │   ├── financial_agent_findings.json
│   │   ├── operational_agent_findings.json
│   │   └── compliance_agent_findings.json
│   ├── entity_resolution/
│   │   ├── entity_graph.json
│   │   └── resolution_log.json
│   ├── validation/
│   │   ├── numerical_audit.json
│   │   └── dod_checks.json
│   ├── reports/
│   │   └── DD_Report_NovaBridge_Solutions.xlsx
│   └── metadata/
│       ├── run_config.json
│       └── run_summary.json
```

Key outputs:

- **`DD_Report_NovaBridge_Solutions.xlsx`** -- The 14-sheet Excel report with findings, risk matrix, entity map, financial summaries, and more.
- **`findings/`** -- Raw JSON findings from each specialist agent.
- **`entity_resolution/`** -- The resolved entity graph and matching log.
- **`validation/`** -- Numerical audit trail and Definition of Done checks.

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

### `ANTHROPIC_API_KEY not set`

The full run requires an API key. Set it in your environment:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or use AWS Bedrock by configuring `AWS_DEFAULT_REGION` and appropriate credentials.

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
