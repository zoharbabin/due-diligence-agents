# Due Diligence Agents — Launch Copy Pack (final, ship-ready)

**Maker:** Zohar Babin (solo) · **Launch:** Product Hunt, 12:01am PT
**Links:** github.com/zoharbabin/due-diligence-agents · `pip install dd-agents` · sample report: zoharbabin.github.io/due-diligence-agents/sample-report/

**Unified voice (applied throughout):** dry, confident, evidence-first. No swagger, no buzzword soup. The villain is always the *gap between silos*, never a person. The hero is *clarity*. Every claim is literally true to the product. The tool **accelerates** advisors and **cites** its work — humans decide.

**Editor's guardrail sweep — what I changed:**
- **Char limit fix:** A/B Description Variant A was **262 chars (over the 260 PH limit)** despite the draft claiming 257. Tightened to **251** ("the risk that lives between them" → "the risk between them"). Tagline verified at **57/60** (draft said 56 — within limit either way).
- **No "board-ready"** anywhere — kept as "Go / No-Go view," "basis for deliverables," "brief your advisors."
- **No "replaces advisors"** — every surface carries an explicit accelerate-not-replace line.
- **No "zero/no hallucinations"** — framed as the gate *catching* unverified output and *halting*.
- **No upvote asks** — every CTA requests feedback only.
- **Moat + tagline consistency** verified across all assets: cross-domain connection is the hook; forensic citation is the proof; the locked tagline lands verbatim.

---

## 1. Product Hunt Listing Fields

| Field | Value | Chars |
|-------|-------|-------|
| **Name** | Due Diligence Agents | 20 / 40 ✓ |
| **Tagline** | Legal flags a risk. Finance another. We connect and cite. | 57 / 60 ✓ |
| **Description (primary)** | Open-source AI for M&A due diligence. 13 agents read your whole data room across 9 domains, connect findings no single reviewer links, and trace every flag to an exact quote — or the quality gate halts. Runs locally. pip install dd-agents. | 239 / 260 ✓ |

**Launch tags (3):** Artificial Intelligence (broad — agents are the hook) · Open Source (broad — Apache-2.0 + local-run = trust) · Fintech (niche — closest topic to M&A/deal diligence).

**Topics at submission:** lead with **AI + Open Source + Fintech**. Backups if one is unavailable or to weight developers harder: Developer Tools, Productivity, GitHub, SaaS.

### A/B Description variants (both verified within 260)

**Variant A — founder / "gap between silos" (251 chars ✓)** *— strongest emotional hook for M&A pros*
> Your legal, finance, and commercial reviewers each sign off green — and miss the risk between them. 13 open-source AI agents read the full data room, connect the dots across 9 domains, and cite every flag to an exact quote. Or they halt. Runs locally.

**Variant B — forensic-citation proof (245 chars ✓)** *— best for the skeptical "show me it's real" segment*
> Every M&A finding traced to an exact page and verbatim quote — or the pipeline halts rather than ship it. 13 open-source agents read every doc across 9 domains and connect risks no single-domain reviewer does. Local-first. pip install dd-agents.

---

## 2. Maker First Comment (Product Hunt)

Hi Product Hunt 👋 I'm Zohar, and I built this to solve a problem that cost me weeks of my life.

As a corp-dev lead, I'd sit on top of siloed advisor reports — legal, finance, commercial — each flagging the same target independently, none of them talking to each other. A change-of-control clause buried in one contract and a revenue cliff hiding in another were the *same risk*, but they lived in separate workstreams. The danger was never any one report. It was the gap between them. I'd spend weeks by hand connecting the dots nobody else connected.

So I built Due Diligence Agents. 13 AI agents read your entire data room across 9 domains (Legal, Finance, Commercial, Product/Tech, Cybersecurity, HR, Tax, Regulatory, ESG), cross-reference what no single-domain reviewer ever links, and trace every finding to an exact page and a verbatim quote. If a finding can't be verified against the source, the quality gate halts rather than ship it.

What makes it different: the cross-domain connection is the whole point, and forensic citation is the proof. It's open-source (Apache-2.0) and runs locally — your documents only leave as API calls to your own LLM provider. **No vendor lock-in:** run it on the Anthropic API, your own AWS Bedrock or Google Vertex account, or *any* model (GPT, Gemini, a local model) behind an Anthropic-compatible gateway — all by env config, no code change. `dd-agents doctor` verifies your setup before a run, and every run records which provider/model produced the findings. It accelerates your advisors; humans still decide.

See a sample report (no install): https://zoharbabin.github.io/due-diligence-agents/sample-report/
Code: https://github.com/zoharbabin/due-diligence-agents · `pip install dd-agents`

I'm here all day. Drop feature requests in the comments and I'll build live, and I'm happy to give anyone a personal walkthrough.

One question for this crowd: what's the cross-domain risk that slipped through a deal *you* worked on — the one nobody connected until it was too late?

---

## 3. Video Scripts — "The Clause Nobody Connected"

**Hero cut: ~85s · Social teaser: ~20s.** Synthetic deal only ("Project Atlas"). No real company, person, or financial data. Villain = the gap between silos. Hero = clarity.

**Direction for talent:** dry, confident, under-stated. Not announcer-y. The facts carry the weight. Read straight through the periods; do not lift at line ends. Pauses are marked `(beat)`.

### (a) Cold open — three specialist-avatar lines
Three reviewers, three screens, each signing off on their own domain. One clean clip each. They never look at each other — that is the point.

| Avatar | On-camera line | Direction |
|---|---|---|
| **Legal** | "Legal review complete. Change-of-control clause flagged, noted, cleared." | Crisp, procedural. Green check lands on "cleared." |
| **Finance** | "Finance review complete. Revenue concentration flagged, noted, cleared." | Identical cadence to Legal — deliberately. |
| **Commercial** | "Commercial review complete. Top customer renewal flagged, noted, cleared." | Brisk, satisfied. Third green check. Then silence. |

> Each said "flagged." Each said "cleared." None of them said the same risk to each other.

### (b) Hero cut — voiceover (~85s, timecoded)
> One continuous read. Timecodes are guide rails, not hard cuts mid-sentence.

**[0:00–0:06] Cold open** — *(no VO; let the three "cleared" lines and three green checks play)*

**[0:06–0:12]** "Three reviews. Three sign-offs. Three greens. (beat) A deal seconds from signing."

**[0:12–0:20]** "Legal saw a change-of-control clause. Finance saw a revenue cliff. Commercial saw a renewal at risk."

**[0:20–0:27]** "Each cleared their own domain. (beat) Nobody connected them. The gap between the reports is where deals get hurt."

**[0:27–0:34]** "Due Diligence Agents reads the whole data room — across nine domains — and looks for the line that links the two."

**[0:34–0:43]** "Here, it connects them: the change-of-control trigger and the revenue cliff are the same risk. If control changes, the contract terminates — and the revenue goes with it."

**[0:43–0:51]** "Then it proves it. Every finding traced to an exact page and a verbatim quote. (beat) If it can't cite the source, it halts instead of shipping the claim."

**[0:51–0:58]** "That's the catch the quality gate is built to make — fabrication doesn't get through; it stops the run."

**[0:58–1:06]** "You get one interactive report with a Go / No-Go view, a fourteen-sheet workbook, and a JSON record behind every flag."

**[1:06–1:14]** "It runs locally. Your documents only leave as API calls to your own LLM provider. It's open source. (beat) It doesn't replace your advisors — it gets them to the connected picture faster."

**[1:14–1:20]** "Read every doc. Connect every domain. Cite every flag."

**[1:20–1:25] End card** "Legal flags a risk. Finance another. (beat) We connect and cite."

### (c) Founder on-camera line (~2 sentences)
> Real face, plain room, no graphics. The trust beat.

"I once spent weeks rebuilding the same picture by hand — legal, finance, and commercial had each flagged the same target, separately, and nobody had connected the threads. I built this so the connection — and the proof behind it — shows up on day one, not week three."

### (d) Social teaser — voiceover (~20s)

**[0:00–0:04]** "Legal cleared it. Finance cleared it. Commercial cleared it."
**[0:04–0:08]** "Same target. (beat) Same risk. Three reviews, none connected."
**[0:08–0:14]** "Due Diligence Agents reads all nine domains, connects the finding nobody linked, and traces it to an exact quote."
**[0:14–0:18]** "Can't cite it? It halts. (beat) Open source. Runs locally."
**[0:18–0:20] End card** "Connect every domain. Cite every flag."

### (e) Burned-in on-screen text cards

**Hero cut**

| Beat | Card text |
|---|---|
| 0:00 (over Legal clip) | `LEGAL — CLEARED` |
| 0:02 (over Finance clip) | `FINANCE — CLEARED` |
| 0:04 (over Commercial clip) | `COMMERCIAL — CLEARED` |
| 0:06 | `Three greens.` |
| 0:20 | `Nobody connected them.` |
| 0:27 | `9 domains. Read in full.` |
| 0:34 | `Change-of-control × revenue cliff = one risk` |
| 0:43 | `Traced to page + verbatim quote` |
| 0:51 | `Can't cite it? It halts.` |
| 0:58 | `Go / No-Go report · 16-sheet workbook · JSON per finding` |
| 1:06 | `Runs locally · Open source` |
| 1:14 | `Read every doc. Connect every domain. Cite every flag.` |
| 1:20 (end) | `Legal flags a risk. Finance another.` / `We connect and cite.` |
| 1:24 (lockup) | `Due Diligence Agents` · `pip install dd-agents` · `github.com/zoharbabin/due-diligence-agents` |

**Social teaser**

| Beat | Card text |
|---|---|
| 0:00 | `CLEARED. CLEARED. CLEARED.` |
| 0:08 | `One risk. Nobody connected it.` |
| 0:14 | `Cited to an exact quote.` |
| 0:18 | `Connect every domain. Cite every flag.` |
| 0:19 (lockup) | `Due Diligence Agents` · `pip install dd-agents` |

---

## 4. X / Twitter Launch Thread (7 tweets)

**Posting note:** Tweet 1 carries the demo clip (the verdict-flip moment) or the live-report link. Keep links out of the middle tweets so reach isn't throttled. Put PH + repo + sample links in Tweet 7. Reply to your own thread with the live report once posted.

**1/ (Hook)**
Three advisors reviewed the same deal. Legal flagged a Change-of-Control clause. Finance flagged a revenue cliff. Nobody connected them — they were the same risk.

I spent weeks of my career being the person stitching siloed reports together by hand.

So I open-sourced the M&A tool I wish existed. 🧵

**2/ (The problem)**
Due diligence is run in silos. Legal reads legal. Finance reads finance. Each signs off green on their own domain.

The deal-killers live in the GAPS between them — the clause one team sees and another would've cared about, if anyone had told them.

That gap is what burns acquirers.

**3/ (The how)**
Due Diligence Agents reads the entire data room with 13 AI agents across 9 domains — Legal, Finance, Commercial, Product/Tech, Cybersecurity, HR, Tax, Regulatory, ESG — then CROSS-REFERENCES findings no single-domain reviewer connects.

Legal flags a risk. Finance another. We connect and cite.

**4/ (The proof — citation + gate)**
Every finding is traced to an exact page and a verbatim quote. If a claim can't be verified against the source, the quality gate halts instead of shipping it.

It doesn't replace your lawyers or bankers — it accelerates them, and hands them analysis they can actually stand behind.

**5/ (Open-source + local + no lock-in)**
Apache-2.0, runs locally. Your data room never leaves your machine — only API calls to YOUR LLM provider go out. And no vendor lock-in: Anthropic API, your own AWS Bedrock / Google Vertex, or any model (GPT, Gemini, local) via a gateway — env config, zero code change.

pip install dd-agents (or Docker). Read the prompts, edit the agents, fork the whole thing. #buildinpublic

**6/ (What you get)**
Output is built to be reviewed, not trusted blindly:

• Interactive HTML report with a Go/No-Go view + drill-down to the source quote
• 16-sheet Excel for the workstreams
• Per-finding JSON for anything you want to script

It's a basis for your deliverables — humans still decide.

**7/ (CTA)**
We're live on Product Hunt today and I'd genuinely love your feedback — what's missing, what you'd trust, what you wouldn't.

→ PH: [Product Hunt link]
→ Code: github.com/zoharbabin/due-diligence-agents
→ Live sample report: zoharbabin.github.io/due-diligence-agents/sample-report/

Built solo. Tell me where it's wrong. 🙏

*5-tweet cut: fold 2 into 1 (problem into hook) and 6 into 4 (proof + deliverables).*

---

## 5. LinkedIn Launch Post

Legal flagged a change-of-control clause. Finance flagged a revenue concentration cliff. Both reviews came back clean — because each was right about its own domain, and neither was looking at the other's.

That's the gap that has cost me weeks of my career: siloed workstreams, three advisor reports on the same target, and the real risk sitting in the space *between* them where nobody owns the connection.

So I built Due Diligence Agents — an open-source tool that reads an entire data room across nine domains (legal, finance, commercial, tax, regulatory, HR, cyber, product/tech, ESG), then does the part humans rarely have time for: it cross-references findings across those domains and traces every flag to an exact page and a verbatim quote. If it can't cite it, it halts rather than ship something unverified.

It does not replace your lawyers, bankers, or deal team — it accelerates them. Humans still decide. It just connects the dots and hands your advisors a cited starting point instead of a blank page.

Runs locally. Your documents never leave your environment except as API calls to your own LLM provider — and there's no vendor lock-in: run it on the Anthropic API, your own AWS Bedrock or Google Vertex account, or any model via an Anthropic-compatible gateway, all by configuration.

We're live on Product Hunt today. I'd genuinely value your read on it — see a sample report and tell me where it's wrong:

Sample report: https://zoharbabin.github.io/due-diligence-agents/sample-report/
Code: github.com/zoharbabin/due-diligence-agents

Feedback welcome — especially the critical kind.

#DueDiligence #LegalTech #MandA #PrivateEquity #OpenSource

---

## 6. Supporter DM Templates (feedback, never upvotes)

**1. Close connection**
Hey [Name] — launching something today I think you'll have opinions on. It's an open-source tool that cross-references M&A diligence findings across domains (the legal-flag-meets-finance-flag problem we've both lived) and cites every flag to an exact quote. I'm not after upvotes — I genuinely want your gut reaction, especially anything that feels off. Sample report's here if you have 5 min: https://zoharbabin.github.io/due-diligence-agents/sample-report/ — would love your honest take.

**2. Professional network**
Hi [Name] — I've been building a forensic M&A diligence tool and it's live on Product Hunt today. The idea came from a pain I suspect you know: siloed advisor reports where the real risk lives between the domains nobody connects. It reads the full data room across nine domains, cross-references, and traces every finding to a verbatim source. It accelerates a deal team, doesn't replace it. No ask for votes — I'd just value your professional read and any pushback. Sample: https://zoharbabin.github.io/due-diligence-agents/sample-report/

**3. Fellow founder**
Hey [Name] — shipped my thing today, open-source, on Product Hunt. It's AI agents for M&A due diligence: read every doc, connect every domain, cite every flag — and it halts rather than ship anything it can't verify. You know the launch-day drill, so no upvote ask — what I'd actually value is a builder's eye on it. Where's the positioning weak? What would make you bounce? Repo and a live sample report: github.com/zoharbabin/due-diligence-agents · https://zoharbabin.github.io/due-diligence-agents/sample-report/ — brutal feedback more than welcome.

---

## 7. Product Hunt Gallery Specs (6 images)

Read as one mini-walkthrough scroll: **what it is → cross-domain reveal → the cited finding → the report verdict → export & local → install.** Every panel is literally true and uses real assets (live sample report, `docs/marketing/screenshots/`, real terminal output, synthetic "Project Atlas" only).

**Brand system (all 6):** Canvas deep navy `#0a0f1e` (secondary surface `#111827`). Iris signature `#6366f1` → `#8b5cf6` (the "connect" motif, logo, active highlight, headline keyword). Three-domain triad reused from the report: Legal blue `#3b82f6`, Finance green `#10b981`, Commercial violet `#8b5cf6`. Severity: critical red `#dc3545`, high orange `#fd7e14`, good green `#10b981`. Type: one clean grotesk (Inter); headline 56–72px bold, caption 24–28px @ 60–70% opacity; mono (JetBrains/SF Mono) for terminal. Format 1270×760 (16:10), 64px safe margins, logo lockup bottom-left every frame. One focal element per image; iris glow sparing.

**#1 — Scroll-stopper (thumbnail/lead).** Headline: "Legal flags a risk. Finance another. **We connect and cite.**" Sub: "Open-source forensic M&A due diligence. 13 AI agents read the whole data room across 9 domains." Visual: connect-the-dots still — left Legal-blue card "Change-of-Control trigger," right Finance-green card "Revenue cliff," one bright iris arc joining at a node labeled "SAME RISK." Faint greyed disconnected domain cards behind imply the gap. Headline top third, cards + arc dead center, sub bottom. The arc is the hero.

**#2 — Cross-domain reveal (the moat).** Headline: "Connect the dots no single-domain reviewer does." Sub: "Neurosymbolic triggers spot when a Legal finding and a Finance finding are the same risk — then re-examine across domains." Visual: real cross-domain synthesis view (`03-cross-domain-synthesis.png`) in browser chrome; pull one row forward with an iris ring — a correlation linking a Legal trigger ↔ a Finance ARR concentration, labeled "Project Atlas Entity." Optional `06-risk-heatmap.png` inset for breadth. Screenshot right 60%, text left 40%; one iris callout line to the highlighted row. Must read "two domains, one connected risk," not "a dashboard."

**#3 — The cited finding (proof).** Headline: "Every finding traced to an exact quote. Or we halt." Sub: "Hover any flag → the verbatim clause and the exact page it came from. The quality gate blocks unverified output." Visual: one enlarged finding card from `09-legal-findings.png` with the citation hover state open — severity badge (critical red `#dc3545`), finding title, expanded tooltip showing a verbatim quote with a real `Page N` anchor + source filename; iris underline ties claim to quote. Card centered-left, tooltip popping right with iris glow + shadow. Do NOT write "zero hallucinations" — the honest, stronger claim is "traced to an exact quote, or we halt." Synthetic clause only.

**#4 — Report / Go·No-Go verdict (the deliverable).** Headline: "An interactive report with a clear verdict — built to brief your advisors." Sub: "Go / No-Go view, deal-breakers, action items, risk heatmap. Filter by severity and drill into any finding." Visual: executive dashboard (`01-executive-dashboard.png` / `05-deal-breakers.png`) in browser chrome; foreground the verdict banner showing real sample value "Conditional Go" + deal-breaker count + severity tally; show filter bar (`07-filter-bar-active.png`) as a thin strip; iris accent on the active filter pill. Caption stays "to brief your advisors" / "basis for deliverables" — never "board-ready," never "replaces advisors."

**#5 — Export + local + no lock-in (the practical close).** Headline: "16-sheet Excel, per-finding JSON — runs locally, on your model." Sub: "Your documents never leave your machine except as API calls to your own LLM provider. No vendor lock-in — Anthropic API, your Bedrock/Vertex, or any model via a gateway. Apache-2.0, open source." Visual: split panel — left, a 16-tab Excel still (tabs along the bottom, one sheet showing findings rows with severity + citation columns); right, a "local" trust motif (laptop/terminal + shield) with the data-flow line `Data room (your disk) → agents (local) → your LLM API → report (your disk)`, iris on the "your disk" endpoints. 50/50 vertical split, thin iris divider; badges bottom-right: "Apache-2.0," "Local-first," "BYO model." Keep the data-flow line literally accurate.

**#6 — Install (CTA, dev-native).** Headline: "Read every doc. Connect every domain. Cite every flag." Visual: clean terminal block on `#0a0f1e`, mono, copy-paste ready:
```
$ pip install dd-agents
$ dd-agents run deal-config.json
```
Below it, three faint real-run status lines: `✓ 9 specialists  ·  ✓ citations verified  ·  ✓ quality gate: passed`. Optional Docker one-liner for parity. Footer: "github.com/zoharbabin/due-diligence-agents · Live sample report linked below. · Tell me what breaks — feedback welcome." Iris caret (`$`) the one accent. CTA invites feedback, never upvotes. Terminal text must be a real `dd-agents run` capture, not faked.

**Sequencing & asset map**

| # | Beat | Primary real asset |
|---|------|--------------------|
| 1 | What it is (scroll-stopper) | Connect-the-dots still (custom brand art) |
| 2 | Cross-domain reveal (moat) | `03-cross-domain-synthesis.png` (+ `06-risk-heatmap.png` inset) |
| 3 | Cited finding (proof) | `09-legal-findings.png` + citation hover |
| 4 | Report verdict | `01-executive-dashboard.png` / `05-deal-breakers.png` / `07-filter-bar-active.png` |
| 5 | Export + local | 16-sheet Excel still + local data-flow motif |
| 6 | Install (CTA) | Real terminal output |

**Cross-frame consistency:** same navy canvas, same iris signature, same logo corner, same type scale, one focal element per frame. The three-domain triad (blue/green/violet) threads through #1, #2, #3 so the cross-domain story carries from thumbnail to proof.

**Asset gaps:** #2/#3/#4 ship today from existing screenshots. #1 (connect-the-dots still) is custom brand art — worth the design time, it's the scroll-stopper. #5's Excel still should be captured from a real Project Atlas export once available. #6 terminal text must be a real capture.

---

## Final guardrail self-check (whole pack)
- **"Board-ready":** absent. Reports framed as "Go / No-Go view," "basis for deliverables," "brief your advisors."
- **"Replaces advisors":** absent. Explicit accelerate-not-replace line on PH comment, video, X, LinkedIn, and Gallery #4.
- **"Zero/no hallucinations":** absent. Consistently "traced to an exact quote, or we halt" / gate *catches* fabrication.
- **Upvote asks:** none. Every CTA (PH comment, X tweet 7, LinkedIn, all 3 DMs, Gallery #6) asks only for feedback.
- **Tagline:** verbatim on PH tagline field, video end card, X tweet 3, Gallery #1.
- **Spec A/B line ("Read every doc. Connect every domain. Cite every flag."):** lands on video [1:14], Gallery #6.
- **Cross-domain moat first, citation as proof:** consistent across all assets.
- **Char limits:** Name 20/40, Tagline 57/60, Desc 239/260, Variant A 251/260 (**fixed from 262 over-limit**), Variant B 245/260 — all within PH limits.
- **No real company/person/financial data:** synthetic "Project Atlas" only; author Zohar Babin named per policy.