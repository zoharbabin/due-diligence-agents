import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { Project, ScanSummary } from '../api/types'
import { Banner, Button, Card, Field } from '../components/ui'
import { baseName, formatBytes } from '../lib/format'
import { isDesktop, pickFolder } from '../lib/native'

export function NewProjectPage() {
  const nav = useNavigate()
  const [folder, setFolder] = useState('')
  const [typedName, setTypedName] = useState<string | null>(null)
  const [project, setProject] = useState<Project | null>(null)
  const [scan, setScan] = useState<ScanSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const name = typedName ?? baseName(folder)
  const [buyer, setBuyer] = useState('')
  const [target, setTarget] = useState('')

  async function browse() {
    const picked = await pickFolder()
    if (picked) setFolder(picked)
  }

  async function create(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const p = await api<Project>('/projects', { method: 'POST', json: { name: name.trim(), data_room: folder.trim() } })
      setProject(p)
      setScan(await api<ScanSummary>(`/projects/${p.slug}/scan`))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function saveDeal(e: FormEvent) {
    e.preventDefault()
    if (!project) return
    setBusy(true)
    setError(null)
    try {
      await api(`/projects/${project.slug}/config`, {
        method: 'PUT',
        json: {
          config_version: '1.0.0',
          buyer: { name: buyer.trim() },
          target: { name: target.trim() },
          deal: { type: 'acquisition', focus_areas: ['change_of_control', 'ip_ownership', 'data_privacy'] },
        },
      })
      nav(`/p/${project.slug}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">New project</h1>
      {error && <Banner tone="error">{error}</Banner>}
      {!project ? (
        <Card>
          <form onSubmit={create} className="space-y-4">
            <Field
              label="Data room folder"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder="/Users/you/Deals/Acme"
              hint="The folder with the contracts. Files are only read, never changed."
              required
            />
            {isDesktop() && (
              <Button variant="secondary" onClick={browse}>
                Browse…
              </Button>
            )}
            <Field label="Project name" value={name} onChange={(e) => setTypedName(e.target.value)} required />
            <Button type="submit" busy={busy} disabled={!folder.trim() || !name.trim()}>
              Continue
            </Button>
          </form>
        </Card>
      ) : (
        <Card>
          <form onSubmit={saveDeal} className="space-y-4">
            {scan && (
              <Banner tone="success">
                Found {scan.total_files.toLocaleString()} files ({formatBytes(scan.total_bytes)}){scan.truncated ? ' or more' : ''}.
              </Banner>
            )}
            <Field label="Buyer" value={buyer} onChange={(e) => setBuyer(e.target.value)} required />
            <Field label="Target company" value={target} onChange={(e) => setTarget(e.target.value)} required />
            <p className="text-xs text-slate-500">You can change the deal type and focus areas later in Settings.</p>
            <Button type="submit" busy={busy} disabled={!buyer.trim() || !target.trim()}>
              Create project
            </Button>
          </form>
        </Card>
      )}
    </div>
  )
}
