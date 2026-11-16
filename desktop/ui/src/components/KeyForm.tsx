import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { isDesktop, saveProviderEnv } from '../lib/native'
import { testConnection, type ProbeResult } from '../lib/connection'
import { Banner, Button, Field } from './ui'

/** Paste an Anthropic API key. It goes to the service memory and the OS keychain, then gets tested. */
export function KeyForm({ onSaved }: { onSaved?: (result: ProbeResult) => void }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ProbeResult | null>(null)

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const values = { ANTHROPIC_API_KEY: key.trim() }
      await api('/settings/env', { method: 'PUT', json: { values } })
      await saveProviderEnv(values)
      setKey('')
      const outcome = await testConnection()
      setResult(outcome)
      onSaved?.(outcome)
    } catch (err) {
      setResult({ ok: false, text: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-slate-600">Paste your Anthropic API key. It is kept in your system keychain, not in a file.</p>
      <Field label="API key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
      <Button type="submit" busy={busy} disabled={key.trim().length < 8}>
        Save and test
      </Button>
      {!isDesktop() && <p className="text-xs text-slate-500">In a browser the key lasts until the service stops.</p>}
      {result && <Banner tone={result.ok ? 'success' : 'error'}>{result.text}</Banner>}
    </form>
  )
}
