import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Doctor } from '../api/types'
import { Banner, Button, Card, Spinner } from '../components/ui'
import { KeyForm } from '../components/KeyForm'
import { testConnection, type ProbeResult } from '../lib/connection'
import { providerLabel } from '../lib/format'
import { isDesktop, saveProviderEnv } from '../lib/native'
import { useLoad } from '../lib/useApi'

const ENGINE_SOURCE: Record<string, string> = {
  env: 'Set by DD_AGENTS_CLI_PATH',
  system: 'Found on this computer',
  managed: 'Downloaded by this app',
  sdk: 'Bundled with the Python package',
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium text-slate-900">{children}</dd>
    </div>
  )
}

export function SettingsPage() {
  const doctor = useLoad(() => api<Doctor>('/doctor'), 'doctor')
  const health = useLoad(() => api<{ version: string }>('/health'), 'health')
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  async function run(action: () => Promise<ProbeResult | null>) {
    setBusy(true)
    setFailure(null)
    try {
      setProbe(await action())
      doctor.reload()
    } catch (err) {
      setFailure(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const removeKey = () =>
    run(async () => {
      const values = { ANTHROPIC_API_KEY: '' }
      await api('/settings/env', { method: 'PUT', json: { values } })
      await saveProviderEnv(values)
      return null
    })

  if (doctor.loading && !doctor.data) return <Spinner />
  const d = doctor.data

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
      {doctor.error && <Banner tone="error">{doctor.error}</Banner>}
      {d && (
        <>
          <Card className="space-y-3">
            <h2 className="font-semibold text-slate-900">Model connection</h2>
            <dl className="divide-y divide-slate-100">
              <Row label="Provider">{providerLabel(d.provider)}</Row>
              {d.base_url && <Row label="Address">{d.base_url}</Row>}
              <Row label="Credential">{d.credential_present ? 'Set' : 'Missing'}</Row>
              <Row label="Claude engine">{d.cli.source ? ENGINE_SOURCE[d.cli.source] : 'Not installed'}</Row>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" busy={busy} disabled={!d.ready} onClick={() => run(testConnection)}>
                Test connection
              </Button>
              {d.provider === 'anthropic' && d.credential_present && (
                <Button variant="danger" busy={busy} onClick={removeKey}>
                  Remove key
                </Button>
              )}
            </div>
            {probe && <Banner tone={probe.ok ? 'success' : 'error'}>{probe.text}</Banner>}
            {failure && <Banner tone="error">{failure}</Banner>}
          </Card>
          {d.provider === 'anthropic' ? (
            <Card className="space-y-3">
              <h2 className="font-semibold text-slate-900">{d.credential_present ? 'Replace the API key' : 'Add an API key'}</h2>
              <KeyForm onSaved={() => doctor.reload()} />
            </Card>
          ) : (
            <Banner tone="info">
              This provider is set by environment variables ({d.credential_env.join(', ')}). Change them where you start the app.
            </Banner>
          )}
        </>
      )}
      <Card>
        <h2 className="mb-1 font-semibold text-slate-900">About</h2>
        <dl className="divide-y divide-slate-100">
          <Row label="Version">{health.data?.version ?? '...'}</Row>
          <Row label="Running as">{isDesktop() ? 'Desktop app' : 'Browser'}</Row>
        </dl>
      </Card>
    </div>
  )
}
