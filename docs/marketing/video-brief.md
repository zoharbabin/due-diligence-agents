# Marketing Video — Brief & Script

> One launch video for **Due Diligence Agents** (`dd-agents`). Concept, production brief, and a shot-by-shot script in one file. Built to dramatize the *real* moat — **cross-domain cross-referencing** ("nobody connects the dots") — and land the tagline: **"Legal flags a risk. Finance another. We connect and cite."**

---

## 1. The big idea — "The Clause Nobody Connected"

A cold-open mini-thriller: a deal is about to close. Three specialist reviewers each sign off on their own domain — all green. The deal is *seconds* from signing. Then the agents connect two findings nobody linked, trace both to the exact quote, and flip the verdict. **The drama isn't a bug or a villain — it's the silent gap between siloed workstreams that this tool closes.**

Why this concept wins:
- **It shows, doesn't tell, the one thing competitors can't copy.** Anyone can claim "AI reads contracts." Only we own *"the risk no single reviewer connects."* The video is built around that exact gap.
- **It's the founder's true story** (corp-dev lead, weeks spent connecting dots across siloed advisor reports) — so it's authentic, not invented drama.
- **The multi-avatar device has a job.** The talking faces literally *are* the siloed specialists — each confidently right about their slice, collectively blind to the connection. That's the problem made visual. (Avatars used with narrative purpose = not gimmick.)
- **It earns the proof beat.** The climax is a real citation to an exact page + quote — our anti-fabrication credibility, shown not asserted.
- **Dual-audience by design.** M&A pros feel the deal-table tension; developers get a real terminal run + "open-source, runs local, pip install" payoff.

**Tone:** confident, forensic, a little cinematic — *Spotlight* / a heist's "here's how the pieces connect" reveal, not SaaS-explainer cheese. Dry wit over hype. Never fear-mongering; the hero is *clarity*, not catastrophe.

**Guardrails (hard — from CLAUDE.md):** never imply it's "board-ready" or that it *replaces* advisors — it *accelerates* them (the human makes the call). No real company names, people, or financials — use the synthetic deal ("Project Atlas", "Target Inc.", "Buyer Corp"). No "zero hallucinations" claim. Cite, don't overclaim.

---

## 2. Formats & specs (cut once, export many)

Edit a single master timeline, then export three cuts:

| Cut | Length | Use | Aspect |
|-----|--------|-----|--------|
| **Hero** | 75–90s | Product Hunt first comment, README, docs, YouTube | 16:9 (1920×1080) |
| **Social teaser** | ~20s | X / LinkedIn launch-day, the cold open + tagline + CTA | 1:1 or 9:16 |
| **Silent loop** | 10–12s | GitHub social preview / PH gallery GIF, captioned, no audio | 16:9 |

**Production specs:**
- Subtitles burned in (open captions) — most watch muted; the dialogue/VO must read silently.
- Terminal + screen recordings at 2× readability: large font (≥18pt), high-contrast theme, cursor-zoom on key moments (Screen Studio / Screen Charm style). Never show a raw 12-pt terminal.
- Real product, real (synthetic) data — actual `dd-agents` CLI output and the live HTML sample report (`zoharbabin.github.io/due-diligence-agents/sample-report/`). No faked UI.
- Brand: iris logo + palette (`docs/marketing/assets/logo.svg`); reuse `social-preview.png` end card.
- Music: tense, minimal, building pulse (think understated electronic) → resolves to a clean, confident button at the CTA. Duck under all VO.
- Pace: cold open fast; demo section breathes (let one real finding land); CTA crisp.

---

## 3. Cast & assets

- **Avatars (talking faces):** 3 "specialist reviewers" (Legal, Finance, Commercial) — distinct, professional, each on-screen only briefly. Optional 4th: the **Narrator/Founder** avatar (or Zohar's real face for authenticity — recommended for the "why I built this" beat; real founder > avatar for trust).
- **Screen/terminal recordings:** (a) `dd-agents run` pipeline executing; (b) the HTML report — Go/No-Go verdict, severity filter, drill-down to a finding; (c) the cross-reference view linking two findings across domains; (d) the citation hover showing the exact page + verbatim quote; (e) `pip install dd-agents` one-liner.
- **Motion graphics:** the "connect-the-dots" animation — two domain nodes on screen, a line drawing between them (this is the visual signature of the whole brand; reuse it as the logo-adjacent motif).
- **End card:** logo + tagline + `github.com/zoharbabin/due-diligence-agents` + `pip install dd-agents`.

---

## 4. Shot-by-shot script (Hero cut, ~85s)

Format: **[TIME] VISUAL — AUDIO.** VO = voiceover; OC = on-camera/avatar; SFX/MUSIC noted. On-screen text in **bold**.

---

**[0:00–0:06] COLD OPEN — the silos**
Visual: Split screen, three avatar faces stacked or side-by-side, each in their own tile. Each says one clipped line, fast cuts.
- LEGAL (OC): "Change-of-control clause — standard. **Cleared.**"
- FINANCE (OC): "Revenue recognition checks out. **Cleared.**"
- COMMERCIAL (OC): "Customer concentration's within range. **Cleared.**"
SFX: three crisp "approved" stamps. MUSIC: low pulse begins.
On-screen: **Three reviewers. Three green lights.**

**[0:06–0:12] THE FALSE CALM**
Visual: A deal-room/signature UI or a "Project Atlas — Ready to Sign" screen, cursor hovering a glowing **Sign** button. Timer-like tick.
VO (calm, dry): "Every workstream signed off. The deal's ready to close."
On-screen: **Project Atlas — synthetic deal.** *(tiny disclaimer, keeps it honest)*
MUSIC: pulse tightens. Beat of silence.

**[0:12–0:20] THE GAP**
Visual: Pull back — the three avatar tiles float apart with literal *gaps* between them. A faint dotted line tries to form between Legal's tile and Finance's tile, then fades.
VO: "But nobody read across the room. The change-of-control trigger in Legal… and the revenue cliff in Finance… are the *same* risk. Connected."
On-screen: **No one connected them.**
MUSIC: drops out for a half-beat on "the *same* risk."

**[0:20–0:30] ENTER THE PRODUCT — terminal**
Visual: Hard cut to a clean terminal. Type-on: `dd-agents run project-atlas.json`. The 13-agent pipeline scrolls — domain agents firing in parallel (readable, cursor-zoomed). Logo flicker-in.
VO (confident shift): "So I built the reviewer that *does* read across the room."
On-screen: **13 AI agents. 9 domains. Every document.**

**[0:30–0:42] THE CONNECT-THE-DOTS REVEAL (the signature moment)**
Visual: Motion graphic — nine domain nodes in a ring. Two light up (Legal ⚖, Finance $). A bright line **draws between them** and locks. Cut to the actual HTML report's cross-reference view showing the two linked findings.
VO: "It cross-references findings across every domain — and surfaces the one a single reviewer would walk right past."
On-screen: **The risk no one domain sees.**
MUSIC: the "resolve" chord lands as the line connects.

**[0:42–0:54] THE PROOF — citation**
Visual: Zoom into the finding card. Hover/click reveals the **exact citation**: file, page, section, and a highlighted **verbatim quote** pulled from the document. Severity badge flips the verdict.
VO: "And it doesn't ask you to trust it. Every finding traces to an exact page and quote. If it can't verify, it halts."
On-screen: **Found. Connected. Quoted.**
MUSIC: clean, certain.

**[0:54–1:04] THE VERDICT FLIP**
Visual: The "Ready to Sign / green" screen from the cold open re-appears — the Go/No-Go verdict updates from green to a flagged **Review** state, the cross-domain risk pinned at the top of the report.
VO: "The deal that was seconds from signing? Now you see the whole picture — *before* you sign."
On-screen: **From 'cleared' to clear-eyed.**

**[1:04–1:14] THE FOUNDER BEAT (real face > avatar)**
Visual: Zohar on camera (or founder avatar), warm, direct.
OC: "I spent years as a corp-dev lead stitching this picture together by hand, across weeks of siloed reports. This does it in one run — and it's open source."
On-screen: **Open-source. Runs locally. Apache-2.0.**

**[1:14–1:22] THE DEV PAYOFF + CTA**
Visual: Terminal one-liner type-on: `pip install dd-agents`. Quick flashes — sample report, Excel export, chat. End card resolves.
VO: "Read the whole data room. Connect every domain. Cite every flag."
On-screen (end card): **Due Diligence Agents** · *Legal flags a risk. Finance another. We connect and cite.* · `pip install dd-agents` · github.com/zoharbabin/due-diligence-agents
MUSIC: final confident button.

**[1:22–1:25] TAG**
Visual: Logo + "See a live report — no install" → sample-report URL.

---

## 5. Social teaser (~20s)

Cut from the master: **[0:00–0:20]** cold open (three "cleared" + the gap) → hard cut to the connect-the-dots line drawing → tagline card → `pip install dd-agents`. End on the dots-connecting motif. First 2 seconds must work silently (open captions): **"Three reviewers. Three green lights. One risk nobody connected."**

## 6. Silent loop (~10–12s, GIF/preview)

Pure motion: nine nodes → two light up → line draws between them → citation quote highlights → logo + tagline. No VO. This is the brand's visual signature; reuse the node-connect animation as a recurring motif across all assets.

---

## 7. Writing/VO notes
- VO voice: lower, measured, a touch of dry confidence. Not announcer-y, not startup-peppy.
- Every claim must be literally true (forensic audience): "traces to an exact quote," "if it can't verify, it halts" (the quality gate), "cross-references across domains." No "zero hallucinations," no "replaces your advisors," no "board-ready."
- The villain is *the gap between silos*, never a person. Keep the three reviewers competent and likeable — they're right about their slice; the point is that nobody owned the connection.
- Numbers are fine and credible: 13 agents, 9 domains. Avoid leading on agent-count as the *hook* — lead on the connect-the-dots story; the numbers are support.

## 8. Asset checklist (pre-shoot)
- [ ] Synthetic deal config + data room that *actually produces* a clean cross-domain finding (Legal CoC ↔ Finance revenue) with a real citation — so the demo footage is genuine. (Build/curate this first; the whole video hinges on one real linked finding.)
- [ ] Clean terminal theme, ≥18pt, cursor-zoom tool.
- [ ] HTML report walkthrough recorded at 1440p+: verdict → filter → drill-down → cross-reference view → citation hover.
- [ ] 3 specialist avatar clips (short lines) + founder on-camera (or avatar) clip.
- [ ] Connect-the-dots motion graphic (the signature animation) + end card from `social-preview.png`/logo.
- [ ] Music bed (licensed) + SFX (stamp, tick, resolve).
- [ ] Burned-in caption pass on all three cuts.

## 9. Distribution
- **Hero** → Product Hunt first comment (the proven engagement lever), README hero, docs, YouTube (public, full link).
- **Teaser** → X thread opener + LinkedIn launch-day post.
- **Silent loop** → GitHub social preview, PH gallery image #1, Reddit where video autoplay helps.
- Pair with the existing 23-slide [walkthrough deck](presentation.html) for anyone who wants depth after the video hooks them.

---

*Source of truth for positioning: the locked tagline + cross-domain moat (see `producthunt-launch-plan.md`). Keep the video, the PH listing, and the README telling the same one story.*
