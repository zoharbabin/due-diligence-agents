# Due Diligence Agent SDK

> **Status**: Implemented. Full pipeline, contract search, and auto-config commands operational with 997+ passing tests.

Standalone Python application for forensic M&A due diligence. Migrates a Claude Code Skill (3,100+ lines across 9 files) to a programmatic pipeline using `claude-agent-sdk` v0.1.39+. Six agents (4 specialists + optional Judge + Reporting Lead) analyze contract data rooms, extract clauses, build governance graphs, detect gaps, and produce a 14-sheet Excel report — all under deterministic Python orchestration with hook-enforced quality gates.

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
│       ├── agents/              # Agent definitions, prompt builder, specialists
│       ├── extraction/          # Document extraction: pymupdf, markitdown, GLM-OCR, Claude vision
│       ├── entity_resolution/   # 6-pass cascading matcher, cache, rapidfuzz
│       ├── inventory/           # File discovery, customer registry, references
│       ├── validation/          # Numerical audit, QA, DoD checks, schema validation
│       ├── reporting/           # Merge/dedup, Excel generation, report diff
│       ├── persistence/         # Three-tier storage, run management, incremental
│       ├── hooks/               # SDK hooks (PreToolUse, PostToolUse, Stop)
│       ├── search/              # Contract search: analyzer, Excel writer, runner
│       ├── tools/               # Custom MCP tools (validate_finding, etc.)
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
    └── plan/                    # Implementation plan (22 spec files)
```

## Quick Start

```bash
# Install in development mode
pip install -e ".[dev]"

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

## Prerequisites

- Python 3.12+
- AWS Bedrock access (for Claude API)
- `markitdown` (pip install)
- `pdftotext` (poppler-utils)
- `tesseract-ocr` (optional, for scanned PDFs)

All Python dependencies are declared in `pyproject.toml`.

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

- **Open-source only** — All dependencies under permissive licenses (Apache 2.0, MIT, BSD). No commercial or subscription tools. LLM access via AWS Bedrock.
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

## License

Apache 2.0. See [LICENSE](LICENSE).
