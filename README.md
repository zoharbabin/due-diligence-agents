# Due Diligence Agent SDK

> **Status**: Production-tested. Full 35-step pipeline, contract search, auto-config, data room assessment, NL query, PDF export, portfolio management, collaborative review, report templates, REST API, and contract reasoning operational with 2,797 passing unit tests, mypy strict clean (164 source files), ruff clean.

Standalone Python application for forensic M&A due diligence. Eight agents (4 specialists + optional Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence) analyze contract data rooms, extract clauses, build governance graphs, detect gaps, and produce a board-ready HTML report + 14-sheet Excel report — all under deterministic Python orchestration with hook-enforced quality gates. Powered by `claude-agent-sdk` v0.1.39+ (Claude API or AWS Bedrock).

## Project Structure

```
due-diligence-agents/
├── pyproject.toml               # Package config, dependencies
├── LICENSE                      # Apache 2.0
├── .env.example                 # Environment variable template
├── src/
│   └── dd_agents/               # Main package
│       ├── models/              # Pydantic v2 data models (20+ schemas)
│       ├── orchestrator/        # 35-step pipeline, state machine, checkpoints
│       ├── agents/              # 4 specialists + Judge + Executive Synthesis + Red Flag Scanner + Acquirer Intelligence
│       ├── extraction/          # Document extraction: pymupdf, markitdown, GLM-OCR, Claude vision
│       ├── entity_resolution/   # 6-pass cascading matcher, dedup, cache, rapidfuzz
│       ├── inventory/           # File discovery, customer registry, references
│       ├── validation/          # Numerical audit, QA, DoD checks, schema validation
│       ├── reporting/           # Merge/dedup, Excel generation, HTML review, report diff
│       ├── persistence/         # Three-tier storage, run management, incremental
│       ├── hooks/               # SDK hooks (PreToolUse, PostToolUse, Stop)
│       ├── search/              # Contract search: analyzer, Excel writer, runner
│       ├── query/               # Natural language query engine (NL Q&A over findings)
│       ├── tools/               # Custom MCP tools (validate_finding, etc.)
│       ├── review/              # Collaborative review & annotation layer
│       ├── api/                 # REST API server (FastAPI, optional) + webhook notifications
│       ├── reasoning/           # Contract ontology & relationship reasoning (NetworkX graph)
│       ├── testing/             # Synthetic data room generator for E2E tests
│       ├── utils/               # Naming conventions, constants, shared utilities
│       └── vector_store/        # Optional ChromaDB integration
├── examples/
│   ├── quickstart/              # Quickstart guide with sample data room
│   └── search/                  # Ready-to-use prompt templates
├── tests/
│   ├── fixtures/                # Test data rooms, sample configs
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── config/                      # Deal config templates, JSON schemas
└── docs/
    ├── search-guide.md          # Search command guide for legal teams
    ├── user-guide/              # User documentation (getting started, CLI reference, etc.)
    └── plan/                    # Implementation plan (24 spec files)
```

## Quick Start

```bash
# Install in development mode
pip install -e ".[dev]"

# Assess data room quality before running (pre-flight check)
dd-agents assess ./data_room

# Auto-generate deal-config.json by scanning a data room with AI
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room

# Run the full 35-step pipeline against the generated config
dd-agents run deal-config.json

# Run with incremental mode
dd-agents run deal-config.json --mode incremental
```

## Auto-Config

The `auto-config` command replaces manual configuration. Point it at a data room folder, provide the buyer and target company names, and Claude analyzes the directory structure, file names, and metadata to produce a complete `deal-config.json` — including resolved legal entity names, subsidiaries, historical names, entity variants for contract matching, and recommended focus areas.

```bash
# Basic usage (writes deal-config.json to current directory)
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room

# Preview what would be generated without writing a file
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room --dry-run

# Override the inferred deal type
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room --deal-type merger

# Save to a specific path and overwrite if it exists
dd-agents auto-config "Buyer Corp" "Target Inc" --data-room ./data_room \
  --output configs/my-deal.json --force
```

**Options:**

| Flag | Description |
|------|-------------|
| `BUYER` | Name of the acquiring company (positional, required) |
| `TARGET` | Name of the company being acquired/evaluated (positional, required) |
| `--data-room PATH` | Path to the data room folder (required) |
| `--deal-type TYPE` | Override inferred deal type (`acquisition`, `merger`, `divestiture`, `investment`, `joint_venture`, `other`) |
| `--output PATH` | Where to save the config (default: `deal-config.json`) |
| `--dry-run` | Print the generated config without writing to disk |
| `--force` | Overwrite output file if it already exists |
| `--verbose` / `-v` | Enable debug logging |

The generated config includes everything needed to run the full pipeline: buyer/target details, entity aliases, focus areas, and data room mapping. You can review and edit it before running `dd-agents run`.

## Contract Search

Run targeted questions against every customer's contracts and get an Excel report with answers and precise citations — without running the full pipeline.

```bash
# Analyze all customers in a data room
dd-agents search prompts.json --data-room ./data_room

# Filter to specific customers
dd-agents search prompts.json --data-room ./data_room --customers "Acme,Beta Corp"

# Skip confirmation and save to specific file
dd-agents search prompts.json --data-room ./data_room -y --output results.xlsx
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

The Excel output has two sheets: **Summary** (one row per customer, color-coded answers) and **Details** (one row per citation with file path, page, section, exact quote).

See the [Search Command Guide](docs/search-guide.md) for full documentation, prompt writing tips, and troubleshooting. See [`examples/search/`](examples/search/) for ready-to-use prompt templates.

## Pipeline Output

After running, results appear in `_dd/forensic-dd/`:

```
_dd/forensic-dd/
├── index/text/                     # Extracted document text (cached across runs)
├── inventory/                      # Discovered files, customers, counts
│   ├── customers.csv
│   └── counts.json
├── runs/
│   └── 20260225_143000/            # Timestamped run directory
│       ├── findings/
│       │   ├── legal/              # Per-agent raw findings
│       │   ├── finance/
│       │   └── merged/             # Deduplicated merged findings
│       ├── report/
│       │   ├── dd_report.html      # Board-ready interactive HTML report
│       │   └── dd_report.xlsx      # 14-sheet Excel companion report
│       ├── audit.json              # QA validation results
│       └── metadata.json           # Run metadata
└── entity_resolution_cache.json    # Entity matching cache (reused across runs)
```

**Key files**: `dd_report.html` is the board-ready HTML report (executive summary, interactive dashboards, domain analysis, entity detail, methodology). `dd_report.xlsx` is the 14-sheet Excel companion. `audit.json` shows whether all validation gates passed.

### Post-Run Commands

```bash
# Export HTML report to PDF
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd_report.html

# Ask questions about findings
dd-agents query --report _dd/forensic-dd/runs/latest -q "How many P0 findings?"

# Interactive Q&A mode
dd-agents query --report _dd/forensic-dd/runs/latest
```

## Portfolio Management

Manage multiple DD projects and compare across deals:

```bash
# Register a new DD project
dd-agents portfolio add "Alpha Acquisition" --data-room ./alpha_data_room

# List all projects
dd-agents portfolio list

# Compare risk profiles across deals
dd-agents portfolio compare

# Remove a project from the registry
dd-agents portfolio remove alpha_acquisition
```

## Collaborative Review

Annotate findings, assign reviewers, and track sign-off progress:

```bash
# Annotate a finding (by finding ID from the report)
dd-agents review annotate FINDING_ID --reviewer alice --status reviewed --comment "Verified"

# Assign a reviewer to a section
dd-agents review assign alice --section legal

# Check review progress
dd-agents review progress --run-dir _dd/forensic-dd/runs/latest --total 200

# Export annotations as CSV
dd-agents review export --run-dir _dd/forensic-dd/runs/latest --format csv
```

## Report Templates

Browse and apply pre-built report templates for different audiences:

```bash
# List available templates
dd-agents templates list

# Show template details
dd-agents templates show board_summary
```

Built-in templates: **Full Report**, **Board Summary**, **Legal Deep Dive**, **Financial Analysis**, **Technical Assessment**. Custom templates can be saved as JSON files.

## REST API (Optional)

Start a REST API server for programmatic access (requires `pip install -e ".[api]"`):

```bash
# Start the API server
DD_API_KEY="your-secret-key" uvicorn dd_agents.api.server:app --port 8000

# Example: start a run via API
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Authorization: Bearer your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"config_path": "deal-config.json"}'
```

Webhook notifications (HTTP, Slack, email) can be configured via the `/api/v1/webhooks` endpoint.

## Implementation Plan

The full implementation plan is in [`docs/plan/`](docs/plan/). Start with the [executive overview](docs/plan/PLAN.md).

| # | File | Description |
|---|------|-------------|
| 01 | [Architecture Decisions](docs/plan/01-architecture-decisions.md) | 6 ADRs: SDK over Skills, file storage, ChromaDB optional, NetworkX, Pydantic v2, programmatic orchestration |
| 02 | [System Architecture](docs/plan/02-system-architecture.md) | Control/data flow, three-tier persistence, agent interaction model |
| 03 | [Project Structure](docs/plan/03-project-structure.md) | `src/dd_agents/` package layout, module boundaries, entry points |
| 04 | [Data Models](docs/plan/04-data-models.md) | Pydantic v2 models: findings, gaps, manifests, config, inventory, quality scores |
| 05 | [Orchestrator](docs/plan/05-orchestrator.md) | 35-step pipeline, 5 blocking gates, state machine, step dependencies |
| 06 | [Agents](docs/plan/06-agents.md) | 6 agent definitions, prompt construction, model selection, tool access |
| 07 | [Tools & Hooks](docs/plan/07-tools-and-hooks.md) | Stop hooks, PreToolUse guards, custom MCP tools, validation hooks |
| 08 | [Extraction](docs/plan/08-extraction.md) | PDF pre-inspection, 7-step fallback chain (pymupdf → GLM-OCR → Claude vision), checksum cache |
| 09 | [Entity Resolution](docs/plan/09-entity-resolution.md) | 6-pass cascading matcher, cache learning, rapidfuzz |
| 10 | [Reporting](docs/plan/10-reporting.md) | 14-sheet Excel, report schema, merge/dedup, report diff |
| 11 | [QA & Validation](docs/plan/11-qa-validation.md) | 5-layer numerical audit, 30 DoD checks, fail-closed gates |
| 12 | [Error Recovery](docs/plan/12-error-recovery.md) | 15 error scenarios, per-agent retry, timeout handling |
| 13 | [Multi-Project](docs/plan/13-multi-project.md) | Data isolation between deals, project registry |
| 14 | [Vector Store](docs/plan/14-vector-store.md) | Optional ChromaDB integration, semantic search |
| 15 | [Testing & Deployment](docs/plan/15-testing-deployment.md) | Test pyramid, CI/CD, Docker |
| 16 | [Migration](docs/plan/16-migration.md) | 5-phase migration from Skill to SDK |
| 17 | [File Manifest](docs/plan/17-file-manifest.md) | Complete inventory: 92 files across 16 categories |
| 18 | [Implementation Order](docs/plan/18-implementation-order.md) | Phased build plan, dependency graph, critical path |
| 19 | [Vector/Graph DB Comparison](docs/plan/19-vector-graph-db-comparison.md) | ChromaDB, Qdrant, ruvector, NetworkX, and alternatives |
| 20 | [Cross-Document Analysis](docs/plan/20-cross-document-analysis.md) | Contract hierarchy, overrides, contradictions, missing docs, renewal chains |
| 21 | [Ontology & Reasoning](docs/plan/21-ontology-and-reasoning.md) | Contract ontology, graph-based reasoning, explainability, hallucination prevention |
| 22 | [LLM Robustness](docs/plan/22-llm-robustness.md) | Research-informed mitigations: chunking, context management, hallucination prevention, Excel handling |
| -- | [Structured Output Plan](docs/plan/structured-output-plan.md) | Pydantic-validated structured LLM outputs across all agents |

## Prerequisites

- Python 3.12+
- Claude API access via `claude-agent-sdk` (Anthropic API key or AWS Bedrock credentials)

### System Dependencies

| Dependency | Platform Install | Required? |
|-----------|-----------------|-----------|
| `poppler` (provides `pdftotext`) | `brew install poppler` (macOS) / `apt-get install poppler-utils` (Linux) | Optional — fallback for pymupdf failures |
| `tesseract-ocr` | `brew install tesseract` (macOS) / `apt-get install tesseract-ocr` (Linux) | Optional — OCR for scanned PDFs |

### Python Dependencies

Core Python dependencies are installed automatically:

```bash
pip install -e "."            # Core only
pip install -e ".[dev]"       # Core + dev tools (pytest, mypy, ruff)
```

Optional extras for additional capabilities:

```bash
pip install -e ".[vector]"    # ChromaDB for semantic cross-document search
pip install -e ".[ocr]"       # pytesseract + Pillow for OCR fallback
pip install -e ".[glm-ocr]"   # GLM-OCR vision-language model (Apple Silicon)
pip install -e ".[api]"       # FastAPI + uvicorn for REST API server
```

For full development with all extras:

```bash
pip install -e ".[dev,vector,ocr,glm-ocr,api]"
# or use the Makefile:
make install-dev
```

### API Key Setup

Set one of these environment variables before running the pipeline:

```bash
# Option A: Anthropic API (recommended)
export ANTHROPIC_API_KEY="sk-ant-..."

# Option B: AWS Bedrock
export AWS_PROFILE=default
export AWS_REGION=us-east-1
```

Unit and integration tests run without an API key. Only E2E tests require one.

## Developer Onboarding

1. Read `docs/plan/PLAN.md` for the executive overview.
2. Read `docs/plan/01-architecture-decisions.md` for key architectural choices.
3. Read `docs/plan/18-implementation-order.md` for the build sequence.
4. Follow `IMPLEMENTATION_PLAN.md` phase by phase to implement.

## Autonomous Implementation (Claude Code)

This project is structured for autonomous implementation by Claude Code:

- **`CLAUDE.md`** — Project instructions loaded automatically at session start
- **`IMPLEMENTATION_PLAN.md`** — Phased execution plan with TDD workflow and status tracking
- **`.claude/settings.json`** — Tool permissions and quality gate hooks
- **`.claude/agents/`** — Custom subagents (code-reviewer, test-runner)
- **`scripts/`** — Quality gate scripts (lint, test, type check, pre-commit gate)
- **`Makefile`** — Convenience targets (`make verify`, `make test`, `make lint`)

**To start autonomous implementation:**
```bash
cd due-diligence-agents
pip install -e ".[dev]"
claude    # Claude Code reads CLAUDE.md + IMPLEMENTATION_PLAN.md automatically
```

Each phase is designed to fit within a single Claude Code session. Use `/clear` between phases.

## Key Technical Choices

- **Open-source only** — All dependencies under permissive licenses (Apache 2.0, MIT, BSD). No commercial or subscription tools. LLM access via `claude-agent-sdk` (Anthropic API or AWS Bedrock).
- **Python 3.12+** with `src/dd_agents/` package layout
- **claude-agent-sdk v0.1.39+** — agents are workers, Python controls flow
- **Pydantic v2** — all data schemas, JSON Schema export for structured outputs
- **openpyxl** — Excel report generation from `report_schema.json`
- **NetworkX** — governance graph construction (~900 edges, in-memory)
- **rapidfuzz** — token-sort-ratio fuzzy matching for entity resolution
- **ChromaDB** (optional) — cross-document semantic search
- **markitdown** — PDF/Office extraction
- **pymupdf** (fitz) — Primary PDF extraction with page markers
- **GLM-OCR** (optional) — High-quality vision-LM OCR for scanned PDFs

## Docker

Build and run in a container:

```bash
docker build -t dd-agents .
docker run -e ANTHROPIC_API_KEY="sk-ant-..." -v ./data_room:/workspace/data_room dd-agents run deal-config.json
```

The multi-stage Dockerfile uses `python:3.12-slim`, installs `poppler-utils` for PDF fallback, and runs as a non-root user.

## License

Apache 2.0. See [LICENSE](LICENSE).
