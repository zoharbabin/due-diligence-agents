# Desktop app

Tauri shell + React UI over the local API (`dd-agents serve`). Design: [`docs/research/desktop-app-plan.md`](../docs/research/desktop-app-plan.md).

## UI dev

```bash
cd desktop/ui && npm ci
npm test            # unit tests
npm run e2e         # real API + fake pipeline + Chromium (needs: pip install -e ".[dev]", npx playwright install chromium)
npm run build       # -> dist/, served by `dd-agents serve --ui-dir desktop/ui/dist`
```

## Layout

| Path | Purpose |
|------|---------|
| `ui/src/api/` | Fetch client (bearer token), SSE reader |
| `ui/src/lib/progress.ts` | Reducer: run events to progress state |
| `ui/src/pages/`, `ui/src/components/` | Screens and shared parts |
| `e2e/` | Test harness only: serves the real API with a fake pipeline. Not shipped |
