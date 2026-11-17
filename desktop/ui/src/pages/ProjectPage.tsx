import { useCallback, useEffect, useReducer, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { streamEvents } from '../api/sse'
import { SEVERITIES, type DealConfig, type Project, type RunState, type RunSummary } from '../api/types'
import { AgentsPanel } from '../components/AgentsPanel'
import { AskPanel } from '../components/AskPanel'
import { ComparePanel } from '../components/ComparePanel'
import { ConfigEditor } from '../components/ConfigEditor'
import { SuggestCard } from '../components/SuggestCard'
import { FindingsTable } from '../components/FindingsTable'
import { HistoryPanel } from '../components/HistoryPanel'
import { ScreeningPanel } from '../components/ScreeningPanel'
import { ReportFrame } from '../components/ReportFrame'
import { RunPanel } from '../components/RunPanel'
import { Banner, Button, Card, SeverityBadge, Spinner, Tabs } from '../components/ui'
import { formatDate, riskLabel } from '../lib/format'
import { initialProgress, reduceEvent } from '../lib/progress'
import { useLoad } from '../lib/useApi'

/** The terminal event can arrive before the process exits and the registry is updated. */
async function settled(slug: string, signal: AbortSignal): Promise<void> {
  for (let i = 0; i < 40 && !signal.aborted; i++) {
    const s = await api<RunState>(`/projects/${slug}/run`).catch(() => null)
    if (!s || s.status !== 'running') return
    await new Promise((r) => setTimeout(r, 500))
  }
}

type Tab = 'overview' | 'findings' | 'report' | 'ask' | 'agents' | 'compare' | 'history' | 'screening' | 'settings'

export function ProjectPage() {
  const { slug = '' } = useParams()
  const nav = useNavigate()
  const project = useLoad(() => api<Project>(`/projects/${slug}`), `p:${slug}`)
  const runs = useLoad(() => api<RunSummary[]>(`/projects/${slug}/runs`), `r:${slug}`)
  const config = useLoad(
    () => api<DealConfig>(`/projects/${slug}/config`).catch((e: unknown) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e))),
    `c:${slug}`,
  )
  const [tab, setTab] = useState<Tab>('overview')
  const [progress, dispatch] = useReducer(reduceEvent, initialProgress)
  const [running, setRunning] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [draft, setDraft] = useState<{ config: DealConfig; n: number } | null>(null)
  const [draftOpen, setDraftOpen] = useState(false)
  // Show the spinner for the first load only, so a reload after Save does not rebuild the editor.
  const [configSeen, setConfigSeen] = useState(false)
  useEffect(() => {
    if (!config.loading) setConfigSeen(true)
  }, [config.loading])

  const refresh = useCallback(() => {
    project.reload()
    runs.reload()
  }, [project, runs])

  // Follow the run while it is active. Also picks up a run that started before this page opened.
  useEffect(() => {
    let live = true
    const ctl = new AbortController()
    api<RunState>(`/projects/${slug}/run`).then((s) => {
      if (!live || s.status !== 'running') return
      setRunning(true)
      streamEvents(slug, (e) => dispatch(e), ctl.signal)
        .then(() => settled(slug, ctl.signal))
        .finally(() => {
          if (!live) return
          setRunning(false)
          setCancelling(false)
          refresh()
        })
    }, () => undefined)
    return () => {
      live = false
      ctl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, starting])

  async function start(quick: boolean) {
    setError(null)
    try {
      await api(`/projects/${slug}/run`, { method: 'POST', json: { quick_scan: quick } })
      setStarting((s) => !s)
    } catch (e) {
      setError(e instanceof ApiError ? [e.message, ...e.issues.map((i) => `${i.loc}: ${i.msg}`)].join('\n') : String(e))
    }
  }

  async function cancel() {
    setCancelling(true)
    try {
      await api(`/projects/${slug}/run/cancel`, { method: 'POST' })
    } catch (e) {
      setCancelling(false)
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function remove() {
    if (!window.confirm('Remove this project from the list? Your data room files are not touched.')) return
    await api(`/projects/${slug}`, { method: 'DELETE' })
    nav('/')
  }

  if (project.loading && !project.data) return <Spinner />
  if (project.error || !project.data) return <Banner tone="error">{project.error ?? 'Project not found'}</Banner>
  const p = project.data
  const latest = runs.data?.find((r) => r.has_findings)
  const needsConfig = config.data === null && !config.loading

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{p.name}</h1>
          <p className="text-sm text-slate-600">{p.path}</p>
        </div>
        <Button variant="ghost" onClick={remove}>
          Remove
        </Button>
      </header>

      <Tabs<Tab>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'findings', label: 'Findings' },
          { id: 'report', label: 'Report' },
          { id: 'ask', label: 'Ask' },
          { id: 'agents', label: 'Agents' },
          { id: 'compare', label: 'Compare' },
          { id: 'history', label: 'History' },
          { id: 'screening', label: 'Screening' },
          { id: 'settings', label: 'Settings' },
        ]}
      />

      {error && <Banner tone="error"><span className="whitespace-pre-wrap">{error}</span></Banner>}

      {tab === 'overview' && (
        <div className="space-y-4">
          {running ? (
            <RunPanel progress={progress} onCancel={cancel} cancelling={cancelling} />
          ) : needsConfig ? (
            <Card className="space-y-3">
              <h2 className="font-semibold text-slate-900">Finish setup</h2>
              <p className="text-sm text-slate-600">Add the buyer and target so the agents know what to look for.</p>
              <Button onClick={() => setTab('settings')}>Open settings</Button>
            </Card>
          ) : (
            <Card className="flex items-center justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-900">{p.total_runs ? 'Run a new review' : 'Ready to review'}</h2>
                <p className="text-sm text-slate-600">Last run: {formatDate(p.last_run_at)}</p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => start(true)}>
                  Quick scan
                </Button>
                <Button onClick={() => start(false)}>Run full review</Button>
              </div>
            </Card>
          )}
          {!running && progress.status === 'failed' && <Banner tone="error">{progress.error ?? 'The run failed. See the log in your data room.'}</Banner>}
          {p.total_findings > 0 && (
            <Card className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-slate-900">Latest results</h2>
                <span className="text-sm text-slate-600">
                  Risk: {p.risk_label || riskLabel(p.risk_score)} ({Math.round(p.risk_score)})
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {SEVERITIES.map((s) => (
                  <SeverityBadge key={s} severity={s} count={p.finding_counts[s] ?? 0} />
                ))}
              </div>
              <Button variant="secondary" onClick={() => setTab('findings')}>
                View findings
              </Button>
            </Card>
          )}
        </div>
      )}

      {tab === 'findings' &&
        (latest ? <FindingsTable slug={slug} runId={latest.run_id} /> : <p className="text-sm text-slate-500">Run a review to see findings here.</p>)}

      {tab === 'report' &&
        (latest?.reports.includes('html') ? (
          <ReportFrame slug={slug} runId={latest.run_id} hasXlsx={latest.reports.includes('xlsx')} />
        ) : (
          <p className="text-sm text-slate-500">The report appears here after a run finishes.</p>
        ))}

      {tab === 'ask' && <AskPanel slug={slug} />}

      {tab === 'agents' && <AgentsPanel slug={slug} />}
      {tab === 'compare' && (runs.data ? <ComparePanel slug={slug} runs={runs.data} /> : <Spinner />)}

      {tab === 'history' && <HistoryPanel slug={slug} />}

      {tab === 'screening' && <ScreeningPanel slug={slug} />}

      {tab === 'settings' &&
        (!configSeen ? (
          <Spinner />
        ) : (
          <div className="space-y-4">
            <SuggestCard slug={slug} ready={Boolean(project.data?.buyer && project.data.target)} onDraft={(c) => {
                setDraft((d) => ({ config: c, n: (d?.n ?? 0) + 1 }))
                setDraftOpen(true)
              }}
            />
            {draftOpen && <Banner tone="info">This is a draft from the model. Check it, then press Save to keep it.</Banner>}
            <ConfigEditor
              key={draft?.n ?? 0}
              slug={slug}
              initial={draft?.config ?? config.data ?? { config_version: '1.0.0', buyer: { name: '' }, target: { name: '' }, deal: { type: 'acquisition', focus_areas: [] } }}
              onSaved={() => {
                setDraftOpen(false)
                config.reload()
                project.reload()
              }}
            />
          </div>
        ))}
    </div>
  )
}
