# Getting Started

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
rapidfuzz, markitdown, pymupdf, click, rich) plus dev tools (pytest, mypy, ruff).

### Optional Dependencies

Install extras for additional capabilities:

```bash
pip install -e ".[vector]"     # ChromaDB for semantic cross-document search
pip install -e ".[ocr]"        # pytesseract + Pillow for OCR fallback on scanned PDFs
pip install -e ".[glm-ocr]"    # GLM-OCR vision-language model (Apple Silicon)
```

To install everything:

```bash
pip install -e ".[dev,vector,ocr,glm-ocr]"
```

### System Dependencies (optional)

| Dependency | Install | Purpose |
|-----------|---------|---------|
| `poppler` | `brew install poppler` (macOS) / `apt install poppler-utils` (Linux) | Fallback PDF extraction |
| `tesseract-ocr` | `brew install tesseract` (macOS) / `apt install tesseract-ocr` (Linux) | OCR for scanned PDFs |

## API Key Setup

Set one of these environment variables:

```bash
# Option A: Anthropic API (recommended)
export ANTHROPIC_API_KEY="sk-ant-..."

# Option B: AWS Bedrock
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

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

## Next Steps

- [Deal Configuration](deal-configuration.md) -- Config file structure and generation
- [Running the Pipeline](running-pipeline.md) -- Execution modes and options
- [Reading the Report](reading-report.md) -- Navigating the HTML and Excel output
- [CLI Reference](cli-reference.md) -- Complete command reference
