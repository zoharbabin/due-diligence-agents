import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ConfigValidation, DealConfig } from '../api/types'
import { Banner, Button, Card } from './ui'

/** Edits the deal config as JSON. Validates against the server rules while typing. */
export function ConfigEditor({ slug, initial, onSaved }: { slug: string; initial: DealConfig; onSaved: () => void }) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2))
  const [check, setCheck] = useState<ConfigValidation | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const parsed = useMemo<{ value?: unknown; syntax: string | null }>(() => {
    try {
      return { value: JSON.parse(text), syntax: null }
    } catch (e) {
      return { syntax: e instanceof Error ? e.message : 'Invalid JSON' }
    }
  }, [text])
  const syntax = parsed.syntax

  useEffect(() => {
    if (parsed.syntax) return
    let live = true
    const t = setTimeout(() => {
      api<ConfigValidation>('/config/validate', { method: 'POST', json: parsed.value }).then(
        (r) => live && setCheck(r),
        () => undefined,
      )
    }, 400)
    return () => {
      live = false
      clearTimeout(t)
    }
  }, [parsed])

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api(`/projects/${slug}/config`, { method: 'PUT', json: JSON.parse(text) })
      setSaved(true)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? [e.message, ...e.issues.map((i) => `${i.loc}: ${i.msg}`)].join('\n') : String(e))
    } finally {
      setSaving(false)
    }
  }

  const issues = !syntax && check && !check.valid ? check.errors : []
  return (
    <Card className="space-y-3">
      <label htmlFor="cfg" className="block text-sm font-medium text-slate-700">
        Deal configuration
      </label>
      <textarea
        id="cfg"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setSaved(false)
        }}
        spellCheck={false}
        className="h-96 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs"
      />
      {syntax && <Banner tone="error">{syntax}</Banner>}
      {issues.length > 0 && (
        <Banner tone="error">
          <ul className="list-disc pl-4">
            {issues.map((i, n) => (
              <li key={n}>
                {i.loc}: {i.msg}
              </li>
            ))}
          </ul>
        </Banner>
      )}
      {error && <Banner tone="error">{error}</Banner>}
      {saved && <Banner tone="success">Saved.</Banner>}
      <Button onClick={save} busy={saving} disabled={Boolean(syntax) || issues.length > 0}>
        Save
      </Button>
    </Card>
  )
}
