import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { SEVERITIES, type Finding, type FindingsPage, type Severity } from '../api/types'
import { Banner, SeverityBadge, Spinner } from './ui'
import { categoryLabel } from '../lib/format'

const PAGE = 25

export function FindingsTable({ slug, runId }: { slug: string; runId: string }) {
  const [severity, setSeverity] = useState<Severity | ''>('')
  const [agent, setAgent] = useState('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<FindingsPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q)
      setOffset(0)
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    let live = true
    const params = new URLSearchParams({ run_id: runId, limit: String(PAGE), offset: String(offset) })
    if (severity) params.set('severity', severity)
    if (agent) params.set('agent', agent)
    if (debouncedQ) params.set('q', debouncedQ)
    api<FindingsPage>(`/projects/${slug}/findings?${params}`).then(
      (p) => {
        if (live) {
          setPage(p)
          setError(null)
        }
      },
      (e: unknown) => live && setError(e instanceof Error ? e.message : String(e)),
    )
    return () => {
      live = false
    }
  }, [slug, runId, severity, agent, debouncedQ, offset])

  if (error) return <Banner tone="error">{error}</Banner>
  if (!page) return <Spinner />

  const agents = Object.keys(page.facets.agent ?? {})
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Search</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Title or text"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Severity</span>
          <select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value as Severity | '')
              setOffset(0)
            }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">All</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s} ({page.facets.severity?.[s] ?? 0})
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Agent</span>
          <select
            value={agent}
            onChange={(e) => {
              setAgent(e.target.value)
              setOffset(0)
            }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">All</option>
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-sm text-slate-500">{page.total.toLocaleString()} findings</span>
      </div>

      {page.items.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">No findings match these filters.</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {page.items.map((f) => (
            <FindingRow key={f.id} finding={f} open={open === f.id} onToggle={() => setOpen(open === f.id ? null : f.id)} />
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between text-sm">
        <button
          type="button"
          className="rounded-lg px-3 py-1.5 text-slate-700 hover:bg-slate-100 disabled:text-slate-300"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          Previous
        </button>
        <span className="text-slate-500">
          {page.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}
        </span>
        <button
          type="button"
          className="rounded-lg px-3 py-1.5 text-slate-700 hover:bg-slate-100 disabled:text-slate-300"
          disabled={offset + PAGE >= page.total}
          onClick={() => setOffset(offset + PAGE)}
        >
          Next
        </button>
      </div>
    </div>
  )
}

function FindingRow({ finding: f, open, onToggle }: { finding: Finding; open: boolean; onToggle: () => void }) {
  return (
    <li>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50">
        <SeverityBadge severity={f.severity} />
        <span className="flex-1">
          <span className="block text-sm font-medium text-slate-900">{f.title}</span>
          <span className="block text-xs text-slate-500">
            {f.subject} · {categoryLabel(f.category)}
          </span>
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <p className="whitespace-pre-wrap">{f.description}</p>
          {f.citations.length > 0 && (
            <ul className="space-y-2">
              {f.citations.map((c, i) => (
                <li key={i} className="rounded-lg border border-slate-200 bg-white p-3">
                  <p className="text-xs font-medium text-slate-500">
                    {c.source_path}
                    {c.page ? ` · p. ${c.page}` : ''}
                  </p>
                  {c.exact_quote && <blockquote className="mt-1 italic">“{c.exact_quote}”</blockquote>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}
