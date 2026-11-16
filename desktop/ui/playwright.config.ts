import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const PORT = 18765
const registry = mkdtempSync(join(tmpdir(), 'dd-e2e-registry-'))
const python = process.env.DD_PYTHON ?? 'python'

export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  webServer: {
    command: `${python} ../e2e/serve_fake.py ${PORT} dist ${registry}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
