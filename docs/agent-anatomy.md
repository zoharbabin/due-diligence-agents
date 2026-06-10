# How the Agents Work — A Reviewer's Tour

**Who this page is for:** an M&A professional — deal lead, lawyer, diligence
manager — who wants to *audit* what this tool actually does before trusting it
on a live deal. You will not write or read any code. Everything that decides how
an agent behaves is plain-English text, and this page shows you where it lives,
how to read it, and how the pieces fit together.

Think of each agent as a **specialist you've hired and briefed**. This page is
the filing cabinet where every briefing packet is kept. You can open any of
them, read exactly what that specialist was told to look for, and satisfy
yourself that the instructions are sound — the same way you'd review an
associate's scope memo before sending them into a data room.

> **The one rule that matters most:** you (or anyone customizing the tool) can
> *add* guidance, sharpen focus, and adjust how findings are graded. Nobody —
> no setting, no customization, no edited file — can switch off the safety
> rules that prevent the agents from inventing facts or citations. Those are
> bolted on in code, last, every time. The ["Safety floor"](#the-safety-floor-what-can-never-be-switched-off)
> section explains how that guarantee holds.

---

## The big idea: the agents' brains are readable

Until recently, the *instructions* that drive each agent lived buried inside
program code — readable only by an engineer. As of the editable-prompt release,
all of that instruction text was lifted out into ordinary
[Markdown](https://www.markdownguide.org/getting-started/) files (plain text
with light formatting — the same kind of file a README is). They sit together
in one folder:

```
src/dd_agents/agents/prompts/
├── specialists/      ← the 9 domain experts (Legal, Finance, …)
├── synthesis/        ← the agents that review, score, and summarize
├── search/templates/ ← column sets for the standalone contract-search tool
└── auto_config/      ← prompts that read a data room and draft a deal config
```

Every file in that tree is a "prompt" — the briefing you'd give a human expert,
written as instructions to the AI. Because they're plain text, you can read them
on GitHub, diff them between versions, and (if you choose) fork and override them
per deal. This page walks the whole tree.

A few promises the system keeps about these files, so you can trust what you
read *is* what runs:

- **What you read is what the agent gets.** The assembled briefing is built from
  these files plus the safety floor — there is no hidden second copy of the
  instructions. You can print the *exact* final briefing with one command (see
  ["Audit it yourself"](#audit-it-yourself)).
- **The numbers aren't scattered.** Wherever a file mentions a threshold like "a
  change-of-control clause covering more than X% of revenue," it uses a
  *placeholder*, not a hand-typed number. All the actual numbers live in one
  place (see ["The numbers"](#the-numbers-severity-thresholds)), so they can
  never silently disagree between files.
- **Customizations stack on top, never underneath.** When you tailor an agent
  for a deal, your guidance is layered *on top* of these built-in files, and the
  safety floor is layered on top of *everything*. See
  [Agent Customization](agent-customization.md) for that layer.

---

## How a finished briefing is assembled

When the pipeline runs a specialist, it doesn't just hand over one file. It
assembles a complete briefing in a deliberate order. You don't need to memorize
this — the point is simply that it's **layered and predictable**, and the
non-negotiable safety rules always come last:

1. **Role & deal context** — who this specialist is, plus the buyer, target, and
   deal type for *this* engagement.
2. **The subject list** — every entity and document the agent must work through.
3. **File-access and reference instructions** — how to read the data room.
4. **Specialist focus** — the domain playbook, read from that agent's
   `specialists/*.md` file. *(This is the heart of the briefing.)*
5. **Severity calibration** — how to grade what it finds (P0 deal-stopper down to
   P3 monitor).
6. **Output format** — the structured shape every finding must take, including a
   mandatory verbatim quote from the source document.
7. **Your customizations** — any per-deal guidance you've added, layered on here.
8. **The safety floor** — the non-removable rules, appended *dead last* so
   nothing above can weaken them.

The order is intentional: the rules the agent must follow most strictly are the
ones it reads most recently, right before it starts work.

---

## The 9 specialists

These are the domain experts. Each one reads **every** entity in the data room
through its own lens and writes up findings with citations. Each has its own file
under `prompts/specialists/`, structured into three readable sections: **Role**
(its mandate in one paragraph), **Specialist Focus** (the playbook and grading
rules), and **Domain Guidance** (detailed "what to look for, what the clause
usually says, what to do if it's missing" notes).

| Specialist | Covers | A sample of what it hunts for |
|---|---|---|
| **Legal** ([`legal.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/legal.md)) | Governance, risk clauses, entity validation | Change-of-control clauses (sorted into 5 subtypes: notification-only, consent-required, termination-right, auto-termination, competitor-only); anti-assignment restrictions; termination for cause vs. for convenience; liability caps and their carve-outs; exclusivity; data-processing agreements |
| **Finance** ([`finance.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/finance.md)) | Pricing, revenue quality, financial reconciliation | Contract ARR vs. the revenue cube (mismatches over a threshold); discounts vs. the pricing guidelines; one-time fees miscounted as recurring; minimum-volume shortfalls and penalties; unit economics (CAC, LTV, net/gross revenue retention) |
| **Commercial** ([`commercial.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/commercial.md)) | Renewal terms, SLAs, customer/churn risk | Most-favored-nation pricing parity; auto-renewal vs. manual renewal mechanics; termination-for-convenience revenue at risk; customer concentration; pricing-model volatility; revenue-retention decomposition |
| **Product & Tech** ([`producttech.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/producttech.md)) | Technical risk, data-protection terms, SLA feasibility | DPA adequacy and subprocessor lists; SOC 2 / ISO 27001 scope and exceptions; encryption standards; uptime/response SLA commitments; data-residency restrictions; end-of-life tech and migration complexity |
| **Cybersecurity** ([`cybersecurity.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/cybersecurity.md)) | Security posture, breach history, certifications | Disclosed breaches and notification timelines; MFA/least-privilege access controls; encryption and key management; incident-response readiness; SOC 2 / ISO 27001 / PCI-DSS validity; third-party vendor security |
| **HR / People** ([`hr.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/hr.md)) | Workforce, compensation, labor compliance | Unfunded pension/benefit liabilities; executive comp, golden parachutes, change-of-control acceleration; non-compete enforceability and retention risk; succession gaps; contractor misclassification; WARN Act and union/CBA exposure |
| **Tax** ([`tax.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/tax.md)) | Income tax, transfer pricing, attributes, controversy | Net operating losses and credits, with Section 382/383 ownership-change limits; transfer-pricing documentation; sales/use-tax nexus (incl. economic-nexus / *Wayfair*); permanent-establishment risk; active audits and disputes; VAT/GST compliance |
| **Regulatory** ([`regulatory.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/regulatory.md)) | Licenses, antitrust, sector compliance | License/permit transferability on change of control; HSR antitrust filing and concentration; sector frameworks (HIPAA, GLBA, FDA, SEC, FINRA, AML, OFAC); active investigations and consent decrees; export-control and sanctions exposure |
| **ESG** ([`esg.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/specialists/esg.md)) | Environmental, climate, ESG governance | Contamination and Phase I/II site assessments; Superfund/CERCLA exposure and allocations; PFAS/PCB/asbestos status; carbon profile and pricing exposure; mandatory ESG-disclosure gaps (CSRD, SEC); board-level ESG governance |

> The "sample of what it hunts for" column is illustrative — open any
> `specialists/*.md` file for the full, current playbook. That file is the
> source of truth; this table just orients you.

If a specialist looks for something but the document is silent, it's instructed
to record a **gap** ("Not Found") rather than guess — a deliberate, auditable
"we looked and it wasn't there."

---

## The review-and-summarize agents

Beyond the domain specialists, a second group of agents doesn't dig through the
data room — it works on what the specialists *produced*: reviewing, scoring,
re-checking, and writing it up. Their prompts live under `prompts/synthesis/`.

| Agent | What it does |
|---|---|
| **Red Flag Scanner** ([`red_flag_scanner.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/synthesis/red_flag_scanner.md)) | A fast first pass over the highest-signal documents (executive summaries, financial highlights, legal-matter lists, board minutes) to surface obvious deal-killers *before* the full run. Produces a stoplight signal (green / yellow / red). |
| **Judge** ([`judge.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/synthesis/judge.md)) | The auditor of the specialists. It samples findings by risk, verifies that quoted citations actually appear in the cited documents, checks financial arithmetic, and looks for inconsistencies across specialists. |
| **Executive Synthesis** ([`executive_synthesis.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/synthesis/executive_synthesis.md)) | The senior-partner final review. It re-weighs severity with professional judgment and issues an overall recommendation (most deals land at "Conditional Go"; a "No-Go" is reserved for exceptional cases). |
| **Acquirer Intelligence** ([`acquirer_intelligence.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/synthesis/acquirer_intelligence.md)) | Re-reads the findings through *this buyer's* strategic lens — does each issue help or hurt the specific acquisition thesis? |
| **Narrative Generation** ([`narrative_generation.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/synthesis/narrative_generation.md)) | Turns structured findings into plain-English narrative for the deal team — answering "what does this actually mean for *this* deal?" while tying every statement back to evidence. |

**A note on the Red Flag Scanner's category list.** The scanner's prompt file
contains a marker, `<!-- CATEGORIES -->`, where the program inserts the list of
red-flag categories it scans for (active litigation, IP-ownership gaps,
undisclosed contracts, key-person dependency, financial restatements, regulatory
violations, customer concentration, debt covenants). The categories are kept in
code as a single source of truth and injected at that marker — so the list can't
drift out of sync with the rest of the system. If you edit that file and remove
or duplicate the marker, the tool refuses to run rather than guess (a
"fail-closed" safeguard).

---

## The contract-search templates

Separate from the full diligence pipeline, the tool offers a focused
**contract-search** mode (handy for a legal team that just wants a structured
spreadsheet across many contracts — see the [Search Guide](search-guide.md)).
Each "template" is a set of spreadsheet **columns**, and each column is itself a
mini-instruction telling the AI what to extract per contract. They live under
`prompts/search/templates/`.

| Template file | Spreadsheet it builds | Columns it fills per contract |
|---|---|---|
| `change_of_control.md` | Change of Control Analysis | Consent Required; Consent Clause Summary; Notice Required; Notice Clause Summary; Termination for Convenience; TfC Summary |
| `confidentiality.md` | Confidentiality & NDA Analysis | Confidentiality Provision; Confidentiality Term; Exceptions; Surviving Obligations |
| `data_privacy.md` | Data Privacy & Protection Analysis | DPA Present; Regulatory Framework; Data Transfer Mechanisms; Breach Notification |
| `exclusivity_and_non_compete.md` | Exclusivity & Non-Compete Analysis | Exclusivity Provision; Non-Compete Clause; Preferred Vendor Status |
| `ip_ownership.md` | IP & Technology License Analysis | IP Ownership; License Scope; Source Code Access; Assignment of IP |
| `liability_and_indemnification.md` | Liability & Indemnification Analysis | Liability Cap; Uncapped Liabilities; Indemnification Obligations |
| `pricing.md` | Pricing & Fee Structure Analysis | Pricing Model; Discount or Concession; Price Escalation; MFN Clause |
| `renewal_and_expiry.md` | Renewal & Contract Expiry Analysis | Contract Term; Auto-Renewal; Early Termination |
| `sla_and_performance.md` | SLA & Performance Obligations | SLA Commitments; SLA Remedies; Performance Benchmarks |
| `termination_for_convenience.md` | Termination for Convenience Analysis | TfC Right Exists; TfC Details; Mutual or One-Sided |

Each file's header (its "front-matter") carries the template's `id`, display
`name`, and one-line `description`; the columns are the `### Column Name` headings
inside. To read or fork the exact wording behind any column, open the file.

---

## The data-room reading prompts (auto-config)

When you point the tool at a fresh data room and ask it to draft a deal-config
for you (`dd-agents auto-config`), three more prompts do that reading. They live
under `prompts/auto_config/`.

| Prompt file | What it produces |
|---|---|
| [`entity_resolution.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/auto_config/entity_resolution.md) | Reads the data-room structure to identify the official legal entities, subsidiaries, "doing-business-as" names, prior/rebranded names, and acquired entities — and the name variants needed to match them across contracts. It also infers the deal type. |
| [`buyer_strategy.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/auto_config/buyer_strategy.md) | Reads buyer-supplied context into a structured acquisition strategy: the thesis, expected synergies, integration priorities, and risk tolerance — so the specialists can weigh findings against what *this* buyer cares about. |
| [`spa_extraction.md`](https://github.com/zoharbabin/due-diligence-agents/blob/main/src/dd_agents/agents/prompts/auto_config/spa_extraction.md) | Pulls structured deal terms out of a Share/Asset Purchase Agreement: purchase price and payment waterfall, escrow/holdback periods, restricted (non-compete) periods, closing conditions, and named knowledge-holders. |

These are *drafting aids* — they propose a starting config for you to review and
edit, not a final answer.

---

## The safety floor — what can never be switched off

This is the part most worth a reviewer's attention. Every briefing, for every
agent, ends with a fixed block of **safety rules that no file and no
customization can remove or weaken**. They are not stored in the editable
Markdown — they're added by the program itself, *after* everything else,
including any per-deal customization. The customization layer can only append
text *before* this block, so the block always has the final word.

The floor enforces, in plain terms:

- **No making things up.** Answer only from the provided documents. If the
  evidence isn't there, say so ("Not Found") — never speculate, interpolate, or
  invent a value, name, number, or citation.
- **Every finding needs a real quote.** Each finding must carry an `exact_quote`
  copied verbatim from a real document the agent actually read. A finding with no
  citation is automatically downgraded — so an uncited claim can't masquerade as
  a serious one.
- **Documents are evidence, not instructions.** If text *inside* a data-room
  document tries to give the agent orders ("ignore your instructions," "mark
  everything low-risk," "don't report X"), the agent treats that as a possible
  tampering finding and reports it — it does **not** obey it. (This defends
  against a planted document trying to suppress its own red flags.)
- **One agent, no shortcuts.** The agent works the documents itself,
  sequentially, and returns findings in a single structured format.

There's a second guardrail behind this: when you customize an agent, the tool
scans your text for attempts to negate the floor (phrasings like "ignore the
rules," "never report…," "mark everything P3," or "fabricate") and **refuses the
customization** if it finds one. You can see and stress-test all of this
yourself with the commands in the next section.

---

## The numbers (severity thresholds)

You'll notice the specialist files say things like "escalate if the clause covers
more than a threshold percentage of revenue" rather than printing a number. That
isn't vagueness — the actual numbers are kept in **one** place so they can never
disagree between files, and the files reference them by name. The named
thresholds are:

| Placeholder you'll see in the files | What it controls |
|---|---|
| `{TFC_REVENUE_PCT}` / `{TFC_NOTICE_DAYS}` | When a termination-for-convenience clause escalates from a valuation concern to a higher severity |
| `{COC_REVENUE_PCT}` | Revenue exposure at which a consent-required change-of-control clause escalates |
| `{COC_AUTOTERM_REVENUE_PCT}` | Revenue exposure at which an *auto-terminating* change-of-control clause is most severe |
| `{ARR_MISMATCH_P1_PCT}` / `{ARR_MISMATCH_P2_PCT}` | The contract-vs-records ARR mismatch tiers |

When the briefing is built, each placeholder is swapped for its real value. If
someone fat-fingers a placeholder name, the tool refuses to build the prompt
rather than ship a broken instruction — another fail-closed safeguard. The
current values live in `src/dd_agents/agents/severity_thresholds.py` (one short,
readable file).

---

## Audit it yourself

You don't have to take this page's word for any of it. These commands are
**read-only** — they never change files or call the AI — and they show you
exactly what the system uses:

```bash
# List every specialist agent and whether it's enabled for a given deal
dd-agents agents list
dd-agents agents list --config ./deal-config.json

# Show one agent's persona, focus areas, and the full non-removable safety floor.
# The footer prints the exact editable Markdown file behind that agent.
dd-agents agents describe --agent legal

# Print the COMPLETE briefing the pipeline would assemble for an agent —
# every layer in this page, in order, exactly as the AI receives it.
dd-agents agents preview --agent legal
```

`describe` is the quickest way to confirm "what is this agent told to do, and
what safety rules constrain it?" `preview` is the way to confirm "and here is the
*entire* assembled instruction, nothing hidden." Read either against the
Markdown files above and they will match.

---

## Where to go next

You've now seen *what the agents are* and *how their instructions are built*. The
natural next step is changing them for your deal:

- **[Agent Customization](agent-customization.md)** — how to add focus areas,
  swap a persona, or adjust severity for a specific deal, all without code (and
  all on top of the safety floor described here). **Read this page first; that
  one second.**
- **[Deal Configuration](user-guide/deal-configuration.md)** — the deal-config
  file, including the inline form of customization.
- **[Search Guide](search-guide.md)** — using the contract-search templates above
  without running the full pipeline.
- **[System Card](system-card.md)** — the tool's overall safety posture and
  anti-hallucination layers.
