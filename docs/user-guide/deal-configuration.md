# Deal Configuration

The pipeline is driven by a `deal-config.json` file that describes the buyer, target,
deal parameters, and execution settings. A well-configured deal file ensures the
analysis focuses on the right risks, entities, and contract provisions — the
difference between a generic scan and forensic-grade analysis tuned to your specific
deal. There are three ways to create one.

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
| `--buyer-docs PATH` | Buyer business description files (10-K, annual report). Repeatable. |
| `--spa PATH` | SPA draft/redline for deal structure extraction |
| `--press-release PATH` | Acquisition press release for strategic context |
| `--buyer-docs-dir NAME` | Folder name for converted buyer files in data room (default: `_buyer`) |
| `--interactive` | Enable interactive follow-up questions for strategy refinement |
| `--output PATH` | Output path (default: `deal-config.json`) |
| `--dry-run` | Print config without writing |
| `--force` | Overwrite existing file |
| `--verbose / -v` | Debug logging |

Preview before writing:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room --dry-run
```

Deep auto-config with buyer strategy generation:

```bash
dd-agents auto-config "Acme Corp" "Target Inc" --data-room ./data_room \
  --buyer-docs ./10k-business.docx --buyer-docs ./earnings-call.docx \
  --spa ./spa-draft.pdf --press-release ./acquisition-pr.docx \
  --interactive
```

When `--buyer-docs`, `--spa`, or `--press-release` are provided, the command runs
a multi-turn analysis that produces a `buyer_strategy` section in the config. This
enables the Acquirer Intelligence Agent and buyer-specific report sections.

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
    "acquired_entities": [
      {"name": "SubCo", "acquisition_date": "2024-01-15", "deal_type": "acquisition"}
    ],
    "entity_name_variants_for_contract_matching": [
      "Target", "Target Incorporated", "Target Inc."
    ]
  },
  "entity_aliases": {
    "canonical_to_variants": {
      "Target Inc": ["Target", "Target Incorporated"]
    },
    "short_name_guard": ["TI"],
    "exclusions": ["N/A", "TBD", "Various"],
    "parent_child": {
      "Target Inc": ["Target EU GmbH", "SubCo"]
    }
  },
  "source_of_truth": {
    "customer_database": null
  },
  "key_executives": [
    {"name": "Jane Doe", "title": "CEO", "company": "Target Inc"}
  ],
  "deal": {
    "type": "acquisition",
    "focus_areas": ["change_of_control_clauses", "ip_ownership"]
  },
  "execution": {
    "execution_mode": "full",
    "staleness_threshold": 3,
    "force_full_on_config_change": true,
    "batch_concurrency": 6
  },
  "judge": {
    "enabled": true,
    "max_iteration_rounds": 2,
    "score_threshold": 70,
    "sampling_rates": {"p0": 1.0, "p1": 0.2, "p2": 0.1, "p3": 0.0},
    "ocr_completeness_check": true,
    "cross_agent_contradiction_check": true,
    "web_research_enabled": false
  },
  "extraction": {
    "ocr_backend": "auto"
  },
  "reporting": {
    "report_schema_override": null,
    "include_diff_sheet": true,
    "include_metadata_sheet": true
  },
  "agent_models": {
    "profile": "standard",
    "overrides": {},
    "budget_limit_usd": null
  },
  "data_room": {
    "path": "./data_room",
    "groups": {
      "Enterprise": {"label": "Enterprise Customers", "customers": ["Acme_Corp"]},
      "SMB": {"label": "SMB Customers", "customers": ["Beta_Inc"]}
    },
    "reference_dir": "_reference"
  },
  "forensic_dd": {
    "enabled": true,
    "domains": {
      "disabled": [],
      "custom": []
    }
  },
  "precedence": {
    "enabled": true,
    "folder_priority": {
      "Board Materials": 1,
      "Team Notes": 3
    }
  },
  "buyer_strategy": {
    "thesis": "Expand SaaS platform into healthcare vertical",
    "key_synergies": ["shared customer base", "technology integration"],
    "integration_priorities": ["API consolidation", "customer migration"],
    "risk_tolerance": "moderate",
    "focus_areas": ["revenue retention", "tech stack compatibility"],
    "budget_range": "$50M-$75M"
  }
}
```

## Key Sections

### buyer / target (required)

`buyer.name` and `target.name` are required. Both sections accept `extra` fields.

The **target** section supports rich entity resolution context:
- `subsidiaries`: list of subsidiary names
- `previous_names`: historical names with period ranges (e.g. rebrands)
- `acquired_entities`: entities previously acquired by the target (with dates in YYYY-MM-DD format)
- `entity_name_variants_for_contract_matching`: alternative names to match in contracts
- `notes`: free-text context

The **buyer** section supports:
- `ticker` / `exchange`: stock information
- `notes`: context about the buyer

### entity_aliases (optional)

Helps the tool match company names correctly across documents. Companies often appear
under different names (abbreviations, legal suffixes, trade names), and this section
tells the tool which names refer to the same entity.

- `canonical_to_variants`: maps the official company name to alternate names used in contracts (e.g. "Target Inc" → ["Target", "Target Incorporated"])
- `short_name_guard`: abbreviations that are too ambiguous to match automatically (e.g. "TI" could be many companies)
- `exclusions`: strings to always ignore during matching (e.g. "N/A", "TBD", "Various")
- `parent_child`: maps parent companies to their subsidiaries for hierarchical matching

When provided, these dramatically improve name-matching accuracy and prevent
false matches.

### source_of_truth (optional)

Authoritative data source for contract date reconciliation (step 11):

- `customer_database`: reference spreadsheet with contract dates and ARR data
  - `file`: path to the spreadsheet
  - `sheet`: sheet name (optional)
  - `header_row`: 1-based row number of column headers (default: 1)
  - `columns`: column index mapping (`customer_name`, `parent_account`, `entity`, `contract_start`, `contract_end`, `arr`)
  - `active_filter`: criteria to identify active customers (`arr_column`, `arr_condition`, `end_date_condition`)

When absent, contract date reconciliation (step 11) is skipped.

### key_executives (optional)

List of key people involved in the deal. Each entry has:
- `name`: full name
- `title`: job title
- `company`: which company they belong to (buyer or target)
- `notes`: additional context

Used by agents for organizational risk analysis and key-person dependency detection.

### deal (required)

`deal.type` accepts: `acquisition`, `merger`, `divestiture`, `investment`,
`joint_venture`, `other`.

`deal.focus_areas` is a list of analysis priorities. Common values:
`change_of_control_clauses`, `ip_ownership`, `revenue_recognition`,
`customer_concentration`, `auto_renewal_terms`, `data_privacy_compliance`,
`liability_caps`, `non_compete_agreements`.

### execution

- `execution_mode`: `full` (default) or `incremental` (reuses prior extraction)
- `staleness_threshold`: days before cached extraction is considered stale (default: 3)
- `force_full_on_config_change`: re-run everything if config changed since last run (default: true)
- `batch_concurrency`: max parallel batches per agent (1-10, default: 6)

### judge

Controls the optional Judge agent that reviews specialist findings:

- `enabled`: whether to run judge review (default: true)
- `max_iteration_rounds`: review cycles (1-5, default: 2)
- `score_threshold`: minimum quality score to pass (0-100, default: 70)
- `sampling_rates`: per-severity sampling rates for review
  - `p0`: 1.0 (review all critical findings)
  - `p1`: 0.20
  - `p2`: 0.10
  - `p3`: 0.0 (skip informational findings)
- `ocr_completeness_check`: verify OCR extraction quality (default: true)
- `cross_agent_contradiction_check`: detect conflicting findings across agents (default: true)
- `web_research_enabled`: enable web research via google-researcher-mcp for claim verification (default: false)

### extraction (optional)

- `ocr_backend`: OCR engine preference — `auto` (default), `pytesseract`, `glm_ocr`, or `none`
  - `auto`: tries pymupdf → markitdown → pytesseract → glm_ocr
  - `pytesseract`: English-only OCR (hardcoded `lang="eng"`)
  - `glm_ocr`: multilingual OCR via GLM vision-language model (100+ languages, recommended for non-English data rooms)
  - `none`: skip OCR entirely (text-only extraction)

### reporting

- `report_schema_override`: path to custom report schema JSON (default: null, uses built-in)
- `include_diff_sheet`: include incremental diff sheet in Excel report (default: true)
- `include_metadata_sheet`: include pipeline metadata sheet (default: true)

### agent_models

Controls which Claude models are used:

- `profile`: preset model tier — see table below
- `overrides`: per-agent model IDs, e.g. `{"legal": "claude-opus-4-6"}`
- `budget_limit_usd`: optional hard spending cap per run

Model assignments per profile:

| Agent Role | `economy` | `standard` | `premium` |
|-----------|-----------|------------|-----------|
| Specialists (Legal, Finance, Commercial, ProductTech) | Haiku | Sonnet | Sonnet |
| Judge | Haiku | Sonnet | Sonnet |
| Executive Synthesis | Sonnet | Sonnet | Opus |
| Red Flag Scanner | Haiku | Haiku | Sonnet |

### data_room

- `path`: path to the data room folder (required for `run` command)
- `groups`: named customer groups with label and customer list
- `reference_dir`: subfolder name for reference/cross-cutting files (e.g. corporate docs)

### forensic_dd (optional)

Controls the forensic DD analysis domains:

- `enabled`: enable/disable the entire forensic DD skill (default: true)
- `domains.disabled`: list of domain IDs to skip
- `domains.custom`: list of custom analysis domains, each with:
  - `id`: lowercase identifier (e.g. `insurance_review`)
  - `name`: display name
  - `description`: what this domain covers
  - `agent_assignment`: which agent handles it (`legal`, `finance`, `commercial`, `producttech`)
  - `expected_finding_categories`: categories this domain should produce
  - `key_terms`: terms to search for in documents
  - `weight`: analysis priority (1-3, default: 3)

### precedence (optional)

Controls how conflicting or overlapping files are ranked. When enabled (default),
the pipeline classifies folders into trust tiers, detects version chains in filenames,
and computes a composite precedence score for each file.

- `enabled`: whether to run precedence analysis (default: true)
- `folder_priority`: custom folder-name → tier mapping (1=authoritative, 2=working, 3=supplementary, 4=historical)

Built-in folder patterns are applied automatically (e.g. "executed" → tier 1, "draft" → tier 3).
Custom overrides take priority over built-in patterns.

### buyer_strategy (optional)

When present, enables the Acquirer Intelligence Agent and buyer-specific report sections:

- `thesis`: buyer's acquisition thesis / strategic rationale
- `key_synergies`: list of expected synergies
- `integration_priorities`: post-close integration priorities
- `risk_tolerance`: `conservative`, `moderate`, or `aggressive`
- `focus_areas`: buyer-specific focus areas for analysis
- `budget_range`: deal budget range context
- `notes`: additional context

Generated automatically when using `auto-config` with `--buyer-docs` or `--spa` flags.

## Next Steps

- [Running the Pipeline](running-pipeline.md) -- Execute the pipeline with your config
- [CLI Reference](cli-reference.md) -- Full option reference for all commands
