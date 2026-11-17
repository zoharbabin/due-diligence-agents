# Desktop App Plan

Status: **in progress.** The views in the table below are built: Projects, Run, Report, Findings, Ask, Compare, Agents, Screening, History and Settings, plus in-app updates. For what ships today, read [the desktop app guide](../user-guide/desktop-app.md) and `desktop/README.md`, not this plan. The sections below are the original proposal and still describe the design intent. Release CI also writes the Homebrew cask and the winget manifests as Release assets. Every `desktop.yml` build installs the macOS DMG and the Windows setup file on a clean runner, starts the app, and checks that its service starts, writes the service log and stops when the app is killed (`desktop/scripts/smoke_installed.py`). A manual signed run of `desktop.yml` passes on both systems, and the macOS app and DMG are Developer ID signed, notarized and stapled (Gatekeeper accepts both on an Apple Silicon Mac). The first signed release is out (see `RELEASE.md`) and the cask is in the owner's tap. The winget manifests are submitted to winget-pkgs and wait for review. The manual `desktop-upgrade.yml` run installs one published release over the previous one on macOS and Windows and the app starts (the Windows user data file survives). The in-app update button was run live on macOS, from one published build to the next. The Windows in-app update button was not run live. The owner accepted that. The installer swap on Windows is tested in `desktop-upgrade.yml`, and the in-app flow is the same updater code as on macOS. Not done yet: the checks under Manual checks that need hardware (a clean macOS user account and spikes S3 and S6). `desktop/e2e/live_model.py` is a manual end-to-end check against a real model provider.

Original research: two rounds on 2026-11-15, against the code in `src/dd_agents/`, local measurements on an Apple Silicon Mac, and the public sources linked inline. Each claim is marked **verified** (checked here), **sourced** (from a doc, not re-tested), or **unverified** (needs a Phase 0 spike).

Goal: a signed, installable Mac and Windows app. Deal teams manage projects, run analyses, read reports, compare targets, and edit agents and prompts. No terminal, no Python install.

## Owner decisions (fixed)

| Decision | Value |
|----------|-------|
| Signer | An individual, not a company. Certificates and accounts are personal. |
| Rust | Acceptable, if install and use stay easy on every OS. Rust code stays small (see Architecture). |
| macOS | **Apple Silicon only** (`aarch64-apple-darwin`). No Intel build. |
| Windows | In scope. x64 only in v1. |
| Location | United States. Azure Artifact Signing is open to US individuals. |
| Accounts | **Reuse the owner's existing Azure (Artifact Signing) and Apple Developer accounts**, already used to release `web-researcher-mcp` and `fen`. **Verified** by reading their release workflows and `docs/RELEASE_SIGNING.md` in those repos. No new accounts, no new validation. |
| Product name | **Due Diligence Agents** (repo and package: `due-diligence-agents`). No "Claude" in it, so the Anthropic branding rule is met. Proposed bundle ID, following `fen`'s pattern: `com.zoharbabin.due-diligence-agents` (to confirm before the first signed build, since changing it later breaks updates and stored data paths). |
| Priorities | Best UX first. Then easy install, easy configuration, easy maintenance and safe updates. |

## Decisions at a glance

| # | Decision | Recommendation | Why |
|---|----------|----------------|-----|
| 1 | Architecture | Web UI + local HTTP API (`dd-agents serve`) + thin native shell | Reuses the Python core. Shell stays swappable. UI also runs in a browser for dev and CI. |
| 2 | Shell | **Tauri v2** | Small installers, scoped permissions, first-class updater. Electron stays the fallback (same API contract). |
| 3 | `claude` CLI | **Download at first run, pinned and checksum-verified. Do not bundle it.** | Keeps Anthropic's binary unmodified (a license condition). Cuts every app update by about 150 MB. Removes the SignPath proprietary-code conflict. Gives Windows ARM64 a binary later. |
| 4 | Python runtime | **Embedded runtime (uv / python-build-standalone) + pre-installed wheels** in app resources | **Verified:** 213 MB on disk, 69 MB gzipped, `dd-agents --version` in 0.33 s warm. Keeps entry points and package data working. |
| 5 | Dependency diet | Replace scikit-learn, drop scipy, drop onnxruntime | **Verified** equivalent (see Optimizations). About 175 MB less on disk. |
| 6 | API server | FastAPI + uvicorn in a new `[app]` extra | Pydantic v2 models exist, so OpenAPI and TypeScript types come free. |
| 7 | Runs | One subprocess per run, progress via `events.jsonl` | Cancel = kill. Reuses checkpoints and `locked_by` PID. |
| 8 | Frontend | React + TypeScript + Vite, shadcn/ui, TanStack Query and Table | Largest component pool. |
| 9 | Secrets | OS keychain, injected into the run subprocess env only | Never in `.env`, config or logs. |
| 10 | Windows signing | **The owner's existing Azure Artifact Signing account**, via Tauri `signCommand` running Microsoft's own `signtool` + Artifact Signing dlib on a Windows runner. No Java. | **Sourced** ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations)). The account and individual validation already work in `web-researcher-mcp`, which uses `jsign` (Java) instead. No hardware token. Signing is required in practice: Windows 11 Smart App Control blocks unsigned apps outright. SignPath is no longer needed. |
| 11 | Stores | Skip the Mac App Store and the Microsoft Store. | Mac sandbox does not fit (spawns binaries, reads arbitrary folders). Tauri builds only EXE and MSI, and the Store does not re-sign those, so the Store gives no signing benefit here. |
| 12 | Distribution | Direct download (DMG, NSIS setup) + in-app updater. Homebrew cask (own tap) and winget as follow-ups. | One signed artifact per OS. Package managers only repackage it. The owner already runs a Homebrew tap, a Scoop bucket and a winget-pkgs fork for `web-researcher-mcp`. |
| 13 | Process lifetime | The Python server exits when its stdin closes. The shell also kills the tree (process group on macOS, Job Object on Windows). | No orphans after quit, crash or force-kill (see Lessons). |

## Optimizations to the current stack

All numbers are from a fresh `uv venv` (CPython 3.13, macOS arm64) with `dd-agents` installed.

| Item | Measured | Action |
|------|----------|--------|
| `claude` binary inside the SDK wheel | 331 MB of 687 MB site-packages (**verified**) | Do not ship it in the app. Download pinned version at first run. |
| scikit-learn + scipy | 31 MB + 70 MB, import costs 1.3 s (**verified**) | Replace with a small TF-IDF function in `entity_resolution/matcher.py` (only user of sklearn, scipy, numpy in `src/`). |
| onnxruntime | 80 MB (**verified**) | **Done** in `desktop/scripts/build_runtime.py` (`UNUSED_PACKAGES`): the runtime build removes `magika`, `onnxruntime` and their two orphan packages, and `extraction/office_convert.py` loads markitdown with the stand-in. Checked: Office conversions of the extraction corpus are byte-identical with and without them, and the extraction unit tests pass without them. |
| Total, app payload | 720 MB on disk, 265 MB gzipped, with `claude` and sklearn. 213 MB on disk, 69 MB gzipped without (**verified**). | Every app update downloads about 70 MB, not 265 MB. |

**TF-IDF replacement, verified.** `_pass_4_tfidf_match` uses `TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4))` plus cosine similarity. A 30-line pure-Python version (same n-gram rule, smooth idf, L2 norm) matched sklearn on 3,000 random name sets: max absolute difference 8.9e-16, no argmax mismatches, and the "empty vocabulary" case raises the same way. It ran faster than sklearn on those inputs. The prototype lives only in `/tmp`. Production change needs a test file first (rule 9), the same equivalence test with fixed fixtures, and a drop of `scikit-learn` from `pyproject.toml`. `numpy` is used only for `argmax` there, so check whether it can go too (pandas and markitdown may still pull it).

## What already exists (reuse, do not rebuild)

| Need | Existing piece | Gap |
|------|----------------|-----|
| Project list | `persistence/project_registry.py` → `ProjectRegistryManager` (`~/.dd-projects/project_registry.json`, `DD_BASE_DIR` override, `locked_by` PID) | Check concurrent-write safety when the app and CLI both write. Check for a schema version field. |
| Config forms | `models/config.py` → `DealConfig` | Generate form schema from `model_json_schema()`. No hand-built forms. |
| Config wizard | `dd-agents init`, `auto-config`, `validate --json` | Wrap as API calls. |
| Pre-flight | `dd-agents doctor --json --probe` | None. |
| Run | `orchestrator/engine.py` → `PipelineEngine.run()`, checkpoints, resume | **No event stream.** `orchestrator/progress.py` defines `PipelineProgressTracker`, but nothing calls it (**verified** by grep). |
| Cost | `agents/cost_tracker.py`, `dd-agents cost --json`, `budget_limit_usd` | **No pre-run estimate.** Actuals only. |
| Reports | `reporting/html.py`, `excel.py`, `pdf_export.py`, `export.py` | None to view. |
| Run compare | `dd-agents diff --json`, `reporting/diff.py` | None. |
| Target compare | `dd-agents portfolio compare` | **Shallow** (risk score, counts, severity totals). Needs a domain-level comparison. |
| Ask / search | `chat/engine.py`, `query/engine.py`, `search/runner.py` | Chat needs a streaming adapter. |
| Agents and prompts | `customization/loader.py`, `agents list/describe/validate/preview` | Editor UI only. Strict format (4 headings, fixed front-matter keys), so a form is safe. |
| History | `knowledge/chronicle.py` | None. |
| Screening | `dd-agents screening ...` | None. |
| CLI path | `utils/__init__.py` → `resolve_sdk_cli_path()`: `DD_AGENTS_CLI_PATH`, then `claude` on PATH, then SDK-bundled | The app sets `DD_AGENTS_CLI_PATH` to its own pinned binary. A GUI app does not inherit the shell PATH anyway (see Lessons). |

## Architecture

```
┌────────────── Tauri shell (Rust, small) ───────┐
│  window, menu, tray, updater, keychain         │
│  CLI provisioner (download + verify + pin)     │
│  spawns Python, passes port + token, reaps it  │
│        ▲ WebView (React UI)                    │
└────────┼───────────────────────────────────────┘
         │ HTTP + SSE on 127.0.0.1:<random>, bearer token
┌────────▼──────── Python (embedded runtime) ────┐
│ python -m dd_agents serve  (FastAPI)           │
│   read: registry, findings, reports, config    │
│   write: config, dd-config/, project registry  │
│   spawns:  dd-agents run <config>  (per run)   │
│            tails runs/<id>/events.jsonl → SSE  │
└────────┬───────────────────────────────────────┘
         │ claude_agent_sdk → pinned claude CLI (app data dir)
         ▼ Anthropic / Bedrock / Vertex / gateway (user's own credentials)
```

Rust surface (target: stays small, reviewable in one sitting): spawn and reap the Python process, per-launch token and port, health check, CLI provisioner, tray, keychain bridge, and wiring for the updater, dialog and shell plugins. Everything else is the web UI and Python. Pin the toolchain in `rust-toolchain.toml`. Contributors who only touch UI or Python never need Rust (browser mode: `dd-agents serve` + `vite dev`). End users never need Rust, Python, or Node.

Why the Python runtime is app **resources**, not a Tauri `externalBin` sidecar: `externalBin` expects one executable per target triple ([Tauri sidecar docs](https://v2.tauri.app/develop/sidecar/)). An embedded runtime is a directory tree, so Rust launches `<resources>/python/bin/python -m dd_agents serve` itself. **Unverified:** whether Tauri's macOS signing step signs nested `.so`/`.dylib` files inside resources. Phase 0 spike S1 must check this. If it does not, the release script signs every Mach-O in the tree before the bundle is sealed.

Why not PyTauri (Python embedded in the Rust process): it ties the Python version to the Rust build and puts Python in the UI process, so a crash or long GIL hold freezes the window. This is reasoning, not a measured test. A separate process also matches the existing "one subprocess per run" model.

Rules for the API (mechanical):

1. Bind `127.0.0.1` only. Random port. New bearer token per launch. Check `Host` and `Origin` (blocks DNS rebinding). No CORS.
2. Serve files only from registered project directories. Resolve and reject `..` and symlink escapes.
3. The API never bypasses a quality gate. Validation failures return as errors (rule 8).
4. Every LLM call still goes through `dd_agents.llm.build_agent_options` (rule 1). The API adds no LLM code.
5. Severity stays with `resolve_severity()` (rule 12). The UI never re-derives it.
6. Run progress comes from `events.jsonl` written by the engine, not from parsing logs.
7. Token goes to the WebView by Tauri IPC, not by URL or file. Evaluate a Unix socket / named pipe in Phase 1 (**unverified** that uvicorn + WebView2 fetch can use it without a proxy). Loopback + token is the baseline.

### New backend work

| Item | Detail |
|------|--------|
| `src/dd_agents/api/` | Routers: projects, config, runs, findings, reports, compare, agents, settings, chat. Tests first in `tests/unit/api/` (rule 9). |
| `events.jsonl` | Wire `PipelineProgressTracker` into `PipelineEngine`. One JSON line per step start/end, agent progress, finding counts, cost, gate failure. Atomic append. Versioned schema in `models/`. |
| Pre-run estimate | Token estimate from inventory size and agent count. Show a range, label it an estimate. Live actual cost against `budget_limit_usd`. |
| Domain compare | Aggregate two projects' findings by domain and severity. Matrix plus top differing findings. |
| Chat adapter | Stream `ChatEngine.ask()` over SSE. Keep session and cost counters. |
| `dd-agents serve` | Headless entry point. Also gives browser mode for dev, CI, and Linux users. |
| Dependency diet | sklearn replacement, optional onnxruntime removal (above). |
| `[app]` extra | `fastapi`, `uvicorn`, `keyring`. Check each against existing deps first. |
| Data versioning | Add a schema version to the registry and any new app-written files. Refuse to open data written by a newer version (downgrade guard). |

## Views

| View | Contents | Backed by |
|------|----------|-----------|
| **Projects** | Cards: name, buyer → target, status, last run, risk score, severity counts. Search, archive, open folder. | `ProjectRegistryManager` |
| **New project wizard** | 1. Pick folder. 2. Scan summary (files, types, extraction gaps). 3. "Suggest setup" (auto-config). 4. Review config in plain forms. 5. Pre-flight. 6. Start. | `init`, `auto-config`, `validate`, `doctor` |
| **Run** | Pre-run: estimate, budget cap, dry-run step list. Live: step timeline, one row per agent with subject progress, finding counts, cost vs cap, log drawer. Cancel, resume. | `events.jsonl`, checkpoints |
| **Report** | Embedded `dd_report.html` in a sandboxed frame. Open in browser, Excel, PDF, CSV, show in folder. | `reporting/` |
| **Findings** (review table) | Rows are entities. Columns are domains and questions (summary, date, yes/no, verbatim). Each cell shows a short summary and opens the exact quote, page and source document. Filter, sort, export to Excel/CSV. Comments on cells, rows and columns. Activity sidebar for comments and value changes. User-defined columns (a column builder) are a later step, since they need a new backend path. Per-subject files only (rule 2). | `findings/{agent}/{subject}.json` |
| **Ask** | Chat and search over the project. Cited answers link to findings. Shows session cost. | `chat/`, `query/`, `search/` |
| **Compare** | Tab 1: run vs run (new, resolved, changed). Tab 2: target vs target (domain × severity matrix, top differences). | `reporting/diff.py`, new domain compare |
| **Agents** | List with enabled state and model. Editor per agent: persona, focus areas, instructions, severity overrides (the 4 recognised headings). Profile picker (`extends`). Live assembled-prompt preview. Built-in vs yours diff. | `customization/loader.py`, `agents preview` |
| **Screening** | Status, update, check, user lists. | `screening/` |
| **History** | Timeline of runs, searches, chats, annotations. | `knowledge/chronicle.py` |
| **Settings** | Provider (Anthropic, Bedrock, Vertex, gateway), keys, model routes, extraction options, update channel, diagnostics export. | `doctor --json`, `llm/provider.py` |

### Agent and prompt editor rules

- The safety floor (rule 11) shows as a locked, read-only block at the end of the preview. It cannot be edited or hidden.
- Severity thresholds (rule 13) show as read-only values. Overrides go through the bounded `Severity Overrides` section only.
- Save runs `agents validate` first. Fail-closed: invalid files are not written.
- Warn on save: changing prompts changes the provenance hash, so an in-flight checkpoint will be rejected on resume (rule 15).
- Built-in prompt prose in `agents/prompts/**/*.md` stays developer-owned. The UI edits only `dd-config/` (rule 14).

### UX principles

| Principle | Concrete rule |
|-----------|---------------|
| First result fast | Install to running analysis in under 5 minutes. Three questions: provider and key, folder, "Analyze". Everything else defaults from auto-config. The one-time engine download shows a progress bar and starts while the user picks a folder. |
| Same disclosure as the report | Verdict first, then actions, then detail, then evidence. Mirrors the 4 layers in `docs/user-guide/reading-report.md`. |
| Money is visible | Estimate before, live cost during, hard cap always. |
| Evidence one click away | Every finding shows its quote and opens the source page. |
| Plain words | UI says "Entity", not "subject" (rule 7). No "board-ready". Copy states the tool accelerates advisors, it does not replace them. |
| Safe by default | Destructive actions (remove project, delete run) are separate and confirm. Removing a project never deletes the data room. |
| Native feel | Cmd on Mac, Ctrl on Windows. Dark mode. Keyboard-first tables. WCAG AA contrast and focus states. Keep CSS conservative: WKWebView and WebView2 differ from Chromium. |
| Honest errors | Map `doctor` and `CLINotFoundError` style failures to one fix action each ("Open Settings", "Retry"). |

## Anthropic terms and branding (sourced)

From [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) and [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), read 2026-11-15:

| Rule | What it means for the app |
|------|---------------------------|
| Running Claude Code inside a product is allowed under the Commercial Terms. | Redistribution is not a blocker. Earlier "gating risk" is downgraded. |
| The binary must not be modified. Auth methods must not be removed or restricted. | Download it unmodified and keep Anthropic's signature. Do not re-sign it. This is the main reason for decision 3. |
| Do not pay for or resell Claude usage for end users. Each user brings their own API key or Bedrock / Vertex / Foundry credential. | Settings asks for the user's own credentials. No shared key. No app-side billing. |
| No claude.ai login or subscription-limit passthrough for third-party products. | Offer API key and cloud providers only. Do not add "Sign in with Claude". |
| Do not call the product "Claude Code", and do not use Anthropic names or logos in the product name. "X Powered by Claude" is allowed. Do not mimic Claude Code visuals. | Pick a product name without "Claude". Use plain-text "powered by Claude" at most. |

Not verified: whether a general "ask Anthropic" step is still wise for distribution at scale. The docs say customers can do this under the Commercial Terms, so it is optional, not gating. The user (as an individual) should read the Commercial Terms once, since they bind the person who ships.

## Packaging

### How the `claude` CLI is provisioned (new design)

Facts (**verified** 2026-11-15 against the public release bucket):

- `https://downloads.claude.ai/claude-code-releases/<version>/manifest.json` lists `darwin-arm64`, `darwin-x64`, linux (glibc and musl), `win32-x64`, and `win32-arm64`, each with `checksum` (SHA256) and `size`. A `manifest.json.sig` file also exists (HTTP 200, not cryptographically checked here).
- The binary is at `<version>/<platform>/claude` (`claude.exe` on Windows). For 2.1.325: `darwin-arm64` 347,406,976 bytes, `win32-x64` 372,461,728, `win32-arm64` 354,470,048. Served uncompressed (no `Content-Encoding`).
- **Resumable.** The server sends `accept-ranges: bytes`, and a `Range` request returned HTTP 206. A 350 MB download can resume after a drop.
- `stable` (2.1.311 today) lags `latest` (2.1.325). The SDK wheel's bundled CLI is 2.1.325 (`claude_agent_sdk/_bundled/claude.version`). Pin to the SDK's own version, not to `stable`.
- The SDK accepts any CLI at or above 2.0.0 and checks the version at start (`MINIMUM_CLAUDE_CODE_VERSION` in `subprocess_cli.py`). The manifest also carries `sdkCompat` (`testedWrapperVersions`, `harnessSchema`). Its version numbers (0.3.x) do not match our Python SDK (0.2.x), so we do not rely on it.
- Binaries are signed by "Anthropic PBC" and notarized on macOS, and signed "Anthropic, PBC" on Windows ([setup docs](https://code.claude.com/docs/en/setup#binary-integrity-and-code-signing)). The manifest is GPG-signed from release 2.1.89.

Design:

1. Each app release pins one CLI version and its SHA256 per platform in a file under version control. CI fills it from the manifest of the same version as the SDK wheel pinned in `pyproject.toml`, and fails if the two disagree.
2. First run: download to `<app data>/claude/<version>/`, check size and SHA256 against the pin (the pin is covered by our own signed update, so no GPG code in the app), `chmod +x`, run `--version`, then switch a `current` pointer. Resume on failure. Offer "use my installed claude" as an advanced option and an offline file picker for locked-down networks.
3. The app sets `DD_AGENTS_CLI_PATH` to the pinned binary for every run.
4. New app releases may pin a newer CLI. Old versions stay on disk until the next successful run on the new one, then are removed. This gives rollback for free.
5. Downloaded files made by the app carry no quarantine flag on macOS. They are Anthropic-signed and notarized anyway. **Unverified:** confirm Gatekeeper and the 4 s first-run delay seen locally behave the same on a clean user account.

Cost of this design: a one-time 347 MB (Mac) or 372 MB (Windows) download on first run, against about 150 MB gzipped if bundled. Trade accepted: the installer drops to about 80 MB, updates stay small, and licensing and signing stay clean. A fully offline installer can be a second artifact later.

### Python runtime

**Verified** on this Mac: `uv venv --python 3.13` then `uv pip install .` finished in 3 s with a warm cache. The runtime tree is 58 MB and site-packages 687 MB (331 MB of that is the CLI). `dd-agents --version` took 2.96 s on the first call, 1.51 s on the second, 0.33 s after. The first call is a cold file cache and possibly Gatekeeper. Measure it again on a clean account, and on Windows with Defender running.

| | Embedded runtime + wheels (chosen) | PyInstaller (onedir) |
|---|---|---|
| Entry points (`dd_agents.specialists`) | Work | Need manual hooks |
| Data files (prompt `.md`, `report_schema.json`, profiles) | Normal package data | Must be listed in the spec |
| Antivirus profile | Many small files to scan | Frozen bootloader is a common false-positive trigger (**sourced**: common reports, not measured here) |
| Build | `uv` + a lockfile, reproducible | Spec maintenance |

Pre-compile `.pyc` files at build time so first start does not write into a signed bundle. Never write into the app bundle at runtime (it would break the signature and the updater).

### Size budget (measured, Apple Silicon)

| Piece | On disk | Gzipped |
|-------|---------|---------|
| Python runtime + wheels, lean | 213 MB | 69 MB |
| Tauri shell + UI | not measured | not measured |
| `claude` CLI (downloaded) | 347 MB | not applicable |

Target: installer under 100 MB, update download under 100 MB. Check in Phase 0.

## Updates and safe upgrades

One rule: **the app update is atomic and carries everything except the CLI and user data.** A release is one signed bundle: UI + Rust + Python runtime + wheels + pinned CLI manifest. Nothing in it is upgraded piecemeal at runtime.

| Concern | Design |
|---------|--------|
| Updater | Tauri updater plugin with a minisign key. Static `latest.json` on GitHub Releases for v1. TLS is enforced. A dynamic endpoint (for staged rollout) can replace it later without a client change. |
| Key custody | Losing the updater private key means installed apps can never update again ([Tauri docs](https://v2.tauri.app/plugin/updater/)). Keep two offline backups. Use CI secrets for the build copy only. |
| Windows signing order | Authenticode first, then regenerate the updater `.sig` ([Fluxzy field report](https://www.fluxzy.io/resources/blogs/electron-to-tauri-migration-fluxzy-desktop)). Put it in the release script on day one. |
| Windows install mode | Per-user NSIS install (no admin) so updates run without elevation. The `quiet` install mode only works for per-user installs ([Tauri docs](https://v2.tauri.app/plugin/updater/)). Use `passive` by default. **Unverified:** exact NSIS per-user setting name in `tauri.conf.json`. |
| Channels | `stable` and `beta`, two endpoints. Beta first, promote the same artifact. Do not rebuild for stable. |
| Never mid-run | Block "Restart to update" while a run is active. Show "update ready, installs when runs finish". |
| Provenance on upgrade | A new `PromptBuilder.PROMPT_VERSION` or config hash makes old checkpoints fail closed (rule 15). The app must say so in plain words: "This run started on an older version. Start it again." No bypass. |
| Data migration | Forward-only migrations with a backup copy first. Newer-than-app data opens read-only with a clear message (downgrade guard, see backend work). |
| Rollback | Publish a higher version number with the old content. Do not rely on updater downgrades (off by default). Keep the previous CLI version on disk until the next good run. |
| Update stability | Once a client is shipped with the Tauri updater, never change the update mechanism. Fluxzy stranded users when moving from Electron's updater to Tauri's. |
| Toolchain | Pin Rust and Node versions, use GitHub-hosted runners. Self-hosted runners drifted and broke Windows builds in Fluxzy's report. Enable Dependabot or Renovate for crates and npm. |
| Release flow | Extend `RELEASE.md` with a `desktop.yml` job on the same version tag. One tag, one version, both PyPI and desktop artifacts. |

## Signing as an individual

| Platform | Route | Notes |
|----------|-------|-------|
| macOS | **Developer ID Application identity, already in this Mac's keychain** (**verified** with `security find-identity`) and already used in CI by `web-researcher-mcp` (`MACOS_SIGN_P12`, `MACOS_SIGN_PASSWORD`) and `fen` (`MACOS_CERTIFICATE`). Hardened runtime, notarization. | Developer shows as the owner's personal name. **Notary credentials already exist as GitHub secrets in those repos** (App Store Connect API key in `web-researcher-mcp`, Apple ID app-specific password in `fen`). Secrets are per repo, so copy them into this repo. Map the API key to Tauri's env vars: `MACOS_NOTARY_ISSUER_ID` → `APPLE_API_ISSUER`, `MACOS_NOTARY_KEY_ID` → `APPLE_API_KEY`, and write the base64 `MACOS_NOTARY_KEY` to a temp file for `APPLE_API_KEY_PATH` ([Tauri docs](https://v2.tauri.app/distribute/sign/macos/)). **Lesson from `web-researcher-mcp` issue #204:** the `.p12` must carry the full chain (leaf, Developer ID intermediate, Apple Root CA). A leaf-only `.p12` makes AMFI kill the signed binary at launch. Copy its "Verify macOS signing chain" step into our workflow. Notarization of our tree is still untested. |
| Windows, chosen | **The owner's existing Azure Artifact Signing account and public-trust certificate profile** | **Verified in use** in `web-researcher-mcp` (`docs/RELEASE_SIGNING.md`): a service principal with the "Certificate Profile Signer" role signs releases, with an RFC-3161 timestamp. Certificates last about 3 days and rotate on every sign. The timestamp keeps old signatures valid. Identity validation is done and the subscription is paid. The signer name is the owner's validated legal name. **That repo signs with `jsign`, which needs Java. We will not copy that.** Options for this repo: (1) **`signtool` + Microsoft's Artifact Signing dlib, chosen.** It is Microsoft's own tool ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-signing-integrations)). Needs Windows SDK `signtool` 10.0.2261.755 or newer, the .NET 8 runtime, and the NuGet package `Microsoft.ArtifactSigning.Client`. A `metadata.json` names the endpoint, account and certificate profile. Call it from Tauri's `bundle.windows.signCommand`: `signtool sign /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 /dlib <dlib> /dmdf metadata.json <file>`. Auth reads `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` through `DefaultAzureCredential`, the same variable names you already use. (2) `azure/artifact-signing-action`, Microsoft's GitHub Action, which also exists. (3) `artifact-signing-cli`, a third-party Rust crate from Tauri's docs: no Java or .NET, but we would have to audit it. **Unverified:** the .NET 8 runtime and the `signtool` version on GitHub's `windows-latest` runner (install both in the workflow if missing), and whether `signCommand` signs the NSIS installer as well as the app exe. Use a separate service principal for this repo with only the signer role, so one leaked secret does not cover both projects. |
| Windows, fallback | SignPath Foundation, or an individual OV certificate | Not needed while the Azure account works. SignPath ([terms](https://signpath.org/terms)) is free for open source but names SignPath as publisher. An OV certificate costs roughly $150 to 300 per year and needs a hardware or cloud key. |
| Windows, not chosen | Microsoft Store | Free signing applies only to MSIX. Tauri produces only EXE and MSI ([Tauri docs](https://v2.tauri.app/distribute/microsoft-store/)), and Microsoft does not re-sign those. Community MSIX tools exist but add risk. |

**Why signing is required, not optional.** Unsigned apps trigger SmartScreen when downloaded in a browser. On Windows 11 with Smart App Control on, unsigned unknown apps are blocked even when not downloaded from a browser, and users cannot allow a single app ([Tauri docs](https://v2.tauri.app/distribute/sign/windows/)). A comparable Tauri + Python app (Snapmaker Studio) ships unsigned and tells users to click "Run anyway" ([README](https://github.com/DVOpenLabs/snapmaker-studio)). We should not.

SmartScreen: **no option** removes the warning on day one. Azure Artifact Signing "does not provide instant SmartScreen trust", and EV no longer helps since 2024 ([Microsoft Learn](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)). Reputation builds across releases signed by one identity, so keep the identity stable from the first public build. Write the "More info, Run anyway" steps in the install guide.

**macOS signing test (verified, this session).** I copied the uv Python 3.13 runtime (58 MB) and the dd-agents site-packages (359 MB, without the `claude` binary) to a temp folder. All 303 Mach-O files were ad-hoc signed. I re-signed all 303 with the owner's Developer ID, `--options runtime` (hardened runtime) and a secure timestamp, with **no entitlements**. Results: signing took about 7 s, `codesign --verify --strict` passed, `dd-agents --version` ran, and all 249 `dd_agents` modules imported, plus pydantic_core, lxml, Pillow, cryptography, numpy, scipy, scikit-learn, onnxruntime, rapidfuzz, openpyxl, pandas and cffi. Not covered: `pypdfium2` (not installed in the prototype), notarization itself, and whether Tauri's own signing step leaves these signatures intact. Spike S1 closes those.

## Lessons from other apps

| Lesson | Source | Rule here |
|--------|--------|-----------|
| Closing the window is not quitting. Sidecars outlived the window in Voicebox on Windows and Linux. | [Voicebox changelog](https://github.com/jamiepine/voicebox/blob/main/CHANGELOG.md) | Explicit quit path with a timeout. On launch, reap a stale server from a PID file. Windows Job Object for `python` and `claude.exe` children. |
| GUI apps get a minimal PATH. Voicebox had to search Homebrew, MacPorts and WinGet paths for `ffmpeg`. | same | Build the child env explicitly. Use absolute paths. Never rely on PATH, including for `claude` and for Git or OCR tools the extraction step may call. |
| Heavy optional parts are better downloaded after install. Voicebox downloads GPU backends on demand. | same | Same pattern for the `claude` CLI. |
| On Windows, killing a parent process leaves its children running. Cline hit this with its CLI. | [Cline issue 14221](https://github.com/cline/cline/issues/14221) | Put `python` and its children in a Job Object with kill-on-close. On macOS, kill the process group. Also make the Python server exit when its stdin closes. The shell holds the pipe, so a shell crash closes it. (Design is mine, **not measured yet**, spike S3.) |
| A Tauri app with a frozen Python loopback sidecar works in production, but closing the window left the sidecar running. Ships unsigned, users click "Run anyway". | [Snapmaker Studio](https://github.com/DVOpenLabs/snapmaker-studio) | Same architecture as ours, so it is evidence the shape works. Avoid both of its problems: sign, and reap on window close. |
| Tools with a review table (documents by questions, cell summary plus source quote) are the pattern lawyers already use. | [Harvey Vault](https://www.harvey.ai/blog), [Legora Tabular Review](https://legora.com/blog) | Findings view above. Only the table pattern was read, not a full teardown. |
| Tauri's dialog plugin has no Yes/No/Cancel. | Fluxzy | Use in-app web dialogs for confirmations. |
| Two signing systems must take turns on Windows. | Fluxzy | Release script order above. |
| Changing the updater mechanism strands users. | Fluxzy | Pick Tauri's updater once. |
| Self-hosted runner toolchain drift broke builds. | Fluxzy | Pin toolchains, use hosted runners. |
| Tauri capabilities are a good default. | Fluxzy | One capability file. Allow only: dialog, opener, updater, and the exact spawn needed. Validate any arguments. |
| Installers dropped from about 190 MB (Electron) to 55 MB (Tauri) for an app whose backend is a separate sidecar. | Fluxzy | Same shape as ours. |

**Research gaps (honest):** no usable sources for Tauri nested-binary signing details, PyTauri maturity, competitors beyond Harvey and Legora, winget requirements, Homebrew cask notability numbers, or a Unix-socket/named-pipe alternative to loopback HTTP. Phase 0 should include a 5-user walkthrough of a clickable prototype to replace the UX gap with real data.

## Install and first run

| Step | Target |
|------|--------|
| Download | One DMG (Apple Silicon) or one NSIS setup (x64, per-user, no admin prompt) from GitHub Releases. WebView2 uses the default `downloadBootstrapper` (no size cost). An offline WebView2 installer adds about 127 MB and is only for locked-down networks. |
| Open | Signed and notarized on Mac. Signed on Windows. No warning beyond the normal SmartScreen reputation prompt in the first weeks. |
| First run | 1. Choose provider and key (stored in the keychain). 2. Engine download starts in the background with progress and resume. 3. Pick a folder while it downloads. 4. Analyze. |
| Offline | File picker for a pre-downloaded `claude` binary. Option to use an already installed one. |
| Update | In-app updater, per-user, no admin. Rollback keeps the previous CLI version side by side. |
| Other channels | Homebrew cask, Scoop and winget are follow-ups. The owner already publishes `web-researcher-mcp` through a personal Homebrew tap (cask), a Scoop bucket, and a winget-pkgs fork. Per that repo's docs, the first winget submission needs a manual PR and Microsoft review. Reuse the same pattern. Notability rules for the official Homebrew cask repo were **not read**, and are not needed for a personal tap. |

## Security and privacy

Data rooms are confidential. Treat this as a requirement.

| Area | Rule |
|------|------|
| Disclosure | First-run screen: document text is sent to the configured provider. Show the active provider on every run screen. |
| Telemetry | Off. Crash reports and update checks are separate opt-ins. Document content never leaves the machine except to the chosen provider. |
| Local API | Loopback, per-launch token, Host/Origin checks, path confinement. |
| Download integrity | The CLI download is verified against a pinned SHA256 before it is ever run. Fail closed. |
| Report frame | Render `dd_report.html` in a sandboxed frame with strict CSP and no network. Quotes come from untrusted documents. Escape in the native table too. |
| Secrets | Keychain (macOS Keychain, Windows Credential Manager). Redact in logs and diagnostics export. |
| Logs | Diagnostics export strips document text and keys. |
| Process hygiene | Kill the whole process tree on quit and crash. Windows Job Object. `cli.py` has `_terminate_child_processes` for the CLI case. |
| Privacy prompts | macOS asks permission for Documents, Desktop, and external drives. Test which process the OS blames (spike S3). |

## Risks and open questions

| Risk | Severity | Action |
|------|----------|--------|
| Notarization and signing of many `.so`/`.dylib` files in the embedded runtime | High | Spike S1. Release script signs every Mach-O. Test on a clean account. |
| First-run 347 MB (Mac) / 372 MB (Windows) download on slow or locked-down networks | Medium | Progress, resume, checksum, offline file picker, optional offline installer later. |
| Windows signing from a Windows runner with `signtool` + dlib: not yet run here | Low | Spike S5. Test `signCommand` on `windows-latest` with a throwaway exe first. Fallback: `azure/artifact-signing-action`. |
| Notarization and Tauri's own signing step are untested for the nested runtime files | High | Spike S1. Use the existing notary credentials. A full-chain `.p12` is required (issue #204 lesson). |
| `pypdfium2` dylib under the hardened runtime is untested | Medium | Include in S1. |
| CLI version drift: SDK expects behavior from its own bundled CLI version | Medium | Pin CLI to the version in the SDK wheel's `claude.version`. CI gate compares them. Run `doctor --probe` in CI against the pinned pair. |
| Removing onnxruntime changes file-type detection | Medium | Run the extraction suite on all document types before and after. Keep it a separate PR. |
| Antivirus false positives on a new unsigned Windows build | Medium | Sign early. Submit builds to vendors. Prefer the embedded runtime over frozen exes. |
| Windows ARM64 | Low | v1 ships x64 only (**unverified** that it runs under emulation). Native ARM64 CLI exists (`win32-arm64` in the manifest), but Python wheels for it were not checked. |
| Windows long paths on deep data rooms | Medium | Enable long-path support in the app manifest and Python. Test with a 300+ char path. |
| Data room in cloud-synced folders (iCloud, OneDrive) syncing `_dd/` writes | Medium | Warn in the wizard. Check whether the `_dd/` location is configurable (**not yet checked**). |
| Registry concurrency between app and CLI | Medium | Review `project_registry.py` locking before Phase 1. |
| No pre-run cost estimate | Medium | Build it. Until then show only the budget cap. |
| Target compare is shallow | Low | Ship run-vs-run first. Domain compare in Phase 4. |
| Rust skill gap | Low | Rust is small and isolated. Electron fallback keeps the same API contract. Rust is not installed on this Mac yet (`cargo` not found), so Phase 0 includes toolchain setup. |
| External specialist plugins (`dd_agents.specialists`) | Low | Work with the embedded runtime. Document. |

## Live test findings

A hands-on pass on the installed macOS app and the Playwright suite found these. All are fixed and covered by a test.

| Finding | Fix |
|---------|-----|
| The in-app update added bytecode files inside the signed bundle, which broke the macOS seal after the first launch. | Precompiled hash-based bytecode, `PYTHONDONTWRITEBYTECODE=1` for the sidecar, and a seal check in `smoke_installed.py`. The Tk sample scripts are skipped in `build_runtime.py`. |
| The run panel showed internal agent names. | `agentLabel` in `desktop/ui/src/lib/format.ts`. |
| Ask said it had no findings before the first question. | The chat status reads the finding count from the review (`api/routers/chat.py`). |
| Projects saved before risk labels existed showed a different label than the report. | `_labelled()` in `api/routers/projects.py` uses `ReportDataComputer._compute_risk_label`. |
| Ask answers showed raw markdown. | `desktop/ui/src/components/Markdown.tsx`. It builds elements only, with no HTML and no links. |
| The `claude` CLI loaded hooks and CLAUDE.md files from the user's home and the data room. | `build_agent_options` sets `setting_sources=[]`. Provider env in `~/.claude/settings.json` no longer applies. Use the app's provider settings. |
| Tabs could not be used with the keyboard. | Roving tabindex and arrow, Home and End keys in `Tabs` (`components/ui.tsx`). |
| Remove dropped a project with one click. The dialog plugin makes `window.confirm` async, so the check was always true in the app. | The question is part of the page (`ProjectPage.tsx`). Do not use `window.confirm` or `alert` in the UI. |

Limits of the desktop automation: the macOS accessibility tree of the WebView can come back empty, and a click can land in another app if focus is lost. Repeatable UI checks run in Playwright against the real API (`desktop/ui/e2e/`).

## Phases (each ends with a check)

Sizes: S under 1 week, M 2 to 3 weeks, L 4 or more.

| Phase | Size | Deliverable | Exit check |
|-------|------|-------------|-----------|
| **0. Spikes** | M | S1 embedded runtime in a Tauri shell, signed and notarized on macOS, runs on a clean user account. S2 CLI provisioner: download, verify, run `doctor --probe` with a real key. S3 folder permissions and process attribution on macOS and Windows. S4 sklearn replacement + onnxruntime removal PRs (tests first). S5 Add the Azure and Apple secrets to this repo (new service principal), then sign a throwaway exe from `windows-latest` and a test DMG, and notarize it. S6 clickable prototype shown to 5 users. | On clean macOS and Windows 11 VMs: install, first-run download, launch, one live `doctor --probe` call. Report installer size, update size, cold start, VirusTotal result. Written go/no-go. |
| **1. Backend API** | L | `dd_agents.api`, `dd-agents serve`, `events.jsonl`, `[app]` extra, data versioning. OpenAPI published. | `pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/` green. A run with a mocked LLM streams events end to end (`dd_agents.testing` only has a data generator today, so the mock is new work). `test_docs_drift.py` passes. |
| **2. Shell, Projects, Settings** | M | Tauri app, onboarding, project list, provider setup, keychain, wizard up to pre-flight. | Playwright e2e in browser mode and a manual pass on both OSes: zero to "ready to analyze" in under 5 minutes. |
| **3. Run and Report** | L | Live run view, cancel/resume, cost, report viewer, exports. | Full run on `examples/project-atlas` with a mocked LLM in CI. One live run per provider type, signed off by hand. |
| **4. Findings, Ask, Compare** | L | Findings explorer, chat/search, run diff, domain compare. | Keyboard-only walkthrough. Compare numbers match `dd-agents diff --json` and `portfolio compare` on the same fixtures. |
| **5. Agents and Prompts** | M | Editor, preview, validate, profile picker. | Saved files pass `agents validate`. Preview equals `agents preview` output byte for byte. Safety floor present and uneditable. |
| **6. Ship** | M | Signing, notarization, updater, beta channel, Homebrew cask, winget, user guide, a11y audit. | Update from build N to N+1 works on both OSes, including with a CLI pin change. Tag-triggered `desktop.yml` publishes signed artifacts. Docs updated in the same PR (CLAUDE.md map row, `docs/user-guide/`). |

Repo layout (proposed): `desktop/` for Tauri and the UI, `src/dd_agents/api/` for the server, `.github/workflows/desktop.yml` triggered by the same version tag as `release.yml`.

## Manual checks that need hardware

CI cannot do these. Run each on a clean machine and report pass or fail.

| Check | Steps | Pass when |
|-------|-------|-----------|
| Clean macOS user account (S1) | Create a new standard user. Install from the DMG. Open the app. Add a data room, run a Quick scan. | Gatekeeper opens the app without a warning. The first-run download of `claude` works. The scan finishes. |
| Folder permissions (S3) | On a clean macOS and Windows user, pick a data room in Documents, Desktop and an external drive. | The OS prompt names "Due Diligence Agents", not another process. After allowing, the scan reads every file. |
| Clickable prototype (S6) | Show the app to 5 people who do deal reviews. Ask each to start a review and find the riskiest finding, without help. | Note where each person hesitates. Fix what 2 or more people hit. |

## Sources

- [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- [Claude Agent SDK overview (branding, terms)](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Code setup: release channels, binary integrity](https://code.claude.com/docs/en/setup)
- [Claude Agent SDK troubleshooting (bundled CLI, Windows)](https://code.claude.com/docs/en/agent-sdk/troubleshooting)
- [Tauri: embedding external binaries](https://v2.tauri.app/develop/sidecar/)
- [Tauri updater plugin](https://v2.tauri.app/plugin/updater/)
- [Microsoft Learn: Artifact Signing quickstart](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart), [FAQ](https://learn.microsoft.com/en-us/azure/artifact-signing/faq)
- [Microsoft Learn: code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options), [SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- [SignPath Foundation conditions](https://signpath.org/terms)
- Tauri distribution: [Windows signing](https://v2.tauri.app/distribute/sign/windows/), [macOS signing](https://v2.tauri.app/distribute/sign/macos/), [Microsoft Store](https://v2.tauri.app/distribute/microsoft-store/), [Windows installer](https://v2.tauri.app/distribute/windows-installer/)
- Owner's release pipelines (reference implementations): [web-researcher-mcp](https://github.com/zoharbabin/web-researcher-mcp) (`docs/RELEASE_SIGNING.md`, `scripts/sign-windows.sh`, `.goreleaser.yml`) and [fen](https://github.com/zoharbabin/fen) (`.github/workflows/release.yml`)
- [Cline issue 14221 (Windows child processes)](https://github.com/cline/cline/issues/14221)
- [Snapmaker Studio (Tauri + Python sidecar)](https://github.com/DVOpenLabs/snapmaker-studio)
- [Homebrew acceptable casks](https://docs.brew.sh/Acceptable-Casks)
- [Harvey blog](https://www.harvey.ai/blog), [Legora blog](https://legora.com/blog) (review-table pattern)
- [Indie Windows signing costs (Oct 2026)](https://sundrymill.com/blog/windows-protected-your-pc-code-signing-cost)
- [Fluxzy: Electron to Tauri after five months](https://www.fluxzy.io/resources/blogs/electron-to-tauri-migration-fluxzy-desktop)
- [Voicebox changelog (Tauri + Python sidecar in production)](https://github.com/jamiepine/voicebox/blob/main/CHANGELOG.md)
- [Tauri + FastAPI + PyInstaller worked example](https://aiechoes.substack.com/p/building-production-ready-desktop)
