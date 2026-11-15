# Sanctions and Watchlist Screening

Screen the target, its executives and the data room entities against official sanctions lists and your own watchlists. List matching runs on your machine. Off by default.

Two optional parts go further. Both are off by default: [officer discovery](#officer-discovery) reads the data room, and [public source research](#public-source-research) sends names to a search server you configure.

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
| `discover_officers` | `false` | An agent reads the extracted data room text and proposes officers, directors and owners to screen. Needs `people`. No web access |
| `profile_research` | `false` | An agent searches public sources for the screened names. Needs `external_verification.enabled`. Sends names to the configured server |
| `research_max_targets` | `25` | Most names sent to research. The target and its executives come first |

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

## Officer Discovery

Set `discover_officers: true` (with `people: true`). An agent reads the extracted text and proposes people named as officers, directors or owners. It has no web tools.

- Each proposal needs the source file and a quote. The step keeps it only if the quote is found in that file, the name is inside the quote, and the path stays inside the text folder. Everything else is dropped and counted.
- At most 50 names are kept. Duplicates collapse.
- Kept names are screened against the lists like `key_executives`. Their role reads "officer named in the data room" plus the title.
- The quote and source file stay in `screening/officer_candidates.json` in the run folder. They are not sent anywhere.
- Not covered: officers named only in documents the agent did not open, or in scanned files with no extracted text.

## Public Source Research

Set `profile_research: true` and enable [`external_verification`](deal-configuration.md#external_verification-optional). An agent with web search tools looks up each name (litigation, enforcement, sanctions, regulatory action, adverse media). It cannot read the data room.

- **What leaves your machine:** the name, whether it is a person or company, and its role. No document text, file names, quotes or findings. The names go to the server in `external_verification.server`, and from there to the services behind it.
- Which names: the target and its executives first, then the rest, up to `research_max_targets`.
- A `found` record needs a source URL, a summary and a quote from the source, and an access date. Records without them are dropped and counted.
- Each lead becomes a finding in the same per-name file as the list matches. Confidence is `low`. The citation is `web_research` with the access date. Severity starts from `PROFILE_LEAD_SEVERITY` (`src/dd_agents/agents/severity_thresholds.py`) and the merge step decides the final value. At most 5 leads per name.
- A lead may concern someone else with the same name. Open the source, confirm the party, then decide with counsel.
- If `profile_research` is on and `external_verification.enabled` is off, nothing is searched. The report says so as a gap.
- A tool that fails or times out, an invalid record, or a name with no record counts as not researched. The report lists those names under "Public source research is incomplete".

## Outputs

| File | Content |
|------|---------|
| `findings/external_screening/{subject}.json` | One finding per screened name with a possible match. Hits on the target and its executives are in `_target_screening.json` |
| `screening/coverage.json` | Lists used, their status and date, gaps, counts. Written on every run, also when nothing matched. Holds `officer_discovery` and `profile_research` blocks when those ran |
| `screening/officer_candidates.json`, `screening/profile_leads.json` | Raw agent output, before checking. Only with the matching option on |

The HTML report gets a "Sanctions and Watchlist Screening" section when the step ran. It shows the lists used, the possible matches, the public source leads (when research ran), discovery and research status, and a fixed statement of limits. The section is omitted when screening is off.

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
- Politically exposed persons and beneficial ownership registers. Public source research may surface adverse media, but it does not search these.
- Sanctions lists through public source research. It is a web search, not a list lookup. Use the official lists above.
- Any list not named in the coverage table.

The same list appears in the report and in `coverage.json`.

## Data Statement

| Question | Answer |
|----------|--------|
| Where does list matching run? | On your machine. No LLM call, no network call |
| When is the network used? | `dd-agents screening update` (official list sites). Public source research, only if you turn it on |
| Are names sent anywhere? | Not by default. With `profile_research` on: names, kind and role go to your `external_verification` server and the services behind it |
| Does officer discovery send anything out? | The agent reads extracted text through the normal LLM provider, like every pipeline agent. It has no web tools |
| Do logs contain names? | No. They carry counts only |

A possible match or lead is a prompt for human review. Absence of a match is not clearance. Decide with counsel.
