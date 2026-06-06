# Launch Recordings — terminal & screen

Reproducible, high-quality recording scripts for the launch video and Product Hunt gallery.
All terminal recordings use [VHS](https://github.com/charmbracelet/vhs) (`brew install vhs`) so they
render identically every time — no live typing, no mistakes, no flaky timing.

## House style (matches `../demo-v1.6.tape`)
- 1920×1080, `FontSize 18`, `Catppuccin Mocha`, `Framerate 30`, `TypingSpeed 25ms`, `Padding 30`.
- Run every tape **from the repo root**: `vhs docs/marketing/recordings/<name>.tape`.
- Output MP4s land in `../assets/` (kept out of the recordings dir to separate source from artifact).

## The tapes (in video-cut order)

| Tape | Captures | Used in |
|------|----------|---------|
| `01-atlas-run.tape` | The headline moment: `dd-agents run` on Project Atlas — the 13-agent pipeline executing across 9 domains, cross-domain step firing | Hero video [0:20–0:34], gallery #1 |
| `02-quick-scan.tape` | `dd-agents run --quick-scan` — GREEN/YELLOW/RED triage in seconds | Teaser, gallery |
| `03-search-cite.tape` | `dd-agents search` — a targeted question returning a cited answer (exact quote) | Hero [0:43–0:51], gallery (citation) |
| `04-cli-tour.tape` | `dd-agents --help` + `validate` + `assess` — the breadth of the tool, dev-credible | B-roll, gallery |
| `05-install.tape` | `pip install dd-agents` one-liner + `dd-agents version` | Hero [1:14–1:22], end card |

> **Dependency:** tapes 01–03 read the **real** Project Atlas run output. Run the pipeline first
> (`dd-agents run examples/project-atlas/deal-config.json`) so the findings/report exist, then record.
> The HTML report walkthrough (verdict → cross-reference view → citation hover) is a **screen**
> recording, not a tape — see `screen-recording-guide.md`.

## Rendering all tapes
```bash
for t in docs/marketing/recordings/*.tape; do vhs "$t"; done
```
