# Documentation

The full documentation site is published at
**[zoharbabin.github.io/due-diligence-agents](https://zoharbabin.github.io/due-diligence-agents/)**.
This page indexes the same content for browsing on GitHub.

## User Guide

Start here if you're using the tool:

| Guide | Description |
|-------|-------------|
| [Getting Started](user-guide/getting-started.md) | Installation, first run, sample data room walkthrough |
| [Deal Configuration](user-guide/deal-configuration.md) | Config file structure, auto-generation, buyer strategy |
| [Model Providers](user-guide/model-providers.md) | Run on any provider/model — Anthropic API, Bedrock, Vertex, or any model via a gateway |
| [Provider Coverage](user-guide/provider-coverage.md) | Which flows are verified live on which providers |
| [Running the Pipeline](user-guide/running-pipeline.md) | Execution modes, resume, quality gates |
| [Reading the Report](user-guide/reading-report.md) | Progressive disclosure layout, verdict block, domain cards |
| [CLI Reference](user-guide/cli-reference.md) | Complete command reference |
| [Troubleshooting](user-guide/troubleshooting.md) | Common errors, exit codes, blocking gate recovery |

## Guides

| Doc | Topic |
|-----|-------|
| [How the Agents Work](agent-anatomy.md) | A non-technical reviewer's tour — what each specialist hunts for, how a briefing is assembled, and the non-removable safety floor. Read this to audit the tool before trusting it on a deal. |
| [Agent Customization](agent-customization.md) | Tune focus, persona, and severity per deal — without code |
| [Contract Search](search-guide.md) | Targeted contract search for legal teams (no full pipeline) |
| [Knowledge Architecture](knowledge-architecture.md) | Deal Knowledge Base — compounds insights across runs |

## Trust & Safety

| Doc | Topic |
|-----|-------|
| [System Card](system-card.md) | What the system does, its limits, and the safety model |
| [Eval Datasheet](eval-datasheet.md) | How agent quality is measured |

The code under `src/dd_agents/` is the authoritative source for current behavior.
For a fast orientation, read the **Architecture Map** and **Key Patterns** in
[`CLAUDE.md`](../CLAUDE.md) (repo root) — it annotates each package and its entry
point and is kept in sync with the code (CI-enforced by `tests/unit/test_docs_drift.py`).

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, code style, and PR process.
