import type { RunProgress } from '../lib/progress'
import { percent } from '../lib/progress'
import { formatDuration, formatUsd } from '../lib/format'
import { Banner, Button, Card } from './ui'

export function RunPanel({ progress, onCancel, cancelling }: { progress: RunProgress; onCancel: () => void; cancelling: boolean }) {
  const pct = percent(progress)
  const agents = Object.values(progress.agents)
  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-semibold text-slate-900">Review in progress</h2>
          <p className="text-sm text-slate-600" aria-live="polite">
            {progress.stepName || 'Starting…'}
            {progress.etaMs ? ` · about ${formatDuration(progress.etaMs)} left` : ''}
          </p>
        </div>
        <Button variant="secondary" onClick={onCancel} busy={cancelling}>
          Cancel
        </Button>
      </div>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Run progress"
        className="h-2 overflow-hidden rounded-full bg-slate-100"
      >
        <div className="h-full bg-indigo-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-slate-500">
        {pct}% · {formatUsd(progress.costUsd)} so far
      </p>
      {agents.length > 0 && (
        <ul className="space-y-1.5">
          {agents.map((a) => (
            <li key={a.name} className="flex items-center justify-between text-sm">
              <span className="capitalize text-slate-700">{a.name.replace(/_/g, ' ')}</span>
              <span className="text-slate-500">
                {a.status === 'failed' ? 'Failed' : a.status === 'done' ? 'Done' : `${a.done}/${a.total || '?'}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {progress.error && <Banner tone="error">{progress.error}</Banner>}
    </Card>
  )
}
