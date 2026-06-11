# Due Diligence Agents

**Legal flags a risk. Finance flags another. We connect and cite.** Open-source forensic M&A due diligence — 13 AI agents read your entire data room across 9 specialist domains (Legal, Finance, Commercial, ProductTech, Cybersecurity, HR, Tax, Regulatory, ESG), cross-reference the findings no single reviewer connects, and trace every one to an exact page and verbatim quote.

[![GitHub](https://img.shields.io/github/stars/zoharbabin/due-diligence-agents?style=social)](https://github.com/zoharbabin/due-diligence-agents)
[![PyPI](https://img.shields.io/pypi/v/dd-agents.svg)](https://pypi.org/project/dd-agents/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](https://github.com/zoharbabin/due-diligence-agents/blob/main/LICENSE)

**[📄 Documentation](https://zoharbabin.github.io/due-diligence-agents/)** · **[📊 Sample Report](https://zoharbabin.github.io/due-diligence-agents/sample-report/)** · **[💻 Source Code](https://github.com/zoharbabin/due-diligence-agents)**

---

## Quick Start

```bash
docker pull zoharbabin/due-diligence-agents:latest

# Generate a deal configuration
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v ./data_room:/data \
  zoharbabin/due-diligence-agents auto-config "Buyer Corp" "Target Inc" --data-room /data

# Run the full analysis pipeline
docker run --rm \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v ./data_room:/data \
  -v ./deal-config.json:/workspace/deal-config.json \
  zoharbabin/due-diligence-agents run /workspace/deal-config.json
```

Output appears in your data room at `_dd/forensic-dd/runs/latest/report/`.

## What It Does

| Command | Purpose |
|---------|---------|
| `run deal-config.json` | Full 38-step pipeline across 9 domains with 5 blocking quality gates |
| `run --quick-scan` | Red flag triage (GREEN/YELLOW/RED) in minutes |
| `search prompts.json` | Targeted contract questions with citations |
| `chat --report ...` | Interactive multi-turn chat about findings |
| `assess /data` | Data room quality check before running |
| `auto-config` | AI-generated deal configuration from data room scan |

## What Gets Analyzed

- **Legal** — Change of control, anti-assignment, termination, IP ownership, indemnification, liability caps
- **Finance** — Revenue cross-referencing, unit economics (CAC/LTV/NRR), cost structure, projections
- **Commercial** — Renewal mechanics, customer concentration, SLAs, pricing models, MFN clauses
- **ProductTech** — DPA analysis, security certifications, technical SLAs, migration complexity
- **Cybersecurity** — Security governance, incident history, vulnerability management, disaster recovery
- **HR** — Compensation, key talent retention, labor compliance, workforce classification
- **Tax** — Transfer pricing, NOL/tax attributes, deal structure, income tax compliance
- **Regulatory** — License transferability, antitrust, data privacy, AML/sanctions
- **ESG** — Environmental contamination, climate risk, supply chain sustainability

## Output

- **Interactive HTML report** — Go/No-Go verdict, executive narrative, severity filtering, cross-domain synthesis
- **16-sheet Excel report** — structured findings for downstream modeling
- **Per-subject JSON** — every finding with severity, citations, and cross-references

## Architecture

```
Data Room → Python Orchestrator (38 steps, 5 blocking gates)
         → 9 Specialist Agents (parallel) + Judge + Cross-Domain Analysis
         → Merge & Audit (dedup, citation verification, 31 QA checks)
         → Executive Synthesis (Go/No-Go signal)
         → HTML + Excel + JSON output
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key |
| `AWS_PROFILE` | Alt | AWS profile for Bedrock |
| `AWS_REGION` | Alt | AWS region for Bedrock |

*Either Anthropic API key or AWS Bedrock credentials required.

## Docker Compose Example

```yaml
services:
  dd-agents:
    image: zoharbabin/due-diligence-agents:latest
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - ./data_room:/data
      - ./deal-config.json:/workspace/deal-config.json
    command: run /workspace/deal-config.json
```

## Tags

- `latest` — most recent stable release
- `x.y.z` — pin a specific release (matches the PyPI version; see [Releases](https://github.com/zoharbabin/due-diligence-agents/releases))
- `x.y` — latest patch within a minor series

## Security & Privacy

- **Local execution** — documents only leave your machine as API calls to your LLM provider
- **No telemetry** — no phone-home, no usage data collection
- **Read-only** — never modifies files in your data room
- **No persistent credentials** — API keys read from environment, never stored in output

## Links

- **Documentation:** https://zoharbabin.github.io/due-diligence-agents/
- **Sample Report:** https://zoharbabin.github.io/due-diligence-agents/sample-report/
- **Source Code:** https://github.com/zoharbabin/due-diligence-agents
- **PyPI:** https://pypi.org/project/dd-agents/
- **Issues:** https://github.com/zoharbabin/due-diligence-agents/issues

## License

Apache 2.0 — free for commercial use.
