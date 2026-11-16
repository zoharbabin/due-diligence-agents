import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DealConfig, SuggestState } from '../api/types'
import { Banner, Button, Card, Spinner } from './ui'

const POLL_MS = 1000

/** Asks the model to draft the deal config from the data room. The draft is only loaded into the editor. */
export function SuggestCard({ slug, ready, onDraft }: { slug: string; ready: boolean; onDraft: (config: DealConfig) => void }) {
  const [state, setState] = useState<SuggestState>({ state: 'idle' })
  const [failure, setFailure] = useState<string | null>(null)
  const running = state.state === 'running'

  const fail = (err: unknown) => setFailure(err instanceof ApiError ? err.message : String(err))

  useEffect(() => {
    api<SuggestState>(`/projects/${slug}/config/suggest`).then(setState, fail)
  }, [slug])

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      api<SuggestState>(`/projects/${slug}/config/suggest`).then(setState, fail)
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running, slug])

  const start = useCallback(async () => {
    setFailure(null)
    try {
      await api(`/projects/${slug}/config/suggest`, { method: 'POST' })
      setState({ state: 'running' })
    } catch (err) {
      fail(err)
    }
  }, [slug])

  const error = failure ?? (state.state === 'error' ? state.error : null)

  return (
    <Card className="space-y-3">
      <h2 className="font-semibold text-slate-900">Suggest a setup</h2>
      <p className="text-sm text-slate-600">
        The model reads your folder names and file list and drafts the configuration. You review it before anything is saved. This
        calls the model and costs money.
      </p>
      {!ready && <p className="text-sm text-slate-500">Save the buyer and target names below first.</p>}
      {running && (
        <p className="flex items-center gap-2 text-sm text-slate-700">
          <Spinner /> Reading your data room. This can take a few minutes.
        </p>
      )}
      {error && <Banner tone="error">{error}</Banner>}
      {state.state === 'done' && (
        <Banner tone="success">
          A draft is ready. It is not saved.{' '}
          <button className="font-medium underline" onClick={() => onDraft(state.config)}>
            Review the draft
          </button>
        </Banner>
      )}
      {!running && (
        <Button onClick={start} disabled={!ready}>
          {state.state === 'idle' && !error ? 'Suggest a setup' : 'Suggest again'}
        </Button>
      )}
    </Card>
  )
}
