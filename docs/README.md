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

The code under `src/dd_agents/` is the authoritative source for current behavior.
For a fast orientation, read the **Architecture Map** and **Key Patterns** in
[`CLAUDE.md`](../CLAUDE.md) (repo root) — it annotates each package and its entry
point and is kept in sync with the code.

## Knowledge Base

| Doc | Topic |
|-----|-------|
| [Knowledge Architecture](knowledge-architecture.md) | Deal Knowledge Base — compounds insights across runs |
| [Extraction Knowledge Base](extraction-knowledge-base.md) | Extraction layer internals |

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, code style, and PR process.
