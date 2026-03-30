# Due Diligence Agent SDK

**Automate M&A due diligence in minutes, not weeks.** Point **4 domain-specialist AI agents** (Legal, Finance, Commercial, Product/Tech) plus **4 synthesis and validation agents** at a contract data room and get a board-ready risk report with precise citations — no manual review of hundreds of PDFs.

## The Problem

M&A due diligence requires lawyers and analysts to manually review hundreds of contracts across dozens of counterparties, hunting for change-of-control clauses, liability caps, IP risk, revenue recognition issues, and termination rights. A typical data room review takes 4-12 weeks and costs 1-3% of deal value in professional fees. Critical risks get buried in volume.

**The market is massive and accelerating.** Global M&A deal value reached approximately $4.9 trillion in 2025 — up roughly 36-40% year-over-year — with megadeals (>$5B) surging over 70% (sources: Bain, PwC). Over 70% of M&A advisors expect deal flow to increase further in 2026 (Capstone/IMAP). Yet traditional due diligence hasn't scaled: manual review remains the bottleneck between signing and closing.

**AI adoption in M&A is doubling annually.** Nearly half of M&A practitioners now use AI in their deal processes, roughly double the prior year (Bain). Over half use GenAI specifically for due diligence and deal validation. 73% of lawyers rely on AI for document review (Thomson Reuters). AI-assisted contract review reduces review time by 70-90% according to vendor case studies (Luminance, LegalOn, Axiom).

**But existing tools are fragmented.** Virtual data rooms (Datasite, Intralinks, Ansarada) have added AI-assisted indexing and classification but don't perform deep analytical review. AI contract review tools (Luminance, Kira/Litera, LegalOn, Harvey) are legal-centric — single-domain clause extraction without cross-domain synthesis. CLM platforms (Ironclad, Robin AI) target post-signature lifecycle management. M&A workflow tools (Midaxo, DealRoom) handle project management and deal tracking, not content analysis. Financial-services AI platforms (Blueflame AI) and general-purpose GenAI frameworks (ZBrain) require extensive custom build-out. No existing solution provides multi-domain forensic analysis with adversarial cross-validation across Legal, Finance, Commercial, and Product/Tech — the full scope of what acquirers actually need.

This project fills that gap: an open-source, multi-agent pipeline that analyzes an entire data room across all four domains, cross-validates findings adversarially, and produces a board-ready report with precise citations — at a fraction of the cost and time of manual review or stitching together single-domain SaaS tools ($3K-30K+/month each).

## What You Get

Run `dd-agents` against a data room folder and receive:

- **Board-ready HTML report** — interactive, navigable, with Go/No-Go recommendation, risk heatmaps, severity filtering, and drill-down to exact contract clauses
- **14-sheet Excel companion** — structured findings, cross-references, entity resolution log, and audit trail for downstream analysis
- **Precise citations** — every finding links back to file, page, section, and exact quote
- **Quality-validated results** — 5 blocking gates, 6-layer numerical audit, 30 definition-of-done checks. Fail-closed: bad data halts the pipeline instead of producing bad reports

## Quick Start

```bash
# 1. Install
pip install -e "."

# 2. Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Auto-generate a deal config by scanning the data room with AI
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room

# 4. Run the full 35-step pipeline
dd-agents run deal-config.json
```

Open `_dd/forensic-dd/runs/latest/report/dd_report.html` in your browser. Done.

For a 5-minute red-flag triage instead of full analysis:

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

See the [Getting Started guide](docs/user-guide/getting-started.md) for a full walkthrough with the included sample data room.

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

Pre-flight check before running the full pipeline:

```bash
dd-agents assess ./data_room
```

Reports file type distribution, extraction readiness, and overall completeness score.

### Natural Language Query

Ask questions about findings after a run:

```bash
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many P0 findings?"
dd-agents query --report _dd/forensic-dd/runs/latest   # interactive mode
```

### PDF Export

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
dd-agents review annotate FINDING_ID --reviewer alice --status reviewed --comment "Verified"
dd-agents review progress --run-dir _dd/forensic-dd/runs/latest --total 200
```

### Report Templates

Apply pre-built templates for different audiences: **Full Report**, **Board Summary**, **Legal Deep Dive**, **Financial Analysis**, **Technical Assessment**.

```bash
dd-agents templates list
dd-agents templates show board_summary
```

### REST API (Optional)

Programmatic access via FastAPI (requires `pip install -e ".[api]"`):

```bash
DD_API_KEY="your-secret-key" uvicorn dd_agents.api.server:app --port 8000
```

Webhook notifications (HTTP, Slack, email) via `/api/v1/webhooks`.

## How It Works

A **35-step deterministic pipeline** orchestrated by Python, with AI agents as workers:

1. **Extract** — Discover and extract text from PDFs, Office docs, and images using pymupdf with fallback to markitdown, OCR, and Claude vision
2. **Resolve** — 6-pass cascading entity resolution matches counterparty names across documents, with document precedence scoring (version chains, folder trust tiers, recency)
3. **Analyze** — 4 domain-specialist agents (Legal, Finance, Commercial, ProductTech) analyze every customer's contracts in parallel with provision-specific prompts and 18 canonical clause types
4. **Validate** — Judge agent reviews findings adversarially; Executive Synthesis calibrates Go/No-Go; Red Flag Scanner provides quick triage; Acquirer Intelligence augments with market context
5. **Merge & Audit** — Deduplicate findings across agents, run 6-layer numerical audit and 30 definition-of-done checks with citation verification for P0-P2 findings
6. **Report** — Generate board-ready HTML report + 14-sheet Excel report with full audit trail

**5 blocking gates** halt the pipeline on quality failures rather than producing unreliable reports. Checkpoint/resume from any step.

## Pipeline Output

```
_dd/forensic-dd/
├── index/text/                     # Extracted document text (cached across runs)
├── inventory/                      # Customer registry, file counts
├── runs/
│   └── 20260225_143000/            # Timestamped run directory
│       ├── findings/
│       │   ├── legal/              # Per-agent raw findings
│       │   ├── finance/
│       │   ├── commercial/
│       │   ├── product_tech/
│       │   └── merged/             # Deduplicated merged findings
│       ├── report/
│       │   ├── dd_report.html      # Board-ready interactive HTML report
│       │   └── dd_report.xlsx      # 14-sheet Excel companion report
│       ├── audit.json              # QA validation results
│       └── metadata.json           # Run metadata and costs
└── entity_resolution_cache.json    # Entity matching cache (reused across runs)
```

## Prerequisites

- Python 3.12+
- Claude API access via `claude-agent-sdk` (Anthropic API key or AWS Bedrock credentials)

### API Key Setup

```bash
# Option A: Anthropic API (recommended)
export ANTHROPIC_API_KEY="sk-ant-..."

# Option B: AWS Bedrock
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

### System Dependencies (optional)

| Dependency | Install | Purpose |
|-----------|---------|---------|
| `poppler` | `brew install poppler` (macOS) / `apt install poppler-utils` (Linux) | Fallback PDF extraction |
| `tesseract-ocr` | `brew install tesseract` (macOS) / `apt install tesseract-ocr` (Linux) | OCR for scanned PDFs (English only; use GLM-OCR for multilingual) |

## Installation

```bash
pip install -e "."            # Core only
pip install -e ".[dev]"       # + dev tools (pytest, mypy, ruff)
pip install -e ".[vector]"    # + ChromaDB for semantic cross-document search
pip install -e ".[ocr]"       # + pytesseract OCR fallback (English only)
pip install -e ".[glm-ocr]"   # + GLM-OCR vision-language model (100+ languages, Apple Silicon / Ollama)
pip install -e ".[api]"       # + FastAPI for REST API server
```

All dependencies are open-source under permissive licenses (Apache 2.0, MIT, BSD). No commercial or subscription tools.

## Docker

```bash
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." -v ./data_room:/workspace/data_room dd-agents run deal-config.json
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/user-guide/getting-started.md) | Installation, first run, sample data room |
| [Deal Configuration](docs/user-guide/deal-configuration.md) | Config file structure, auto-generation |
| [Running the Pipeline](docs/user-guide/running-pipeline.md) | Execution modes, resume, blocking gates |
| [Reading the Report](docs/user-guide/reading-report.md) | HTML/Excel report navigation |
| [CLI Reference](docs/user-guide/cli-reference.md) | Complete command reference |
| [Search Guide](docs/search-guide.md) | Contract search for legal teams |
| [Architecture & Design](docs/plan/PLAN.md) | System architecture and 22 spec documents |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR process.

## License

Apache 2.0. See [LICENSE](LICENSE).
