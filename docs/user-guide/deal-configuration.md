# Deal Configuration

The pipeline is driven by a `deal-config.json` file that describes the buyer, target,
deal parameters, and execution settings. There are three ways to create one.

## Auto-Generation with AI

The `auto-config` command scans your data room with Claude and produces a complete config:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room
```

Options:

| Flag | Description |
|------|-------------|
| `BUYER` | Acquiring company name (positional, required) |
| `TARGET` | Company being acquired (positional, required) |
| `--data-room PATH` | Path to data room folder (required) |
| `--deal-type TYPE` | Override inferred deal type |
| `--output PATH` | Output path (default: `deal-config.json`) |
| `--dry-run` | Print config without writing |
| `--force` | Overwrite existing file |
| `--verbose / -v` | Debug logging |

Preview before writing:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room --dry-run
```

## Interactive Generation

The `init` command walks you through the setup interactively:

```bash
dd-agents init --data-room ./data_room
```

Or run non-interactively for scripted workflows:

```bash
dd-agents init --non-interactive --data-room ./data_room \
  --buyer "Acme Corp" --target "Target Inc" \
  --deal-type acquisition \
  --focus-areas "ip_ownership,revenue_recognition"
```

## Config Validation

Validate an existing config without running the pipeline:

```bash
dd-agents validate deal-config.json
```

This checks all required fields, value constraints, and version compatibility.

## Config Structure

```json
{
  "config_version": "1.0.0",
  "buyer": {
    "name": "Acme Corp",
    "ticker": "",
    "exchange": "",
    "notes": ""
  },
  "target": {
    "name": "Target Inc",
    "subsidiaries": ["Target EU GmbH"],
    "previous_names": [{"name": "OldName Co", "period": "2018-2021"}],
    "acquired_entities": [],
    "entity_name_variants_for_contract_matching": [
      "Target", "Target Incorporated", "Target Inc."
    ]
  },
  "deal": {
    "type": "acquisition",
    "focus_areas": [
      "change_of_control_clauses",
      "ip_ownership",
      "revenue_recognition",
      "customer_concentration"
    ]
  },
  "execution": {
    "execution_mode": "full",
    "staleness_threshold": 3,
    "batch_concurrency": 6
  },
  "judge": {
    "enabled": true,
    "max_iteration_rounds": 2,
    "score_threshold": 70
  },
  "reporting": {
    "include_diff_sheet": true,
    "include_metadata_sheet": true
  },
  "agent_models": {
    "profile": "standard",
    "overrides": {},
    "budget_limit_usd": null
  },
  "data_room": {
    "path": "./data_room"
  }
}
```

## Key Sections

### buyer / target

`buyer.name` and `target.name` are required. The target section supports
`subsidiaries`, `previous_names`, and `entity_name_variants_for_contract_matching`
to improve entity resolution accuracy across contracts.

### deal

`deal.type` accepts: `acquisition`, `merger`, `divestiture`, `investment`,
`joint_venture`, `other`.

`deal.focus_areas` is a list of analysis priorities. Common values:
`change_of_control_clauses`, `ip_ownership`, `revenue_recognition`,
`customer_concentration`, `auto_renewal_terms`, `data_privacy_compliance`,
`liability_caps`, `non_compete_agreements`.

### execution

- `execution_mode`: `full` (default) or `incremental` (reuses prior extraction)
- `staleness_threshold`: days before cached extraction is considered stale (default: 3)
- `batch_concurrency`: max parallel batches per agent (1-10, default: 6)

### judge

Controls the optional Judge agent that reviews specialist findings:

- `enabled`: whether to run judge review (default: true)
- `max_iteration_rounds`: review cycles (1-5, default: 2)
- `score_threshold`: minimum quality score to pass (0-100, default: 70)

### agent_models

Controls which Claude models are used:

- `profile`: `economy` (Haiku), `standard` (Sonnet), `premium` (Opus)
- `overrides`: per-agent model IDs, e.g. `{"legal": "claude-opus-4-6"}`
- `budget_limit_usd`: optional hard spending cap per run

### buyer_strategy (optional)

When present, enables buyer-specific analysis sections in the report:

```json
"buyer_strategy": {
  "thesis": "Expand SaaS platform into healthcare vertical",
  "key_synergies": ["shared customer base", "technology integration"],
  "risk_tolerance": "moderate"
}
```

## Next Steps

- [Running the Pipeline](running-pipeline.md) -- Execute the pipeline with your config
- [CLI Reference](cli-reference.md) -- Full option reference for all commands
