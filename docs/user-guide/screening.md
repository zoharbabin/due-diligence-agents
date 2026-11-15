# Sanctions and Watchlist Screening

Screen the target, its executives and the data room entities against official sanctions lists and your own watchlists. Matching runs on your machine. Off by default.

## Quick Start

```bash
dd-agents screening update          # download the official lists (needs network, once a week or so)
dd-agents screening status          # which lists are stored, and how old
dd-agents screening check "Fabricated Holdings Limited"   # try one name
dd-agents screening validate --project-dir path/to/project   # check your own lists
```

Turn the pipeline step on in `deal-config.json`:

```json
"screening": {
  "enabled": true
}
```

Then run the pipeline as usual. The step is pipeline step 26. Full option list: [CLI Reference](cli-reference.md#screening).

## Deal Config Block

| Field | Default | Meaning |
|-------|---------|---------|
| `enabled` | `false` | Run the screening step |
| `people` | `true` | Screen `key_executives` |
| `companies` | `true` | Screen the target, its subsidiaries, its previous names and every data room entity |
| `sources` | all | Official list ids to use, for example `["ofac_sdn", "uk"]`. Unknown ids fail config validation |

The block is part of the run provenance hash. If you change it, or edit a file in `dd-config/screening/`, a resume from an earlier checkpoint is rejected. Start the run again.

## What Is Screened

| Name | Screened as |
|------|-------------|
| `target.name` | Company |
| `target.subsidiaries` | Company |
| `target.previous_names` | Company |
| `key_executives` | Person |
| Every data room entity (subject) | Company |

Names are de-duplicated after normalization. A name that is both an entity and the target is reported once, under the entity.

## How Matching Works

Matching is local, deterministic and has no LLM call. Case, accents, punctuation and word order are ignored. Company names also lose legal suffixes such as Ltd or Inc.

| Band | Meaning | Severity |
|------|---------|----------|
| `exact` | Same words after normalization | P0 |
| `strong` | Near-identical spelling, same number of words | P1 |
| `possible` | Close spelling, or one name contains the other with at least two shared words | P2 |

- Birth years and countries from the list entry are noted as "agrees" or "differs". A birth year that differs lowers the band one step.
- Confidence is `medium` only for an exact match with agreeing detail. Otherwise it is `low`. It is never `high`.
- Severity thresholds live in `src/dd_agents/agents/severity_thresholds.py`. The merge step stays the single severity authority.
- Every finding says "possible match, needs review". A name match does not show that the party is the listed party.

## Outputs

| File | Content |
|------|---------|
| `findings/external_screening/{subject}.json` | One finding per screened name with a possible match. Hits on the target and its executives are in `_target_screening.json` |
| `screening/coverage.json` | Lists used, their status and date, gaps, counts. Written on every run, also when nothing matched |

The HTML report gets a "Sanctions and Watchlist Screening" section when the step ran. It shows the lists used, the possible matches and a fixed statement of limits. The section is omitted when screening is off.

### Gaps

A list can be `screened`, `stale` (older than the age limit, still searched), `missing` or `failed`. Any status other than `screened`, and any broken file in `dd-config/screening/`, is listed as a gap. The report then shows "Screening is incomplete". No hits with gaps is never shown as clean.

The age limit is `LIST_MAX_AGE_DAYS` in `src/dd_agents/screening/store.py`.

## Official Lists

| Id | List |
|----|------|
| `ofac_sdn` | OFAC SDN (US Treasury) |
| `uk` | UK Sanctions List (FCDO) |
| `eu` | EU consolidated financial sanctions list |

Not included:

- **UN Security Council list, as its own list.** Its terms forbid derived indexes. The UK and EU lists carry the UN designations.
- **US SAM.gov and HHS-OIG exclusions.** Add them yourself as a CSV (see below).

Downloaded lists go to `DD_SCREENING_DIR` (default `~/.dd-agents/screening`).

## Add Your Own Lists

Put files in `dd-config/screening/` inside your project folder. One folder, one format: YAML front matter plus markdown. Run `dd-agents screening validate` after every edit.

Example `dd-config/screening/deal-watchlist.md`:

```markdown
---
name: deal-watchlist
kind: watchlist
description: Parties the deal team wants flagged
source_url: https://example.com/internal-note
entries_file: deal-watchlist.csv
---
Notes for the team. The body is kept but not matched.
```

Example `dd-config/screening/deal-watchlist.csv`:

```csv
name,type,aliases,birth_years,countries,programs,reason,url,listed_on
Zelda Quintero Fakename,person,Z. Quintero;Zelda Q. Fakename,1971;1972,XX,Internal review,Prior dispute with a customer,https://example.com/case-1,2025-03-01
Fabricated Holdings Limited,organization,Fabricated Holdings,,XX;YY,Internal review,Debarred by a customer,,2024-11-20
```

You can also put the entries inline in the front matter:

```markdown
---
name: inline-list
kind: watchlist
entries:
  - name: Fabricated Holdings Limited
    type: organization
    countries: [XX]
    reason: Debarred by a customer
---
```

| Field | Rule |
|-------|------|
| `name` | Required. Letters, digits, `_` and `-`. Up to 64 characters. Unique per folder |
| `kind` | `watchlist` (entries are matched) or `reference` (a note, no entries, not matched) |
| `description`, `source_url` | Optional text |
| `entries` or `entries_file` | One of them, not both. The CSV must sit inside `dd-config/screening/` |
| Entry `type` | `person`, `organization` or `unknown` (default) |
| CSV list columns | `aliases`, `birth_years`, `countries`, `programs`. Separate values with `;` |

Limits: 2 MB per file, 50,000 entries per file and 50,000 in total. A file that breaks a rule is skipped. It becomes a coverage gap, so the report shows the problem.

Reference notes are listed in `coverage.json`. This step does not read or match them.

## Not Screened

- UN Security Council list as its own list.
- SAM.gov and HHS-OIG, unless you add them as a user list.
- Politically exposed persons, adverse media and beneficial ownership.
- Any list not named in the coverage table.

The same list appears in the report and in `coverage.json`.

## Data Statement

| Question | Answer |
|----------|--------|
| Where does matching run? | On your machine. No LLM call, no network call |
| When is the network used? | Only by `dd-agents screening update`, to download lists from the official sites |
| Are names sent anywhere? | No |
| Do logs contain names? | No. They carry counts only |

A possible match is a prompt for human review. Absence of a match is not clearance. Decide with counsel.
