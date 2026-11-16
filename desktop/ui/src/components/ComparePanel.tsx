import { useState } from 'react'
import { api } from '../api/client'
import type { ChangeType, RunChange, RunDiff, RunSummary } from '../api/types'
import { runLabel } from '../lib/format'
import { useLoad } from '../lib/useApi'
import { Banner, Card, SeverityBadge, Spinner } from './ui'

const GROUPS: { type: ChangeType; title: string; empty: string }[] = [
  { type: 'new_finding', title: 'New findings', empty: 'No new findings.' },
  { type: 'resolved_finding', title: 'Resolved findings', empty: 'No findings were resolved.' },
  { type: 'changed_severity', title: 'Severity changed', empty: 'No severity changes.' },
  { type: 'new_subject', title: 'New entities', empty: 'No new entities.' },
  { type: 'removed_subject', title: 'Removed entities', empty: 'No entities were removed.' },
  { type: 'new_gap', title: 'New gaps', empty: 'No new gaps.' },
  { type: 'resolved_gap', title: 'Resolved gaps', empty: 'No gaps were closed.' },
]

/** What changed between two reviews of the same data room. */
export function ComparePanel({ slug, runs }: { slug: string; runs: RunSummary[] }) {
  const options = runs.filter((r) => r.has_findings)
  // A choice of null means "the default". Defaults follow the list, which grows when a run finishes.
  const [pickedCurrent, setCurrent] = useState<string | null>(null)
  const [pickedPrior, setPrior] = useState<string | null>(null)
  const current = pickedCurrent ?? options[0]?.run_id ?? ''
  const prior = pickedPrior ?? options[1]?.run_id ?? ''
  const diff = useLoad(
    () => (current && prior ? api<RunDiff>(`/projects/${slug}/compare?current=${current}&prior=${prior}`) : Promise.resolve(null)),
    `cmp-${slug}-${current}-${prior}`,
  )

  if (options.length < 2)
    return <p className="text-sm text-slate-500">Run a second review to see what changed since the first one.</p>

  const select = (label: string, value: string, set: (v: string) => void) => (
    <label className="flex items-center gap-2 text-sm text-slate-700">
      {label}
      <select value={value} onChange={(e) => set(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm">
        {options.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {runLabel(r.run_id)}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-4">
        {select('Newer review', current, setCurrent)}
        {select('Older review', prior, setPrior)}
      </Card>
      {current === prior && <Banner tone="info">Pick two different reviews.</Banner>}
      {diff.loading && !diff.data && <Spinner />}
      {diff.error && <Banner tone="error">{diff.error}</Banner>}
      {diff.data && current !== prior && (
        <div className="space-y-4">
          {GROUPS.map((g) => (
            <ChangeGroup key={g.type} title={g.title} empty={g.empty} items={diff.data!.changes.filter((c) => c.change_type === g.type)} />
          ))}
        </div>
      )}
    </div>
  )
}

function ChangeGroup({ title, empty, items }: { title: string; empty: string; items: RunChange[] }) {
  return (
    <Card className="space-y-2">
      <h2 className="font-semibold text-slate-900">
        {title} <span className="font-normal text-slate-500">({items.length})</span>
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((c, i) => (
            <li key={i} className="flex items-center gap-3 py-2 text-sm">
              <span className="flex w-24 shrink-0 items-center gap-1">
                {c.prior_severity && <SeverityBadge severity={c.prior_severity} />}
                {c.prior_severity && c.current_severity && <span aria-label="became">to</span>}
                {c.current_severity && <SeverityBadge severity={c.current_severity} />}
              </span>
              <span className="font-medium text-slate-900">{c.subject}</span>
              {c.finding_summary && <span className="text-slate-600">{c.finding_summary}</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
