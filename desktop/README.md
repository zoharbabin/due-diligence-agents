# Desktop app

Tauri shell + React UI over the local API (`dd-agents serve`). User guide: [`docs/user-guide/desktop-app.md`](../docs/user-guide/desktop-app.md). Design and open work: [`docs/research/desktop-app-plan.md`](../docs/research/desktop-app-plan.md).

## UI dev

```bash
cd desktop/ui && npm ci
npm test            # unit tests
npm run e2e         # real API + fake pipeline + Chromium (needs: pip install -e ".[dev]", npx playwright install chromium; run `npm run build` first, E2E serves dist/)
npm run build       # -> dist/, served by `dd-agents serve --ui-dir desktop/ui/dist`
```

## Shell dev

```bash
cd desktop/src-tauri
export DD_DESKTOP_PYTHON="$(which python)" DD_DESKTOP_UI="$PWD/../ui/dist"
cargo test --locked                                  # includes a test against the real server
cargo clippy --locked --all-targets -- -D warnings
```

Debug builds create empty stand-ins for the bundle resources (`build.rs`). Release builds fail if they are missing.

## Build an installer

```bash
python desktop/scripts/build_runtime.py              # python-build-standalone + dd-agents -> src-tauri/resources/
(cd desktop/ui && npm run build)
cd desktop/src-tauri && ../ui/node_modules/.bin/tauri build --bundles app,dmg   # macOS
cd desktop/src-tauri && ../ui/node_modules/.bin/tauri build --bundles nsis      # Windows
```

CI does this in [`.github/workflows/desktop.yml`](../.github/workflows/desktop.yml). Runtime pins: `runtime-pins.json`. Signing: `scripts/sign_macos.py`, `scripts/sign_windows.py`. The bundle version is set at build time by `scripts/tauri_override.py`.

## Layout

| Path | Purpose |
|------|---------|
| `ui/src/api/` | Fetch client (bearer token), SSE reader |
| `ui/src/lib/progress.ts` | Reducer: run events to progress state |
| `ui/src/pages/`, `ui/src/components/` | Screens and shared parts |
| `src-tauri/src/sidecar.rs` | Starts `dd-agents serve`, reads the port, stops the process tree |
| `src-tauri/src/secrets.rs` | Provider keys in the OS keychain, passed to the server as env |
| `scripts/` | Runtime build, signing helpers, version override |
| `e2e/` | Test harness only: serves the real API with a fake pipeline. Not shipped |
