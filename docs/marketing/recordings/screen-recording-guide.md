# Screen-Recording Guide — the HTML report walkthrough

The terminal tapes (VHS) cover the CLI. This guide covers the **HTML report** footage —
the visual payoff of the launch video and the richest Product Hunt gallery images.
Record with Screen Studio / Screen Charm (auto-zoom on cursor) at **1920×1080, 60fps**,
browser zoom ~110–125% so text is crisp when scaled.

## Source
After `dd-agents run examples/project-atlas/deal-config.json`, the report is at:
`examples/project-atlas/sample_data_room/_dd/forensic-dd/runs/latest/report/index.html`
Open it in a clean browser window (no bookmarks bar, no extensions visible, light theme
unless the report ships dark). Hide the OS dock/menubar.

## Shot list (record each as its own clip; the editor assembles them)

| # | Shot | What to do on screen | Maps to video beat |
|---|------|----------------------|--------------------|
| S1 | **The verdict** | Land on the report top: the Go / No-Go view + executive headline. Hold 3s. | Hero [0:58–1:06]; gallery #4 (verdict) |
| S2 | **The hero finding** | Scroll to the cross-domain finding (Meridian CoC ↔ $12.4M / 30% ARR cliff). Click to expand it. | Hero [0:34–0:43] |
| S3 | **The cross-reference view** | Show the finding linking the Legal change-of-control flag to the Finance concentration flag — the "connect the dots" panel. Hover the link. | Hero [0:34–0:43]; gallery #3 (the reveal) |
| S4 | **The citation (the proof)** | Hover/click the finding's citation to reveal file → section → **verbatim quote** (Meridian MSA §12.3). Cursor-zoom this. Hold 3s — this is the money shot. | Hero [0:43–0:51]; gallery (citation) |
| S5 | **Severity filter / drill-down** | Use the severity filter (P0/P1…) to show the report is interactive; filter to P0 and land on the hero finding. | B-roll; gallery |
| S6 | **Cross-domain map** | If the report renders the cross-domain trigger table / correlation view, capture it. | Hero [0:30–0:34] |
| S7 | **Excel export** | Quick cut: open the 16-sheet `.xlsx` (from the run's report dir), scroll the findings + cross-reference sheets. | Hero [0:58–1:06]; gallery #5 |

## Capture settings
- 60fps, 1920×1080, cursor-zoom ON, smooth-scroll ON.
- Move the cursor deliberately and slowly — fast jitter looks bad zoomed.
- Record 2–3 takes of S4 (the citation reveal); it's the most important frame in the whole video.
- No real data is on screen — Project Atlas is synthetic — so nothing needs redaction.

## After capture
- Drop clips into the master timeline per the timecodes in `../video-brief.md`.
- The "connect-the-dots" motion graphic (nine nodes → two light up → line draws) is built in
  After Effects / Motion, **not** screen-recorded — it intercuts with S3/S6 as the brand signature.
