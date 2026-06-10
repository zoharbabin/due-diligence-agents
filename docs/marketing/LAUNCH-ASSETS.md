# Launch Assets — Index

Everything produced for the Product Hunt launch, in one place. Positioning is locked
(see `producthunt-launch-plan.md`): tagline **"Legal flags a risk. Finance another. We connect and cite."**,
moat = cross-domain cross-referencing, proof = forensic citation, and a supporting
enterprise differentiator = **no vendor lock-in** (runs on Anthropic API, your own
Bedrock/Vertex, or any model via an Anthropic-compatible gateway — env config only).

> **One golden sample, everywhere.** Project Atlas is now the *single* canonical example across the
> whole repo — the quickstart (`examples/project-atlas/`), the public sample report
> (`docs/sample-report/index.html`, regenerated via `scripts/generate_sample_report.py`), the launch
> demo/recordings, the docs, and a unit guard test (`tests/unit/test_project_atlas_example.py`).
> All prior placeholder deals, the hardcoded-mock sample generator, and the legacy
> demo tape/script/showcase/video have been retired — Atlas is the only sample in the repo.

## 1. The demo deal — "Project Atlas" (the foundation)
`examples/project-atlas/` — a 100% synthetic M&A deal engineered so the product's hero
cross-domain finding is **real and reproducible**, not staged.
- **Target:** Northwind Logistics Software ($41.2M ARR TMS SaaS) · **Acquirer:** Summit Industrial Group.
- **Hero finding (verified P0):** Meridian Freight = 30.1% of ARR **and** its MSA §12.3 auto-terminates
  on change of control → the acquisition itself lets the biggest customer walk. Legal sees the clause,
  Finance sees the concentration; the tool connects them and cites §12.3 verbatim.
- 11 source docs (`data_room/Northwind_Logistics/`) + `deal-config.json` (validates) + buyer reference.
- Continuity source-of-truth: `project-atlas-bible.md`. Run output (`data_room/_dd/`) is gitignored.
- **Re-run:** `dd-agents run examples/project-atlas/deal-config.json` (≈12 min on Bedrock; all gates pass).

## 2. The real report (captured output)
`sample-report-atlas/` — genuine artifacts from the run above:
- `index.html` (520KB, **fully self-contained** — opens anywhere; the screen-recording source).
- `dd_report.xlsx` (14-sheet workbook).
- `findings_merged.json` (44 merged findings: 2× P0, 10× P1, 17× P2, 15× P3).

## 3. The video
- `video-brief.md` — concept "The Clause Nobody Connected", shot-by-shot script, 3 cuts, brand motif.
- `launch-copy-pack.md` §3 — teleprompter-ready: cold-open avatar lines, 85s hero VO (timecoded),
  founder on-camera line, 20s teaser VO, burned-in on-screen text cards.

## 4. Terminal & screen recordings
`recordings/` — reproducible VHS tapes (house style: 1920×1080, FontSize 18, Catppuccin Mocha, 30fps):
- `01-atlas-run.tape` ✅ rendered · `04-cli-tour.tape` ✅ rendered · `05-install.tape` ✅ rendered
- `02-quick-scan.tape`, `03-search-cite.tape` — record against a **live** run (they wait on real command output).
- `screen-recording-guide.md` — the HTML report walkthrough shot list (S1–S7; S4 citation reveal = money shot).
- Rendered MP4s land in `assets/`. Re-render: `for t in recordings/*.tape; do vhs "$t"; done` (from repo root).

## 5. Launch copy (`launch-copy-pack.md`)
7 sections, guardrail-checked: PH listing fields (within char limits) + 2 A/B descriptions ·
maker first comment · full video scripts · X thread (7 tweets) · LinkedIn post · 3 supporter-DM
templates · 6 gallery-image specs.

## Screenshots (`screenshots/`)
Refreshed from the **real** Atlas report (via Playwright against the live HTML):
`01-executive-dashboard` (Conditional Go verdict, Summit→Northwind), `02-domain-overview`
(per-domain finding counts), `03-cross-domain-synthesis` (Northwind P0, 44 findings, Domain
Interaction Matrix), `04-action-items`. The remaining legacy shots (deal-breakers, risk-heatmap,
filter-bar, integration-playbook, mobile-view) are best recaptured in the screen-recording
session — see `recordings/screen-recording-guide.md`.

## Still to produce (creative/manual)
- Connect-the-dots **motion graphic** (brand signature — built in motion software, not screen-recorded).
- **Avatar clips** (3 specialist reviewers) + **founder on-camera** beat.
- Capture the **HTML report screen walkthrough** + the **Excel** scroll from the captured report.
- Final **video assembly** per the brief's timecodes; export Hero / Teaser / Silent-loop cuts.
- Lock the launch date → schedule the PH "Coming Soon" page (see `producthunt-launch-plan.md` for the runway).

## Guardrails (apply to every asset)
No "board-ready"; never "replaces advisors" (it accelerates them); no "zero hallucinations"
(the gate *catches* fabrication); never ask for upvotes (ask for feedback); synthetic data only.
