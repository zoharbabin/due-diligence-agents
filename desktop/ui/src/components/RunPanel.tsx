import type { RunProgress } from '../lib/progress'
import { percent } from '../lib/progress'
import { agentLabel, formatDuration, formatUsd } from '../lib/format'
import { Banner, Button, Card } from './ui'

/** A time left of a few seconds is noise. Show it only when it helps. */
const MIN_ETA_MS = 10_000

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
            {progress.etaMs && progress.etaMs >= MIN_ETA_MS ? ` · about ${formatDuration(progress.etaMs)} left` : ''}
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
              <span className="text-slate-700">{agentLabel(a.name)}</span>
              <span className="text-slate-500">
                {a.status === 'failed' ? 'Failed' : a.status === 'done' ? 'Done' : `${a.done}/${Math.max(a.total, a.done) || '?'}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {progress.error && <Banner tone="error">{progress.error}</Banner>}
    </Card>
  )
}
