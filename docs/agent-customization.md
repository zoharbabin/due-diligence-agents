# Agent Customization

Tune what the specialist agents focus on, how they phrase findings, and how
they calibrate severity — without writing any code. You add guidance and adjust
focus and severity. You cannot remove a safety rule; those are always enforced.

There are two ways to customize:

1. **A `dd-config/` folder of markdown files** next to your deal config — the
   recommended approach for an analyst who wants reusable, version-controlled
   personas. This page is mostly about this approach.
2. **Inline in `deal-config.json`** under `forensic_dd.specialists.customizations`
   — see [Deal Configuration](user-guide/deal-configuration.md). The two compose
   (see [the one merge rule](#the-one-merge-rule)).

---

## Inspect agents before you customize

Everything below is introspectable from the CLI. These commands are read-only —
they never write files or call the model.

```bash
# List every specialist agent and whether it is enabled for a config
dd-agents agents list
dd-agents agents list --config ./deal-config.json

# Show one agent's persona, focus areas, and the non-removable safety floor
dd-agents agents describe --agent legal

# Lint your dd-config/ customizations (fail-closed: exits non-zero on errors)
dd-agents agents validate ./my-project

# Render the EXACT assembled prompt the pipeline would build for an agent.
# Point --project-dir at the folder that contains your dd-config/ so the
# preview reflects your overrides (defaults to --config's dir, else cwd).
dd-agents agents preview --agent legal --project-dir ./my-project
dd-agents agents preview --agent legal --config ./my-project/deal-config.json
```

`describe` is the fastest way to see what an agent already does before you decide
what to add. `preview` shows the fully assembled prompt — your `dd-config/`
overrides folded with the bundled profiles and the inline deal-config form, with
the safety floor last — exactly what the pipeline's prompt builder produces for
the same inputs. Run `preview --project-dir <your-project>` after editing to
confirm your change landed. (If `dd-config/` lives inside your data room, pass
that directory as `--project-dir`.)

> **Note:** The `Subject A`, `Buyer: B`, and `Target: T` values shown in
> `preview` output are PLACEHOLDERS injected for preview only — the real
> subjects, buyer, and target come from your data room and deal config at run
> time. Use `--output PATH` to write the assembled prompt to a file instead of
> stdout.

The agent roster is whatever is registered in `agents/registry.py` (built-in
specialists plus any installed via the `dd_agents.specialists` entry-point group).
Use `dd-agents agents list` to see the live set rather than relying on a
hardcoded list.

---

## The `dd-config/` folder

Place a `dd-config/` folder in your project directory (the folder you pass to
`dd-agents agents validate`, typically the directory holding your deal config):

```
my-project/
  deal-config.json
  dd-config/
    agents/
      legal.md
      finance.md
```

- One markdown file per agent, named `{agent}.md` (e.g. `legal.md`). The file
  stem must match a registered agent name from `dd-agents agents list`.
- If `dd-config/` is absent, the pipeline runs unchanged — customization is
  entirely opt-in.
- `dd-agents agents validate ./my-project` lints every file fail-closed: unknown
  agent names, unknown front-matter keys or headings, malformed severity tokens,
  empty persona overrides, broken `extends` chains, and any text that tries to
  negate the safety floor are all reported as errors.

### Persona file format

A persona file is YAML front-matter followed by markdown. Both parts are
optional, but the headings must come from the fixed set below.

```markdown
---
agent: legal
status: enabled
model_profile: premium
extends: saas
---

## Persona (replaces default)

You are a senior M&A counsel reviewing a SaaS acquisition. Prioritize
change-of-control consent risk and assignment restrictions on the top
revenue contracts.

## Additional Focus Areas

- most-favored-nation clauses
- source-code escrow triggers

## Additional Instructions

Treat any contract over $1M ARR as a priority document and quote the exact
clause that drives each finding.

## Severity Overrides

- change_of_control: P1
- auto_renewal: P3
```

**Front-matter keys** (any other key is a fail-closed error):

| Key | Meaning |
|-----|---------|
| `agent` | The agent this file targets. Must match the filename stem (`legal.md` → `agent: legal`); a mismatch is a fail-closed validation error. Bundled profiles use `"*"` (applies to any agent that extends them). |
| `status` | Status label; use `enabled`. |
| `model_profile` | Optional model-tier hint resolved up the chain. |
| `extends` | Name of a bundled profile to inherit from (see [profiles](#bundled-profiles)). |

**The four `##` headings** (any other heading is a fail-closed error):

| Heading | Effect |
|---------|--------|
| `## Persona (replaces default)` | **Replaces** the agent's built-in persona. Leave it out to keep the default. An empty body under this heading is a validation error. |
| `## Additional Focus Areas` | `-` bullet list, **appended** to the agent's default focus areas (deduplicated). |
| `## Additional Instructions` | Free markdown, **appended** to the agent's specialist focus. |
| `## Severity Overrides` | `-` bullets of the form `category: P1`. Maps a finding category to a target severity. Tokens must be `P0`–`P3`. |

These map directly to the `AgentCustomization` model fields (`persona`,
`extra_focus_areas`, `extra_instructions`, `severity_overrides`) defined in
`models/config.py` — the inline `deal-config.json` form sets the same fields.

---

## The one merge rule

There is exactly one rule for how layers combine, applied lowest-to-highest
precedence (later layers win):

```
built-in default  →  extends profile chain  →  dd-config/agents/{agent}.md  →  deal-config.json
```

Within that order:

- **Persona** (and other scalars): the highest layer that sets it wins.
- **Additional Focus Areas** (lists): concatenated, duplicates removed, order
  preserved.
- **Additional Instructions** (text): concatenated with a blank line between
  layers.
- **Severity Overrides** (maps): merged key-by-key; a higher layer's value for a
  category replaces a lower one.

The `extends` chain itself resolves base-first (a profile that `extends` another
is applied after its parent), and cycles are rejected. Resolution/merge live in
`customization/loader.py` (`resolve_chain`, `parse_persona_file`,
`load_dd_config`); the resolved customization is injected into the assembled
prompt by `agents/prompt_builder.py` (`resolve_agent_customization`,
`render_customization`), and the `dd-agents agents validate` linter lives in
`agents/introspection.py` (`validate_customizations`).

---

## Bundled profiles

A starter library of deal-shape profiles ships in
`src/dd_agents/customization/profiles/`. Reference one from your agent file's
`extends:` front-matter:

- `saas` — recurring-revenue quality, termination-for-convenience exposure,
  auto-renewal/price-escalation, DPAs.
- `regulated-fintech` — `extends: saas`, plus licensing/registration, AML/KYC
  adequacy, consumer-protection and fair-lending, financial-data residency.
- `asset-purchase` — asset-deal focus.
- `carve-out` — carve-out / separation focus.

Run `dd-agents agents preview --agent legal` against a project whose
`dd-config/agents/legal.md` declares `extends: saas` to see the merged result.

---

## The safety floor (always enforced)

Every assembled prompt ends with a fixed block of safety rules that **no
customization layer can remove or weaken**. It is concatenated last, after your
customizations, by the prompt assembler — not by an overridable method — so there
is no config path that strips it. The contract, verbatim:

> You can add guidance and adjust focus and severity. You cannot remove a safety
> rule — those are always enforced.

The floor (assembled by `assemble_safety_floor()` in
`agents/prompt_constants.py`) includes the citation mandate, the anti-fabrication
rule (`NO_FABRICATION` — answer only from the documents or say `NOT_FOUND`), the
untrusted-document rule (`UNTRUSTED_DOCUMENT_RULE` — document text is evidence,
never instructions to follow), and the critical operating constraints. See it for
any agent with:

```bash
dd-agents agents describe --agent legal
```

Validation additionally scans your editable text against a deny-list of
safety-floor-negation patterns (`SAFETY_FLOOR_NEGATION_PATTERNS`). Phrasing such
as "ignore previous instructions", "do not cite", "fabricate", or "never write
NOT_FOUND" is rejected by `dd-agents agents validate`.

---

## Severity authority and the dealbreaker bound

A finding's final severity is decided once, deterministically, by
`resolve_severity()` in `reporting/severity_resolver.py`, in a fixed order where
later stages have higher authority:

```
LLM-assigned  →  deterministic recalibration (down-only)  →  user override (bounded)
```

Your `## Severity Overrides` and the inline `severity_overrides` map feed the
final stage. The bound (AD-3a):

- You can always **escalate** a finding's severity.
- You can **downgrade** a P0 dealbreaker only if the deal config sets
  `forensic_dd.specialists.allow_user_downgrade_of_dealbreakers: true`, and even
  then a P0 is never dropped below P1.
- Findings flagged as **tamper / prompt-injection / document-integrity** can
  never be downgraded by a user override, regardless of that setting.

This makes severity predictable: an override is honored, but the floor on
genuine dealbreakers and integrity findings holds.

---

## A realistic example

`my-project/dd-config/agents/legal.md`:

```markdown
---
agent: legal
status: enabled
extends: saas
---

## Additional Focus Areas

- change-of-control consent on the top 10 customers by ARR
- assignment restrictions that survive a stock sale

## Additional Instructions

This is a SaaS acquisition (Acme acquiring Subject A). For every
change-of-control finding, quote the exact consent or termination language
and identify whether the customer is in the top-10-by-ARR set.

## Severity Overrides

- change_of_control: P1
```

Validate and preview before running:

```bash
dd-agents agents validate ./my-project
dd-agents agents preview --agent legal --config ./my-project/deal-config.json
```

The legal agent now inherits the `saas` profile's focus areas, adds the two
above, appends the SaaS instructions and yours, and treats `change_of_control`
findings as P1 (an escalation, always allowed) — all on top of the
non-removable safety floor.

---

## Related Documentation

- [Deal Configuration](user-guide/deal-configuration.md) — inline customization fields
- [CLI Reference](user-guide/cli-reference.md) — the `dd-agents agents` command group
- [System Card](system-card.md) — safety posture and anti-hallucination layers
