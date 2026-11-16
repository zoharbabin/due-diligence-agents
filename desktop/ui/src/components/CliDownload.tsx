import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CliInstall } from '../api/types'
import { formatBytes } from '../lib/format'
import { Banner, Button, Card } from './ui'

const POLL_MS = 500

/** First run: downloads the Claude engine the app needs. The user starts it, then sees progress. */
export function CliDownload({ onDone }: { onDone: () => void }) {
  const [install, setInstall] = useState<CliInstall | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const active = install?.state === 'downloading'

  async function start() {
    setFailure(null)
    try {
      setInstall(await api<CliInstall>('/cli/install', { method: 'POST' }))
    } catch (err) {
      setFailure(err instanceof ApiError ? err.message : String(err))
    }
  }

  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => {
      api<CliInstall>('/cli/install')
        .then(setInstall)
        .catch((err: unknown) => setFailure(err instanceof ApiError ? err.message : String(err)))
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [active])

  useEffect(() => {
    if (install?.state === 'done') onDone()
  }, [install?.state, onDone])

  const percent = install?.total ? Math.min(100, Math.round((install.done / install.total) * 100)) : null
  const error = failure ?? (install?.state === 'error' ? install.error : null)

  return (
    <Card className="space-y-3">
      <h2 className="font-semibold text-slate-900">Download the Claude engine</h2>
      <p className="text-sm text-slate-600">
        The app needs Anthropic's Claude command line tool to run reviews. It is a one-time download of about 160 MB. It is
        checked against a fixed digest before it is used.
      </p>
      {active && (
        <div className="space-y-1">
          <div
            role="progressbar"
            aria-label="Download progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? undefined}
            className="h-2 overflow-hidden rounded bg-slate-200"
          >
            <div className="h-full bg-blue-600 transition-all" style={{ width: `${percent ?? 5}%` }} />
          </div>
          <p className="text-xs text-slate-500">
            {formatBytes(install.done)}
            {install.total ? ` of ${formatBytes(install.total)}` : ''}
          </p>
        </div>
      )}
      {error && <Banner tone="error">{error}</Banner>}
      {!active && (
        <Button onClick={start}>{error ? 'Try again' : 'Download'}</Button>
      )}
    </Card>
  )
}
