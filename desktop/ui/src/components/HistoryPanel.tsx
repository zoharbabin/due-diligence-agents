import { useState } from 'react'
import { api } from '../api/client'
import type { HistoryPage, InteractionType } from '../api/types'
import { formatDate, formatUsd } from '../lib/format'
import { useLoad } from '../lib/useApi'
import { Banner, Card, SeverityBadge, Spinner } from './ui'

const TYPE_LABEL: Record<InteractionType, string> = {
  pipeline_run: 'Review',
  search: 'Search',
  query: 'Query',
  annotation: 'Note',
  knowledge_compilation: 'Knowledge update',
  chat: 'Ask',
}

const SEVERITIES = ['p0', 'p1', 'p2', 'p3'] as const

/** What was done in this project, newest first. */
export function HistoryPanel({ slug }: { slug: string }) {
  const [type, setType] = useState<InteractionType | ''>('')
  const history = useLoad(
    () => api<HistoryPage>(`/projects/${slug}/history${type ? `?type=${type}` : ''}`),
    `history-${slug}-${type}`,
  )

  if (history.error) return <Banner tone="error">{history.error}</Banner>
  if (!history.data) return <Spinner />
  const page = history.data
  const kinds = Object.keys(page.by_type) as InteractionType[]

  if (page.total === 0 && !type) return <p className="text-sm text-slate-500">Nothing has happened in this project yet.</p>

  return (
    <div className="space-y-4">
      <Card className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          Show
          <select
            value={type}
            onChange={(e) => setType(e.target.value as InteractionType | '')}
            className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">Everything</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {TYPE_LABEL[k] ?? k} ({page.by_type[k]})
              </option>
            ))}
          </select>
        </label>
        <span className="text-sm text-slate-500">
          {page.entries.length < page.total ? `Latest ${page.entries.length} of ${page.total}` : `${page.total} in total`}
        </span>
      </Card>

      <ol aria-label="History" className="space-y-2">
        {page.entries.map((e) => (
          <li key={e.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-slate-100 px-1.5 text-xs font-medium text-slate-700">{TYPE_LABEL[e.interaction_type] ?? e.interaction_type}</span>
              <span className="text-sm font-medium text-slate-900">{e.title}</span>
              <span className="ml-auto text-xs text-slate-500">{formatDate(e.timestamp)}</span>
            </div>
            {(e.findings_summary || e.cost_usd != null || e.entities_affected.length > 0) && (
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                {e.findings_summary && (
                  <>
                    <span>{e.findings_summary.total} findings</span>
                    {SEVERITIES.map((s) => e.findings_summary![s] > 0 && <SeverityBadge key={s} severity={s.toUpperCase() as 'P0'} count={e.findings_summary![s]} />)}
                  </>
                )}
                {e.cost_usd != null && <span>{formatUsd(e.cost_usd)}</span>}
                {e.entities_affected.length > 0 && (
                  <span>
                    {e.entities_affected.slice(0, 3).join(', ')}
                    {e.entities_affected.length > 3 ? ` +${e.entities_affected.length - 3}` : ''}
                  </span>
                )}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
