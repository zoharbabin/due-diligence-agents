import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Doctor } from '../api/types'
import { isDesktop, saveProviderEnv } from '../lib/native'
import { Banner, Button, Card, Field } from './ui'

/** Shown until the app can reach a model. Lets the user paste an API key and test it. */
export function SetupCard({ doctor, onChange }: { doctor: Doctor; onChange: () => void }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const values = { ANTHROPIC_API_KEY: key.trim() }
      await api('/settings/env', { method: 'PUT', json: { values } })
      await saveProviderEnv(values)
      setKey('')
      const probe = await api<{ ok: boolean; detail: string }>('/doctor/probe', { method: 'POST' })
      setResult({ ok: probe.ok, text: probe.ok ? 'Connected.' : `The key did not work: ${probe.detail}` })
    } catch (err) {
      setResult({ ok: false, text: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  if (!doctor.cli.found)
    return (
      <Banner tone="error">
        The Claude command line tool was not found. Reopen the app to download it, or install it and restart.
      </Banner>
    )

  return (
    <Card className="space-y-3">
      <h2 className="font-semibold text-slate-900">Connect a model</h2>
      {doctor.provider === 'anthropic' && !result?.ok ? (
        <form onSubmit={save} className="space-y-3">
          <p className="text-sm text-slate-600">Paste your Anthropic API key. It is kept in your system keychain, not in a file.</p>
          <Field label="API key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          <Button type="submit" busy={busy} disabled={key.trim().length < 8}>
            Save and test
          </Button>
          {!isDesktop() && <p className="text-xs text-slate-500">In a browser the key lasts until the service stops.</p>}
        </form>
      ) : (
        <p className="text-sm text-slate-600">
          Provider: <strong>{doctor.provider}</strong>. Set one of {doctor.credential_env.join(', ')} before starting the app.
        </p>
      )}
      {result && <Banner tone={result.ok ? 'success' : 'error'}>{result.text}</Banner>}
      {result?.ok && <Button onClick={onChange}>Continue</Button>}
    </Card>
  )
}
