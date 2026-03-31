# Due Diligence Agents

**Cut weeks of contract review down to hours.** Point AI agents at your data room and get a risk report with findings traced back to exact contract clauses — across Legal, Finance, Commercial, and Product/Tech.

## Why This Exists

M&A due diligence requires teams to manually review hundreds of contracts across dozens of counterparties. A typical data room review takes 4-12 weeks and costs hundreds of thousands in professional fees. Critical risks get buried in volume.

This tool automates the first pass: 4 domain-specialist AI agents analyze every document, cross-validate findings, and produce a structured report. Your team then reviews AI-identified risks instead of reading every page — dramatically reducing time and cost while improving coverage.

**Important:** AI-generated findings require human review before any business decisions. This tool accelerates analysis; it does not replace professional judgment.

## What It Costs

| Scenario | Traditional Approach | With This Tool |
|----------|---------------------|----------------|
| 50-document data room | 2-4 weeks, $50K-$150K in legal fees | 15-30 min AI analysis + 4-8 hours expert review, $10-$50 in API costs |
| 200-document data room | 6-12 weeks, $150K-$500K+ | 1-3 hours AI analysis + 1-2 days expert review, $50-$200 in API costs |

Your legal and finance teams still review the output — but they start from a structured risk report instead of a stack of PDFs.

## What You Get

Run `dd-agents` against a data room folder and receive:

- **Interactive HTML report** with Go/No-Go recommendation, risk heatmaps, severity filtering, and drill-down to exact contract clauses
- **14-sheet Excel companion** with structured findings, cross-references, and audit trail for downstream analysis
- **Sourced citations** linking every finding back to file, page, section, and exact quote
- **Quality-validated results** with 5 blocking gates and 31 automated checks. The pipeline halts on quality failures rather than producing unreliable output

## Quick Start

**Prerequisites:** Python 3.12+ and an Anthropic API key ([get one here](https://console.anthropic.com/)).

Check your Python version: `python3 --version`. If you need Python 3.12+, download it from [python.org](https://www.python.org/downloads/).

```bash
# 1. Clone and install
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[pdf]"

# 2. Set your API key (or add to a .env file — see below)
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Scan the data room and generate a deal config
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room

# 4. Run the analysis
dd-agents run deal-config.json
```

Open `_dd/forensic-dd/runs/latest/report/dd_report.html` in your browser.

**Quick triage mode** — for a fast red-flag scan instead of full analysis:

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

**Useful flags:**
- `--dry-run` — preview what the pipeline will do without making API calls
- `--resume-from <step>` — resume an interrupted run from any step
- `--model-profile economy` — use cheaper, faster models

**No API key yet?** Generate a config without any API calls:

```bash
dd-agents init --data-room ./data_room
```

See the [Getting Started guide](docs/user-guide/getting-started.md) for a complete walkthrough with the included sample data room.

### Setting Your API Key

Choose one method:

**Option A — Environment variable** (temporary, lasts until you close the terminal):
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Option B — `.env` file** (persistent, recommended):
```bash
cp .env.example .env
# Edit .env and add your key
```

**Option C — AWS Bedrock** (if you use AWS):
```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

### Preparing Your Data Room

Organize contracts into folders by customer or counterparty:

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

The tool discovers and processes PDFs, Word documents, Excel files, and images. Scanned PDFs are handled via OCR.

## Key Features

### Contract Search

Run targeted questions across every customer's contracts and get an Excel report with answers and citations — without running the full pipeline.

```bash
dd-agents search prompts.json --data-room ./data_room
```

The prompts file is plain JSON that any legal professional can write:

```json
{
  "name": "Change of Control Analysis",
  "columns": [
    {
      "name": "Consent Required",
      "prompt": "Does this agreement require consent upon a change of control? Answer YES, NO, or NOT_ADDRESSED."
    }
  ]
}
```

See the [Search Guide](docs/search-guide.md) and [`examples/search/`](examples/search/) for ready-to-use templates.

### Data Room Assessment

Check data room quality before running the full pipeline:

```bash
dd-agents assess ./data_room
```

Reports file type distribution, extraction readiness, and overall completeness score.

### Natural Language Query

Ask questions about findings after a run:

```bash
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many high-severity findings?"
dd-agents query --report _dd/forensic-dd/runs/latest   # interactive mode
```

### PDF Export

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

Apply templates for different audiences: **Full Report**, **Board Summary**, **Legal Deep Dive**, **Financial Analysis**, **Technical Assessment**.

```bash
dd-agents templates list
dd-agents templates show board_summary
```

## How It Works

A **35-step automated pipeline** orchestrated by Python, with AI agents as workers:

1. **Extract** — Discover and extract text from PDFs, Word/Excel documents, and images (with OCR fallback for scanned documents)
2. **Match** — Identify and match company names across documents, handling aliases, abbreviations, and legal suffixes automatically
3. **Analyze** — 4 domain-specialist AI agents (Legal, Finance, Commercial, Product/Tech) analyze every customer's contracts in parallel
4. **Validate** — A Judge agent reviews findings for accuracy; an Executive Synthesis agent calibrates the Go/No-Go recommendation; a Red Flag Scanner provides quick triage
5. **Merge & Audit** — Deduplicate findings across agents, run automated numerical checks and 31 quality checks with citation verification
6. **Report** — Generate the HTML report and 14-sheet Excel report with full audit trail

**5 blocking quality gates** halt the pipeline on quality failures rather than producing unreliable reports. Runs can be resumed from any step.

## Pipeline Output

```
_dd/forensic-dd/
  index/text/                     # Extracted document text (cached across runs)
  inventory/                      # File discovery and company registry
  runs/
    latest/                       # Always points to the most recent run
      findings/
        legal/                    # Findings from each specialist agent
        finance/
        commercial/
        product_tech/
        merged/                   # Deduplicated findings across all agents
      report/
        dd_report.html            # Interactive HTML report
        dd_report.xlsx            # 14-sheet Excel companion report
      audit.json                  # Quality validation results
      metadata.json               # Run metadata and API costs
  entity_resolution_cache.json    # Company name matching cache (reused across runs)
```

## Installation

```bash
pip install -e "."            # Core (no PDF extraction)
pip install -e ".[pdf]"       # + PDF extraction via pymupdf (recommended)
pip install -e ".[dev]"       # + development tools (pytest, mypy, ruff)
pip install -e ".[vector]"    # + semantic search via ChromaDB
pip install -e ".[ocr]"       # + OCR for scanned documents (English)
pip install -e ".[glm-ocr]"   # + multilingual OCR (100+ languages, Apple Silicon)
```

### Optional System Dependencies

| Dependency | macOS | Linux | Purpose |
|-----------|-------|-------|---------|
| `poppler` | `brew install poppler` | `apt install poppler-utils` | Fallback PDF extraction |
| `tesseract` | `brew install tesseract` | `apt install tesseract-ocr` | OCR for scanned PDFs |

### Licensing

All core dependencies use permissive open-source licenses (Apache 2.0, MIT, BSD). The optional `[pdf]` extra installs pymupdf, which is AGPL-3.0 licensed — if you redistribute software that bundles pymupdf, AGPL copyleft terms apply to your distribution. Using it internally or as a tool does not trigger copyleft.

## Docker

```bash
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v ./data_room:/workspace/data_room \
  -v ./deal-config.json:/workspace/deal-config.json \
  dd-agents run deal-config.json
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/user-guide/getting-started.md) | Installation, first run with sample data room |
| [Deal Configuration](docs/user-guide/deal-configuration.md) | Config file structure, auto-generation |
| [Running the Pipeline](docs/user-guide/running-pipeline.md) | Execution modes, resume, quality gates |
| [Reading the Report](docs/user-guide/reading-report.md) | Navigating the HTML and Excel output |
| [CLI Reference](docs/user-guide/cli-reference.md) | Complete command reference |
| [Search Guide](docs/search-guide.md) | Contract search for legal teams |
| [Architecture & Design](docs/plan/PLAN.md) | System architecture and design documents |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR process.

## License

Apache 2.0. See [LICENSE](LICENSE).
