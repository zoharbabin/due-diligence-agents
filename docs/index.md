# DD-Agents — Forensic M&A Due Diligence

Open-source integrated M&A due diligence — analyzes contract data rooms across 9 specialist domains using 13 AI agents, cross-references findings with exact citations, and produces quality-gated HTML + Excel reports.

## Quick Start

```bash
pip install dd-agents[pdf]
export ANTHROPIC_API_KEY="sk-ant-..."
dd-agents init --data-room ./your_data_room
dd-agents run deal-config.json
```

**[See a sample report →](https://zoharbabin.github.io/due-diligence-agents/sample-report/)**

## What It Does

| Command | Purpose |
|---------|---------|
| `dd-agents run` | Full 38-step pipeline across 9 domains |
| `dd-agents run --quick-scan` | Red flag triage in minutes |
| `dd-agents search` | Targeted contract questions with citations |
| `dd-agents chat` | Interactive multi-turn chat about findings |
| `dd-agents query` | Single-question mode |
| `dd-agents assess` | Data room quality check |

## Install Options

=== "pip (recommended)"

    ```bash
    pip install dd-agents[pdf]
    ```

=== "pipx (isolated CLI)"

    ```bash
    pipx install dd-agents[pdf]
    ```

=== "Homebrew (macOS)"

    ```bash
    brew install zoharbabin/due-diligence-agents/dd-agents
    ```

=== "Docker"

    ```bash
    docker pull zoharbabin/due-diligence-agents:latest
    docker run -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
      -v ./data_room:/data zoharbabin/due-diligence-agents run /data/deal-config.json
    ```

## Next Steps

- [Getting Started](user-guide/getting-started.md) — full installation and first-run walkthrough
- [Deal Configuration](user-guide/deal-configuration.md) — customize analysis focus areas
- [CLI Reference](user-guide/cli-reference.md) — every command, flag, and exit code
- [Contract Search Guide](search-guide.md) — targeted search without the full pipeline
