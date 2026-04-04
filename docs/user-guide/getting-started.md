# Getting Started

This tool accelerates M&A due diligence by analyzing your entire data room across Legal, Finance, Commercial, and Product/Tech — helping your deal team find what gets buried, cross-reference it across domains, and trace every finding to an exact page and quote.

[31% of M&A failures trace back to due diligence shortcomings](https://acquisitionstars.com/ma-failure-rate/), often because legal, financial, and commercial workstreams run in silos with no cross-referencing. This tool runs all four workstreams simultaneously, cross-references findings across domains, and produces structured analysis your team can use as the foundation for IC memos, advisor reports, or negotiation checklists.

**This tool does not replace professional advisors.** Legal, financial, and regulatory conclusions should always be made by qualified professionals. This tool helps your team and advisors work more efficiently.

## Prerequisites

- **Python 3.12 or later** — check with `python3 --version`. If you need to install or upgrade, download from [python.org](https://www.python.org/downloads/).
- **An Anthropic API key** — [get one here](https://console.anthropic.com/). Alternatively, AWS Bedrock credentials work too.
- **A data room folder** containing the contracts and documents to analyze.

## Installation

```bash
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[pdf]"
```

This installs the tool and all required dependencies, including PDF extraction support.

For developers who also want testing and linting tools:

```bash
pip install -e ".[dev,pdf]"
```

### Optional Extras

Install these for additional capabilities:

```bash
pip install -e ".[vector]"     # Semantic search across documents (ChromaDB)
pip install -e ".[ocr]"        # OCR for scanned PDFs (English)
pip install -e ".[glm-ocr]"    # Multilingual OCR (100+ languages, Apple Silicon)
```

### Optional System Dependencies

| Dependency | macOS | Linux | Purpose |
|-----------|-------|-------|---------|
| `poppler` | `brew install poppler` | `apt install poppler-utils` | Fallback PDF extraction |
| `tesseract` | `brew install tesseract` | `apt install tesseract-ocr` | OCR for scanned PDFs |

These are optional — the tool works without them but may produce lower-quality text from some scanned documents.

## API Key Setup

You need an API key to run the analysis. Choose one method:

**Option A — `.env` file** (recommended, persists across terminal sessions):

```bash
cp .env.example .env
```

Then edit `.env` and set your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

**Option B — Environment variable** (temporary, lasts until you close the terminal):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Option C — AWS Bedrock:**

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

To override which AI model is used, pass `--model-profile economy|standard|premium` when running the pipeline (see [Running the Pipeline](running-pipeline.md)).

## Verify Installation

```bash
dd-agents version
```

This prints the installed version. If the command is not found, ensure the package installed correctly and your PATH includes the Python scripts directory.

## Preparing Your Data Room

Organize your contracts into folders by customer or counterparty:

```
data_room/
  CustomerGroup_A/
    Acme_Corp/
      master_agreement.pdf
      amendment_2024.pdf
    Beta_Inc/
      license_agreement.pdf
  CustomerGroup_B/
    Gamma_LLC/
      services_contract.docx
  _reference/                    # Optional: reference docs (buyer overview, etc.)
    buyer_overview.pdf
```

**Supported formats:** PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), and images. Scanned PDFs are handled via OCR.

**Folder structure matters:** The tool uses folder names to identify which documents belong to which customer. A flat folder of files with no subfolder structure will still work — the tool groups them as a single entity — but organizing by customer produces better results.

A pre-built sample data room is included at `examples/quickstart/sample_data_room/` so you can try the tool before setting up your own files.

## Pre-Flight Check

Before running the full pipeline, assess your data room quality:

```bash
dd-agents assess ./data_room
```

This reports file type distribution, extraction readiness, and an overall completeness score. Address any critical issues before proceeding.

## First Run

The typical workflow is three steps: generate a config, run the pipeline, review the report.

### 1. Generate a Deal Configuration

The fastest path is `auto-config`, which uses AI to scan your data room and produce a complete configuration (costs roughly $0.50-$2 in API usage):

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room
```

This produces a `deal-config.json` with buyer/target details, company name variants, focus areas, and data room mapping. See [Deal Configuration](deal-configuration.md) for details.

To preview the config without writing it:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room --dry-run
```

Alternatively, generate a config interactively without any API calls:

```bash
dd-agents init --data-room ./data_room
```

### 2. Run the Pipeline

```bash
dd-agents run deal-config.json
```

The pipeline extracts text, matches company names, runs AI analysis across all four domains, validates quality, and generates the report.

To preview what will happen without making API calls:

```bash
dd-agents run deal-config.json --dry-run
```

For a quick red-flag triage instead of full analysis:

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

See [Running the Pipeline](running-pipeline.md) for all options including resume, model selection, and quality gates.

### 3. Review the Report

After the pipeline completes, find the outputs in `_dd/forensic-dd/runs/latest/report/`:

- `dd_report.html` -- Interactive HTML report with cross-domain findings, severity filtering, and drill-down to exact clauses
- `dd_report.xlsx` -- 14-sheet Excel report for detailed analysis and downstream work

Open `dd_report.html` in a browser. See [Reading the Report](reading-report.md) for a walkthrough of each section.

**Use these reports alongside your advisory process.** The structured findings, citations, and cross-references serve as the foundation for your team's own deliverables — board presentations, advisor memos, negotiation checklists, or integration plans.

## Post-Run Tools

### Contract Search

Search contracts with custom questions without running the full pipeline:

```bash
dd-agents search prompts.json --data-room ./data_room
```

### Natural Language Query

Ask questions about findings interactively or via a single question:

```bash
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many high-severity findings?"
dd-agents query --report _dd/forensic-dd/runs/latest  # interactive mode
```

### PDF Export

Export the HTML report to a print-ready PDF:

```bash
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd_report.html
```

### Portfolio Management

Track multiple due diligence projects and compare risk profiles across deals:

```bash
dd-agents portfolio add "Alpha Acquisition" --data-room ./alpha_data_room
dd-agents portfolio list
dd-agents portfolio compare
```

### Report Templates

Apply templates for different audiences (Board Summary, Legal Deep Dive, etc.):

```bash
dd-agents templates list
dd-agents templates show board_summary
```

See the [CLI Reference](cli-reference.md) for full documentation of all commands.

## Docker

Build and run in a container:

```bash
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v ./data_room:/workspace/data_room \
  -v ./deal-config.json:/workspace/deal-config.json \
  dd-agents run deal-config.json
```

## Next Steps

- [Deal Configuration](deal-configuration.md) -- Config file structure and generation
- [Running the Pipeline](running-pipeline.md) -- Execution modes and options
- [Reading the Report](reading-report.md) -- Navigating the HTML and Excel output
- [CLI Reference](cli-reference.md) -- Complete command reference
