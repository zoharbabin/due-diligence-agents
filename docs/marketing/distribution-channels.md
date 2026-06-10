# Distribution Channels — where to publish dd-agents

> Research-backed map of every strong channel to publish and distribute **Due Diligence Agents**,
> prioritized. Synthesized 2026-06-07 from launch-platform/directory/AI-tool research + the
> existing [Product Hunt plan](producthunt-launch-plan.md) and the broader launch plan in project memory.

## The core strategy (read first)

dd-agents has **two audiences that barely overlap**, so we run **two distribution tracks**:

1. **Developers / OSS** — discover via GitHub, Hacker News, package registries, AI-agent lists, dev launch platforms. They reward *open-source, `pip install`, local-run, the 13-agent architecture, cited/auditable*. This track is **free, high-volume, and SEO-compounding**.
2. **M&A / PE / corp-dev / legaltech professionals** — the value buyers. They don't browse Product Hunt; they're reached via LinkedIn, legaltech press/newsletters, niche communities, and conferences. **Lower volume, far higher intent.**

**Two governing principles from the research:**
- **Distribution is a cadence, not an event.** "One launch is a coin flip; 12 launches is a marketing engine." Launch something (a feature, a milestone, a case study, the video) on *one* channel per month, forever — each gives a fresh story + a compounding backlink.
- **Never copy-paste the same blurb** across directories (Google duplicate-content penalty) — rewrite the value prop per platform. Always add **UTM params** (`?utm_source=<channel>&utm_medium=listing`) so we can see what actually works.

Our durable success metrics (free OSS, no signup funnel): **GitHub stars, PyPI/Docker installs, backlinks/DR, newsletter/press pickups, and qualified inbound from M&A pros.**

---

## TIER 1 — do these first (highest ROI, mostly free)

### Developer track
| Channel | Why / how | Effort | Notes |
|---|---|---|---|
| **Product Hunt** | The headline launch — see [producthunt-launch-plan.md](producthunt-launch-plan.md). Traffic spike + DR-91 backlink + newsletter + investor eyeballs. | High (1 day live) | Already fully planned. |
| **Hacker News — Show HN** | Post the **GitHub repo** (HN favors repo links over branded URLs). Brutal but high-signal; a front-page Show HN can do more than PH for a dev tool. Separate day from PH. | Med | Maker first comment = the build story. Don't ask for upvotes. |
| **GitHub itself** | Our home base. Optimize: README hero, 20 topics, social-preview image, Discussions on, good-first-issues, a crisp `about`. PR into **Awesome lists** (below). | Ongoing | Stars are the OSS currency; everything points here. |
| **Awesome-* lists (PRs)** | High-DR, evergreen, free. Submit PRs to: `e2b-dev/awesome-ai-agents`, `kyrolabs/awesome-agents`, `Shubhamsaboo/awesome-llm-apps`, `slavakurilyak/awesome-ai-agents`, `mahseema/awesome-ai-tools`, plus an **awesome-legaltech** list. | Low each | One PR per list; tailor the one-line description. |
| **DevHunt.org** | PH-for-dev-tools, open-source friendly. Use as a **dress rehearsal** ~a week before PH. | Low | GitHub integration is a plus. |
| **Reddit** | Free/OSS gives latitude paid SaaS lacks. `r/opensource`, `r/Python`, `r/MachineLearning`, `r/LLMDevs`, `r/LocalLLaMA` (local-run angle!), `r/SideProject`, `r/webdev` Showoff Saturday. | Med | Lead with the problem + OSS tool; link repo; be a real participant, not a drive-by. |

### M&A / professional track
| Channel | Why / how | Effort | Notes |
|---|---|---|---|
| **LinkedIn (founder-led)** | Zohar's own posts are the single best M&A-pro channel. The missed-clause / "nobody connects the dots" story + the live sample report. #DueDiligence #LegalTech #MandA #PrivateEquity #CorporateDevelopment. | Low, recurring | Highest-intent reach we have; post the video here. |
| **Artificial Lawyer** (Richard Tromans) | The legaltech outlet of record. Pitch *after* a strong PH result — "open-source forensic DD" + "Product of the Day" is a trend-story hook. | Med (pitch) | Email pitch; offer founder availability. |
| **LawNext / Legaltech Hub** (Bob Ambrogi) | Podcast + directory. LegalTech Hub is a major **legaltech product directory** — get listed. | Med | Directory listing is evergreen; podcast is a stretch but high-value. |

---

## TIER 2 — strong, do within the first month

### AI-tool & agent directories (free or low-cost, dofollow, SEO-compounding)
Submit with a **rewritten** blurb + the sample-report link + UTMs. Highest-value first:
- **There's An AI For That (TAAFT)** — highest DR in the AI niche; best long-term organic traffic. (Free queue slow; paid ~$199 guarantees newsletter to ~400k.)
- **Futurepedia** — niche B2B categorization, ~1M visits, 180k newsletter. Good fit for a "business/back-office AI" tool.
- **Toolify.ai** — power users/researchers; ~48h approval.
- **futuretools.io** (Matt Wolfe) — free, huge traffic, dofollow.
- **topai.tools**, **easywithai.com**, **insidr.ai**, **genai.works** (massive LinkedIn) — free/cheap, dofollow.
- **AI-agent-specific marketplaces**: Altern (1000+ agents), AI Agents Directory, AI Agent Store, aiagentsdirectory.com, AgentMCP directory (if/when we expose MCP). These are where someone searching *"AI agent for due diligence"* lands.

### Dev launch platforms (one per month cadence)
- **BetaList** (pre-launch signups, submit 2–4 wks early), **Peerlist** (technical community), **Uneed** (solid for AI tools), **Microlaunch**, **Tiny Launch / Tiny Startups** (newsletter-driven), **Indie Hackers** (launch + community — Zohar should be a real member).

### Package registries (meet developers where they install)
Every new install path = a new discovery surface + credibility:
- ✅ **PyPI** (`pip install dd-agents`) — live.
- ✅ **Docker Hub + GHCR** — live.
- ✅ **Homebrew** (tap) — live.
- **conda-forge** — submit a recipe; reaches the data-science/Python-analyst crowd (very on-target for finance/DD users).
- **pipx** — document `pipx install dd-agents` (isolated CLU installs; already works).
- **Snap / Scoop / WinGet / AUR** — optional; broaden OS reach if there's Windows/Linux desktop demand. (We already ship Docker, so lower priority.)

### Content platforms (the flywheel)
- **Dev.to** + **Hashnode** (`#showdev`, `#ai`, `#opensource`) — repurpose the trust-layer article + "how I built 13 cross-referencing agents" + "what I learned launching on PH."
- **Medium** (Better Programming / Towards Data Science-style pubs) for the M&A-meets-AI angle.
- **daily.dev** — get the blog approved as a source; devs see every post.
- **Console.dev**, **GitHub20k**, **OpenSourceAlternative.to / OpenAlternative** — free dev-tool newsletter/directory submits.
- **YouTube** — the launch video + a screen-recorded walkthrough; evergreen search ("AI due diligence", "automate contract review").

---

## TIER 3 — niche, high-intent, longer lead time (M&A / legaltech depth)

- **Legaltech directories & review sites**: Legaltech Hub, **G2** + **Capterra** (Gartner-owned, buyer-intent traffic; claim free profiles, gather reviews), **AlternativeTo** ("alternative to Kira/Luminance/Litera" captures competitor search), **SaaSHub**, **Slashdot/SourceForge** (legacy but real OSS traffic).
- **M&A / PE / corp-dev communities**: corp-dev & PE Slack/Discord groups, **Axial** (lower-middle-market deal community), the SourceScrub/Grata/Sourceco orbit (adjacent deal-sourcing audiences). Be a contributor, not a spammer.
- **Newsletters/podcasts**: "AI and the Future of Law", LawNext, legaltech substacks; PE/corp-dev newsletters (e.g. deal-sourcing roundups). Pitch the founder story + the open-source angle (rare in this space).
- **Conferences** (2026): **ILTACON** (Aug), **Legal Geek** (Oct), **CLOC Global** (May), corp-dev/M&A summits. Even a lightning demo or a hallway-track presence drives credibility. Most have a startup/demo track.
- **Academic / research**: the [knowledge-architecture](../knowledge-architecture.md) foundations make this credible — arXiv-adjacent writeups, or sharing the eval datasheet, reach the "AI for law/finance" research crowd.

---

## Positioning notes per track (keep messaging honest + on-brand)
- **Dev channels** → lead with the tagline's *mechanism*: open-source, 13 agents, cross-reference across 9 domains, cite to an exact quote, runs local. Show `pip install dd-agents` + the sample report.
- **M&A channels** → lead with the *pain*: the buried clause nobody connects across siloed workstreams; "accelerates your advisors, doesn't replace them" (never "board-ready", never "replaces advisors").
- **Everywhere**: the [live sample report](https://zoharbabin.github.io/due-diligence-agents/sample-report/) is the zero-friction "aha" — link it in every listing.

## Anti-patterns (from the research)
- Don't dump the same blurb everywhere (duplicate-content penalty).
- Don't pay for low-DR/low-traffic directories or "$200/yr for shitty traffic" link farms — vet SimilarWeb traffic + dofollow before paying.
- Don't spray cold communities you're not part of (Meetric's lesson) — quality over quantity.
- Don't treat any single launch as the finish line — it's the cadence that compounds.

## Suggested 90-day cadence
- **Week 0**: GitHub polish + Awesome-list PRs + PyPI/Docker/Homebrew (done) + free AI directories.
- **Launch week**: DevHunt (rehearsal) → Product Hunt → Show HN (separate day) → LinkedIn + X + Reddit.
- **Weeks 2–4**: conda-forge recipe, dev.to/Hashnode posts, remaining AI directories, BetaList/Peerlist/Uneed.
- **Month 2**: Artificial Lawyer / LawNext pitch (using PH result), G2/Capterra/AlternativeTo profiles, a YouTube walkthrough.
- **Month 3+**: one launch/month (new feature, case study, the video), conference/community presence, niche newsletters.

---
*Channel inventory current as of 2026-06-07; re-verify traffic/pricing/dofollow before paying for any listing.*
