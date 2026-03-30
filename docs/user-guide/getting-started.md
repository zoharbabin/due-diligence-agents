# Getting Started

Traditional M&A due diligence takes 4-12 weeks and costs 1-3% of deal value in professional fees. This pipeline automates multi-domain contract analysis across Legal, Finance, Commercial, and Product/Tech — producing a board-ready report with precise citations in minutes instead of weeks.

## Prerequisites

- Python 3.12 or later
- An Anthropic API key or AWS Bedrock credentials
- A data room folder containing the contracts and documents to analyze

## Installation

Install the package in development mode:

```bash
pip install -e ".[dev]"
```

This installs all core dependencies (claude-agent-sdk, pydantic, openpyxl, networkx,
rapidfuzz, markitdown, pymupdf, scikit-learn, click, rich) plus dev tools (pytest, mypy, ruff).

### Optional Dependencies

Install extras for additional capabilities:

```bash
pip install -e ".[vector]"     # ChromaDB for semantic cross-document search
pip install -e ".[ocr]"        # pytesseract OCR fallback (English only)
pip install -e ".[glm-ocr]"    # GLM-OCR vision-language model (100+ languages, Apple Silicon / Ollama)
pip install -e ".[api]"        # FastAPI + uvicorn for REST API server
```

To install everything:

```bash
pip install -e ".[dev,vector,ocr,glm-ocr,api]"
```

### System Dependencies (optional)

| Dependency | Install | Purpose |
|-----------|---------|---------|
| `poppler` | `brew install poppler` (macOS) / `apt install poppler-utils` (Linux) | Fallback PDF extraction via `pdftotext` |
| `tesseract-ocr` | `brew install tesseract` (macOS) / `apt install tesseract-ocr` (Linux) | OCR for scanned PDFs (English only; use GLM-OCR for multilingual) |

## API Key Setup

Set one of these environment variables:

```bash
# Option A: Anthropic API (recommended)
export ANTHROPIC_API_KEY="sk-ant-..."

# Option B: AWS Bedrock
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

Optional environment variables:

```bash
# Override the default Claude model
export DD_MODEL="claude-sonnet-4-20250514"

# REST API authentication key (required for API server)
export DD_API_KEY="your-secret-api-key"

# ChromaDB: persist vector search index to disk (default: memory-only)
export CHROMA_PERSIST_DIR="./chroma_data"

# Logging level (default: INFO)
export LOG_LEVEL="DEBUG"
```

See `.env.example` for the full list.

## Verify Installation

```bash
dd-agents version
```

This prints the installed version. If the command is not found, ensure the package
installed correctly and your PATH includes the Python scripts directory.

## First Run

The typical workflow is three steps: generate a config, run the pipeline, review the report.

### 1. Generate a Deal Configuration

The fastest path is `auto-config`, which uses AI to analyze your data room:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room
```

This produces a `deal-config.json` with buyer/target details, entity aliases,
focus areas, and data room mapping. See [Deal Configuration](deal-configuration.md)
for details.

Alternatively, use the interactive `init` command:

```bash
dd-agents init --data-room ./data_room
```

### 2. Run the Pipeline

```bash
dd-agents run deal-config.json
```

The pipeline executes 35 steps: extraction, entity resolution, agent analysis,
quality validation, and report generation. See [Running the Pipeline](running-pipeline.md)
for options and details.

For a quick red-flag triage without full analysis:

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

### 3. Review the Report

After the pipeline completes, find the outputs in `_dd/forensic-dd/runs/<timestamp>/report/`:

- `dd_report.html` -- Interactive HTML report with sidebar navigation and severity filtering
- `dd_report.xlsx` -- 14-sheet Excel report for detailed analysis

Open `dd_report.html` in a browser. See [Reading the Report](reading-report.md) for
a walkthrough of each section.

## Pre-Flight Check

Before running the full pipeline, assess your data room quality:

```bash
dd-agents assess ./data_room
```

This produces a health report covering file type distribution, extraction readiness,
and an overall completeness score. Address any critical issues before proceeding.

## Docker

Build and run in a container:

```bash
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v ./data_room:/workspace/data_room \
  dd-agents run deal-config.json
```

## Post-Run Workflows

After the pipeline completes, several additional tools are available:

### Contract Search

Search customer contracts with custom questions without running the full pipeline:

```bash
dd-agents search prompts.json --data-room ./data_room
```

### Natural Language Query

Ask questions about findings interactively or via a single question:

```bash
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many P0 findings?"
dd-agents query --report _dd/forensic-dd/runs/latest  # interactive REPL
```

### PDF Export

Export the HTML report to a print-optimized PDF:

```bash
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd_report.html
```

### Portfolio Management

Track multiple DD projects and compare risk profiles across deals:

```bash
dd-agents portfolio add "Alpha Acquisition" --data-room ./alpha_data_room
dd-agents portfolio list
dd-agents portfolio compare
```

### Collaborative Review

Annotate findings, assign reviewers, and track sign-off progress:

```bash
dd-agents review annotate --run-dir _dd/forensic-dd/runs/latest \
  --finding "Liability cap" --reviewer alice --status reviewed

dd-agents review assign --run-dir _dd/forensic-dd/runs/latest \
  --reviewer alice --section legal

dd-agents review progress --run-dir _dd/forensic-dd/runs/latest
```

### Report Templates

Apply pre-built templates for different audiences (Board Summary, Legal Deep Dive, etc.):

```bash
dd-agents templates list
dd-agents templates show board_summary
```

### REST API (Optional)

Start a REST API server for programmatic access (requires `pip install -e ".[api]"`):

```bash
DD_API_KEY="your-secret-key" uvicorn dd_agents.api.server:app --port 8000
```

See the [CLI Reference](cli-reference.md) for full documentation of all commands.

## Next Steps

- [Deal Configuration](deal-configuration.md) -- Config file structure and generation
- [Running the Pipeline](running-pipeline.md) -- Execution modes and options
- [Reading the Report](reading-report.md) -- Navigating the HTML and Excel output
- [CLI Reference](cli-reference.md) -- Complete command reference
