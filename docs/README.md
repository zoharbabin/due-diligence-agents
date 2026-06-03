# Documentation

## User Guide

Start here if you're using the tool:

| Guide | Description |
|-------|-------------|
| [Getting Started](user-guide/getting-started.md) | Installation, first run, sample data room walkthrough |
| [Deal Configuration](user-guide/deal-configuration.md) | Config file structure, auto-generation, buyer strategy |
| [Running the Pipeline](user-guide/running-pipeline.md) | 38-step pipeline, execution modes, resume, quality gates |
| [Reading the Report](user-guide/reading-report.md) | Progressive disclosure layout, verdict block, domain cards |
| [CLI Reference](user-guide/cli-reference.md) | Complete command reference |
| [Troubleshooting](user-guide/troubleshooting.md) | Common errors, exit codes, blocking gate recovery |
| [Search Guide](search-guide.md) | Contract search for legal teams (no full pipeline) |

## Architecture & Design

Start with [PLAN.md](plan/PLAN.md) for the system architecture overview. The `plan/` directory contains the design documents from the build phase. These are historical specs — the code in `src/dd_agents/` is authoritative for current behavior. The plan docs explain *why* the system was designed this way.

Key architecture docs:

| Doc | Topic |
|-----|-------|
| [System Architecture](plan/02-system-architecture.md) | Persistence tiers, pipeline state machine |
| [Orchestrator](plan/05-orchestrator.md) | 38-step pipeline, blocking gates, checkpoint/resume |
| [Agents](plan/06-agents.md) | 13 agents, specialist domains, extensible registry |
| [Tools & Hooks](plan/07-tools-and-hooks.md) | MCP tools, PreToolUse/Stop hooks |
| [Extraction](plan/08-extraction.md) | PDF/Office extraction, OCR, chunking |
| [Reporting](plan/10-reporting.md) | HTML + Excel report generation |
| [Cross-Document Analysis](plan/20-cross-document-analysis.md) | Cross-domain trigger rules, neurosymbolic reasoning |
| [Ontology & Reasoning](plan/21-ontology-and-reasoning.md) | Domain dependency graph, symbolic triggers |
| [LLM Robustness](plan/22-llm-robustness.md) | Search, chunking, citation verification |

## Knowledge Base

| Doc | Topic |
|-----|-------|
| [Knowledge Architecture](knowledge-architecture.md) | Deal Knowledge Base — compounds insights across runs |
| [Extraction Knowledge Base](extraction-knowledge-base.md) | Extraction layer internals |

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, code style, and PR process.
