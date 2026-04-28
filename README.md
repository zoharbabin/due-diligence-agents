<p align="center">
  <h1 align="center">Due Diligence Agents</h1>
  <p align="center">
    Find what gets buried in the data room. Open-source integrated M&A due diligence — legal, financial, commercial, and technical analysis across every contract, cross-referenced with exact citations.
  </p>
  <p align="center">
    <a href="https://pypi.org/project/dd-agents/"><img src="https://img.shields.io/pypi/v/dd-agents.svg" alt="PyPI version"></a>
    <a href="https://pypi.org/project/dd-agents/"><img src="https://img.shields.io/pypi/dm/dd-agents.svg" alt="PyPI downloads"></a>
    <a href="https://github.com/zoharbabin/due-diligence-agents/actions"><img src="https://github.com/zoharbabin/due-diligence-agents/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green.svg" alt="License"></a>
    <img src="https://img.shields.io/badge/tests-3,549-brightgreen.svg" alt="Tests">
    <img src="https://img.shields.io/badge/mypy-strict-blue.svg" alt="mypy strict">
    <a href="https://github.com/zoharbabin/due-diligence-agents/stargazers"><img src="https://img.shields.io/github/stars/zoharbabin/due-diligence-agents?style=social" alt="GitHub Stars"></a>
  </p>
</p>

---

**[See a sample report](https://zoharbabin.github.io/due-diligence-agents/)** — interactive HTML output from a synthetic 4-subject deal, no install required.

---

Finds what gets buried across hundreds of contracts — cross-references it across legal, financial, commercial, and technical domains — and traces every finding to an exact page, section, and quote. Use the structured output alongside your advisors to build IC memos, advisor reports, negotiation checklists, or integration plans.

> **This tool does not replace professional advisors.** Legal, financial, and regulatory conclusions should always be made by qualified professionals. This tool helps your team and advisors work faster.

## Why This Exists

I built this to solve my own problem. As a corp dev lead, I'd spend weeks assembling the cross-domain picture from siloed advisor reports — legal, financial, and commercial teams all flagging the same subject independently, with nobody connecting the dots. A termination clause in one contract and a revenue concentration risk in the same subject would be flagged in separate workstreams, if at all.

The numbers tell the story:

- **31% of M&A failures trace back to due diligence shortcomings** — [Acquisition Stars](https://acquisitionstars.com/ma-failure-rate/), citing HBR, McKinsey, and KPMG research
- **DD timelines keep compressing** — what used to be a six-week process becomes three weeks, with no reduction in scope — [Spellbook](https://www.spellbook.legal/briefs/m-a-due-diligence)
- **Corp dev teams screen 200-1,000+ companies/year** but close only 1-10 — a 1-3% conversion rate, with DD costs sunk on every deal that doesn't close — [CorpDev.AI](https://www.corpdev.ai/wiki/fundamentals/corpdev-metrics)
- **AI contract analysis reaches 95% accuracy** with clause-aware prompting (up from 74% baseline) — [Addleshaw Goddard RAG Report](https://www.addleshawgoddard.com/globalassets/insights/technology/llm/rag-report.pdf), 510 contracts tested
- **86% of M&A organizations have integrated GenAI** into deal workflows — [Deloitte 2025 M&A Trends](https://www.deloitte.com/us/en/what-we-do/capabilities/mergers-acquisitions-restructuring/articles/m-a-trends-report.html)

This tool runs all four workstreams in parallel across every document, cross-references findings automatically, and produces structured analysis your team can search, filter, and drill into — the kind of cross-domain picture that used to take weeks to assemble manually.

**Who uses this:** Corp dev teams screening targets, PE firms running portfolio DD, legal teams doing contract review, advisors accelerating workstreams. Anyone who needs to search hundreds of contracts and connect findings across domains.

## What You Can Do

### Full Pipeline — Integrated Due Diligence

```bash
dd-agents run deal-config.json
```

Analyzes every document through 4 domain lenses, cross-references findings, and validates quality through 5 blocking gates. Produces:

- **Interactive HTML report** — cross-domain findings, risk heatmaps, severity filtering, drill-down to exact clauses
- **14-sheet Excel report** — structured findings, cross-references, audit trail for downstream modeling
- **Per-subject JSON findings** — every finding with severity, citations, cross-references, and governance graph edges

### Quick Scan — Red Flag Triage in Minutes

```bash
dd-agents run deal-config.json --quick-scan --model-profile economy
```

GREEN / YELLOW / RED signal across 8 deal-killer categories. Get a first read before committing to full analysis.

### Contract Search — Targeted Questions, No Full Pipeline

```bash
dd-agents search prompts.json --data-room ./data_room
```

Ask specific questions across every contract and get an Excel report with answers, citations, and verification scores. The prompts file is plain JSON any legal professional can write:

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

See [`examples/search/`](examples/search/) for ready-to-use templates.

### Post-Run Tools

```bash
dd-agents chat --report _dd/forensic-dd/runs/latest         # Interactive multi-turn chat with memory
dd-agents query --report _dd/forensic-dd/runs/latest        # Ask questions about findings
dd-agents assess ./data_room                                # Check data room quality
dd-agents portfolio add "Deal A" --data-room ./data_room_a  # Track multiple deals
dd-agents portfolio compare                                 # Compare risk across deals
dd-agents export-pdf report.html                            # Export to PDF
dd-agents log                                               # Browse the deal knowledge timeline
dd-agents lineage --finding-id F-001                        # Trace a finding back to source
dd-agents health                                            # Check knowledge base integrity
dd-agents annotate F-001 "Confirmed with counsel"           # Add analyst notes to findings
```

## Quick Start

**Prerequisites:** Python 3.12+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
# 1. Install
pip install dd-agents[pdf]

# 2. Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Generate a deal config (AI scans the data room and infers entity aliases, focus areas)
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room

# 4. Run the analysis
dd-agents run deal-config.json
```

<details>
<summary><strong>Install from source (development)</strong></summary>

```bash
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[dev,pdf]"
```
</details>

Open `_dd/forensic-dd/runs/latest/report/dd_report.html` in your browser.

**No API key yet?** Generate a config without any API calls: `dd-agents init --data-room ./data_room`

See the [Getting Started guide](docs/user-guide/getting-started.md) for a complete walkthrough with the included sample data room.

<details>
<summary><strong>API Key Options</strong></summary>

**Environment variable** (temporary):
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**`.env` file** (persistent, recommended):
```bash
cp .env.example .env
# Edit .env and add your key
```

**AWS Bedrock** (if you use AWS):
```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```
</details>

<details>
<summary><strong>Preparing Your Data Room</strong></summary>

Organize contracts into folders by subject or counterparty:

```
data_room/
  SubjectGroup_A/
    Acme_Corp/
      master_agreement.pdf
      amendment_2024.pdf
    Beta_Inc/
      license_agreement.pdf
  SubjectGroup_B/
    Gamma_LLC/
      services_contract.docx
  _reference/                    # Optional: buyer overview, customer database, etc.
    buyer_overview.pdf
```

Supports PDFs, Word, Excel, PowerPoint, and images. Scanned PDFs are handled via OCR.
</details>

## How It Works

```
  Data Room (PDFs, Word, Excel, Images)
       │
       ▼
  ┌─────────────────────────────────────┐
  │        Python Orchestrator          │
  │         35-step pipeline            │
  │       5 blocking quality gates      │
  └──────────────┬──────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
 ┌──────┐  ┌────────┐  ┌──────────┐  ┌──────────┐
 │Legal │  │Finance │  │Commercial│  │ProductTech│
 │Agent │  │ Agent  │  │  Agent   │  │  Agent   │
 └──┬───┘  └───┬────┘  └────┬─────┘  └────┬─────┘
    │          │             │             │
    └──────────┴──────┬──────┴─────────────┘
                      │
              ┌───────▼────────┐
              │  Judge Agent   │  ← Validates findings
              │  (optional)    │
              └───────┬────────┘
                      │
              ┌───────▼────────┐
              │  Merge & Audit │  ← Dedup, numerical checks,
              │  31 QA checks  │    citation verification
              └───────┬────────┘
                      │
              ┌───────▼────────┐
              │   Executive    │  ← Severity calibration,
              │   Synthesis    │    Go/No-Go signal
              └───────┬────────┘
                      │
                      ▼
            HTML + Excel + JSON
```

**4 domain specialists** analyze every document in parallel. A **Judge** spot-checks findings. **Executive Synthesis** calibrates severity and the Go/No-Go signal. **Red Flag Scanner** provides quick triage. **Acquirer Intelligence** maps findings to the buyer's thesis (when configured).

The pipeline **halts on quality failures** rather than producing unreliable output. Runs can be resumed from any step.

## What Gets Analyzed

| Domain | Focus Areas |
|-------|-------------|
| **Legal** | Change of control (5 subtypes), anti-assignment, termination clauses, IP ownership, data privacy, indemnification, liability caps, warranty, dispute resolution, governance graph construction |
| **Finance** | Revenue cross-referencing (flags >5% ARR mismatch), revenue decomposition, unit economics (CAC/LTV/NRR/GRR), pricing compliance, cost structure, financial projections |
| **Commercial** | Renewal mechanics, churn risk, SLA commitments, volume commitments, customer segmentation (flags >30% concentration), pricing models, MFN clauses, competitive positioning |
| **ProductTech** | DPA analysis, security certifications (SOC2/ISO27001), technical SLAs, integration requirements, data portability, migration complexity, technical debt, vendor lock-in |

## Pipeline Output

```
_dd/forensic-dd/
  index/text/                     # Extracted document text (cached across runs)
  inventory/                      # File discovery and company registry
  runs/
    latest/                       # Always points to the most recent run
      findings/
        legal/                    # Per-subject findings from each agent
        finance/
        commercial/
        product_tech/
        merged/                   # Deduplicated cross-domain findings
      report/
        dd_report.html            # Interactive HTML report
        dd_report.xlsx            # 14-sheet Excel report
      audit.json                  # 31 quality validation checks
      numerical_manifest.json     # Every financial figure traced to source
      metadata.json               # Run metadata and API costs
  knowledge/                      # Deal Knowledge Base (compounds across runs)
    articles/                     # Structured knowledge articles
    chronicle.jsonl               # Append-only timeline of all events
    graph.json                    # Cross-reference knowledge graph
  entity_resolution_cache.json    # Company name matching (reused across runs)
```

## Installation

```bash
pip install dd-agents[pdf]      # Recommended (includes PDF extraction via pymupdf)
```

<details>
<summary><strong>Alternative install methods</strong></summary>

```bash
# macOS (Homebrew)
brew install zoharbabin/due-diligence-agents/dd-agents

# Docker
docker pull ghcr.io/zoharbabin/due-diligence-agents:latest

# Extras
pip install dd-agents           # Core only (no PDF extraction)
pip install dd-agents[vector]   # + semantic search via ChromaDB
pip install dd-agents[ocr]      # + OCR for scanned documents (English)
pip install dd-agents[glm-ocr]  # + multilingual OCR (100+ languages, Apple Silicon)
```
</details>

<details>
<summary><strong>Optional System Dependencies</strong></summary>

| Dependency | macOS | Linux | Purpose |
|-----------|-------|-------|---------|
| `poppler` | `brew install poppler` | `apt install poppler-utils` | Fallback PDF extraction |
| `tesseract` | `brew install tesseract` | `apt install tesseract-ocr` | OCR for scanned PDFs |

These are optional — the tool works without them but may produce lower-quality text from some scanned documents.
</details>

<details>
<summary><strong>Docker</strong></summary>

```bash
# Pre-built image (recommended)
docker pull ghcr.io/zoharbabin/due-diligence-agents:latest
docker run -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v ./data_room:/workspace/data_room \
  -v ./deal-config.json:/workspace/deal-config.json \
  ghcr.io/zoharbabin/due-diligence-agents run deal-config.json

# Or build from source
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v ./data_room:/workspace/data_room \
  -v ./deal-config.json:/workspace/deal-config.json \
  dd-agents run deal-config.json
```
</details>

### Licensing

All core dependencies use permissive open-source licenses (Apache 2.0, MIT, BSD). The optional `[pdf]` extra installs pymupdf, which is AGPL-3.0 licensed — if you redistribute software that bundles pymupdf, AGPL copyleft terms apply to your distribution. Using it internally or as a tool does not trigger copyleft.

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

## Star History

If this project is useful to you, consider giving it a star — it helps others discover it.

[![Star History Chart](https://api.star-history.com/svg?repos=zoharbabin/due-diligence-agents&type=Date)](https://star-history.com/#zoharbabin/due-diligence-agents&Date)

## License

Apache 2.0. See [LICENSE](LICENSE).
