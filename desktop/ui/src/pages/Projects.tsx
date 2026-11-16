import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { SEVERITIES, type Doctor, type Project } from '../api/types'
import { SetupCard } from '../components/SetupCard'
import { Banner, Button, Card, EmptyState, SeverityBadge, Spinner } from '../components/ui'
import { formatDate } from '../lib/format'
import { useLoad } from '../lib/useApi'

const STATUS_TEXT: Record<Project['status'], string> = {
  created: 'Not run yet',
  running: 'Running',
  completed: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
  archived: 'Archived',
}

export function ProjectsPage() {
  const { data, error, loading } = useLoad(() => api<Project[]>('/projects'), 'projects')
  const doctor = useLoad(() => api<Doctor>('/doctor'), 'doctor')
  if (loading) return <Spinner />
  if (error) return <Banner tone="error">{error}</Banner>
  const projects = data ?? []
  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
        {projects.length > 0 && (
          <Link to="/new">
            <Button>New project</Button>
          </Link>
        )}
      </header>
      {doctor.data && !doctor.data.ready && <SetupCard doctor={doctor.data} onChange={doctor.reload} />}
      {projects.length === 0 ? (
        <EmptyState
          title="Start your first review"
          body="Pick the folder with your contracts. The agents read every document and flag the risks."
          action={
            <Link to="/new">
              <Button>New project</Button>
            </Link>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {projects.map((p) => (
            <li key={p.slug}>
              <Link to={`/p/${p.slug}`} className="block rounded-xl focus-visible:outline-2 focus-visible:outline-indigo-600">
                <Card className="transition-shadow hover:shadow-md">
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="font-semibold text-slate-900">{p.name}</h2>
                    <span className="text-xs text-slate-500">{STATUS_TEXT[p.status]}</span>
                  </div>
                  {p.target && (
                    <p className="mt-1 text-sm text-slate-600">
                      {p.buyer ? `${p.buyer} acquiring ${p.target}` : p.target}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {SEVERITIES.filter((s) => (p.finding_counts[s] ?? 0) > 0).map((s) => (
                      <SeverityBadge key={s} severity={s} count={p.finding_counts[s]} />
                    ))}
                  </div>
                  <p className="mt-3 text-xs text-slate-500">Last run: {formatDate(p.last_run_at)}</p>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
