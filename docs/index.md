# DD-Agents — Forensic M&A Due Diligence

**Legal flags a risk. Finance flags another. We connect and cite.** Open-source forensic M&A due diligence — 13 AI agents read your entire data room across 9 specialist domains, cross-reference the findings no single reviewer connects, and trace every one to an exact page and verbatim quote. Quality-gated HTML + Excel reports.

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

## What dd-agents does (and does not) do

dd-agents is a forensic analysis accelerator for M&A due diligence. It:

- Reads an entire data room across 9 domains and cross-references findings no single reviewer connects
- Traces every finding to an exact page and verbatim quote
- **Accelerates** legal/financial advisors — it does **not** replace them
- Provides analysis used as a basis for deliverables (not a final "board-ready" document)
- Runs locally; documents only leave as API calls to your own LLM provider

**It does not**:

- Operate without human oversight — quality gates halt rather than ship unverified output
- Guarantee zero hallucinations (human review remains essential)
- Replace professional advisors or provide legal/financial/regulatory conclusions


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
# DD-Agents — Forensic M&A Due Diligence

**Legal flags a risk. Finance flags another. We connect and cite.** Open-source forensic M&A due diligence — 13 AI agents read your entire data room across 9 specialist domains, cross-reference the findings no single reviewer connects, and trace every one to an exact page and verbatim quote. Quality-gated HTML + Excel reports.

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
