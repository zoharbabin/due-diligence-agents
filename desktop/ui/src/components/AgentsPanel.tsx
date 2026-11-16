import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AgentDetail, AgentRow, ConfigIssue, Profile } from '../api/types'
import { useLoad } from '../lib/useApi'
import { Banner, Button, Card, Spinner } from './ui'

const STARTER = `## Additional Focus Areas

- 

## Additional Instructions

`

/** Pick one agent, see what it does, and change how it works for this project. */
export function AgentsPanel({ slug }: { slug: string }) {
  const rows = useLoad(() => api<AgentRow[]>(`/projects/${slug}/agents`), `agents-${slug}`)
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? rows.data?.[0]?.name ?? null

  if (rows.loading && !rows.data) return <Spinner />
  if (rows.error || !rows.data) return <Banner tone="error">{rows.error ?? 'Agents could not be loaded'}</Banner>

  return (
    <div className="grid grid-cols-[14rem_1fr] gap-4">
      <ul aria-label="Agents" className="space-y-1">
        {rows.data.map((a) => (
          <li key={a.name}>
            <button
              type="button"
              aria-current={a.name === current}
              onClick={() => setSelected(a.name)}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm ${a.name === current ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-700 hover:bg-slate-100'}`}
            >
              <span>{a.display_name}</span>
              {a.has_override && <span className="rounded bg-indigo-100 px-1.5 text-xs text-indigo-700">Customized</span>}
            </button>
          </li>
        ))}
      </ul>
      {current && <AgentEditor key={current} slug={slug} name={current} onChanged={rows.reload} />}
    </div>
  )
}

function AgentEditor({ slug, name, onChanged }: { slug: string; name: string; onChanged: () => void }) {
  const detail = useLoad(() => api<AgentDetail>(`/projects/${slug}/agents/${name}`), `agent-${slug}-${name}`)
  const profiles = useLoad(() => api<Profile[]>('/profiles'), 'profiles')
  const [draft, setDraft] = useState<string | null>(null)
  const [issues, setIssues] = useState<ConfigIssue[]>([])
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null)
  const [prompt, setPrompt] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const saved = detail.data?.override ?? ''
  const text = draft ?? saved
  const setText = setDraft

  async function act(run: () => Promise<string>) {
    setBusy(true)
    setIssues([])
    setMessage(null)
    try {
      setMessage({ tone: 'success', text: await run() })
      setPrompt(null)
      detail.reload()
      onChanged()
    } catch (err) {
      if (err instanceof ApiError) {
        setIssues(err.issues)
        setMessage({ tone: 'error', text: err.message })
      } else setMessage({ tone: 'error', text: String(err) })
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    act(async () => {
      await api(`/projects/${slug}/agents/${name}`, { method: 'PUT', json: { content: text } })
      return 'Saved. The next review uses it.'
    })
  const revert = () =>
    act(async () => {
      await api(`/projects/${slug}/agents/${name}`, { method: 'DELETE' })
      setDraft('')
      return 'Back to the built-in agent.'
    })

  async function showPrompt() {
    setBusy(true)
    setMessage(null)
    try {
      setPrompt((await api<{ prompt: string }>(`/projects/${slug}/agents/${name}/preview`)).prompt)
    } catch (err) {
      setMessage({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  if (detail.loading && !detail.data) return <Spinner />
  if (detail.error || !detail.data) return <Banner tone="error">{detail.error ?? 'Agent not found'}</Banner>
  const dirty = text !== saved

  return (
    <Card className="space-y-4">
      <details>
        <summary className="cursor-pointer text-sm font-medium text-slate-700">What this agent does</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
          {detail.data.description}
        </pre>
      </details>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="override" className="text-sm font-medium text-slate-700">
            Your changes for this project
          </label>
          <select
            aria-label="Start from"
            value=""
            onChange={(e) => {
              const profile = profiles.data?.find((p) => p.name === e.target.value)
              setText(profile ? profile.content : STARTER)
            }}
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">Start from...</option>
            <option value="__blank">A blank template</option>
            {profiles.data?.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <textarea
          id="override"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          placeholder="Empty means the built-in agent runs unchanged."
          className="h-72 w-full rounded-lg border border-slate-300 p-3 font-mono text-xs"
        />
        <p className="text-xs text-slate-500">
          Allowed sections: Persona (replaces default), Additional Focus Areas, Additional Instructions, Severity Overrides.
          The safety rules always apply and cannot be removed.
        </p>
      </div>

      {message && <Banner tone={message.tone}>{message.text}</Banner>}
      {issues.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-800">
          {issues.map((i, n) => (
            <li key={n}>{i.msg}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button busy={busy} disabled={!dirty || text.trim() === ''} onClick={save}>
          Save
        </Button>
        <Button variant="secondary" busy={busy} onClick={showPrompt} disabled={dirty}>
          Preview prompt
        </Button>
        {detail.data.override !== null && (
          <Button variant="ghost" busy={busy} onClick={revert}>
            Use built-in agent
          </Button>
        )}
      </div>
      {dirty && <p className="text-xs text-slate-500">Save to preview the prompt with your changes.</p>}

      {prompt !== null && (
        <pre aria-label="Assembled prompt" className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
          {prompt}
        </pre>
      )}
    </Card>
  )
}
