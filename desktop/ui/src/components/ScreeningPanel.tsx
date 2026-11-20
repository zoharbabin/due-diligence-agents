import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ListUpdateResult, ScreeningLists, ScreeningReport } from '../api/types'
import { useLoad } from '../lib/useApi'
import { Banner, Button, Card, Field, Spinner } from './ui'

const LIST_LABEL: Record<string, string> = {
  ofac_sdn: 'US OFAC SDN list',
  us_csl: 'US Consolidated Screening List (without the SDN)',
  uk: 'UK sanctions list',
  eu: 'EU consolidated list',
}
const listLabel = (id: string) => LIST_LABEL[id] ?? id

const STATUS_STYLE: Record<string, string> = {
  screened: 'bg-emerald-100 text-emerald-800',
  stale: 'bg-amber-100 text-amber-800',
  missing: 'bg-red-100 text-red-800',
  failed: 'bg-red-100 text-red-800',
}

const BAND_LABEL: Record<string, string> = { exact: 'Exact', strong: 'Strong', possible: 'Possible' }

/** Sanctions lists: keep them fresh and check one name. A result is never a clearance. */
export function ScreeningPanel({ slug }: { slug: string }) {
  const lists = useLoad(() => api<ScreeningLists>('/screening'), 'screening-lists')
  const [updating, setUpdating] = useState(false)
  const [failures, setFailures] = useState<ListUpdateResult[]>([])
  const [updateError, setUpdateError] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [kind, setKind] = useState<'person' | 'organization'>('organization')
  const [year, setYear] = useState('')
  const [country, setCountry] = useState('')
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [report, setReport] = useState<ScreeningReport | null>(null)
  const [checked, setChecked] = useState('')

  async function update() {
    setUpdating(true)
    setUpdateError(null)
    setFailures([])
    try {
      const res = await api<{ results: ListUpdateResult[] }>('/screening/update', { method: 'POST', json: {} })
      setFailures(res.results.filter((r) => !r.ok))
      lists.reload()
    } catch (e) {
      setUpdateError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setUpdating(false)
    }
  }

  const yearNumber = year.trim() ? Number(year) : null
  const yearError = yearNumber !== null && !(Number.isInteger(yearNumber) && yearNumber >= 1800 && yearNumber <= 2200) ? 'Enter a 4-digit year' : undefined

  async function check() {
    const party = name.trim()
    if (!party || yearError || checking) return
    setChecking(true)
    setCheckError(null)
    try {
      const body = { name: party, kind, birth_year: yearNumber, country: country.trim() || null }
      setReport(await api<ScreeningReport>(`/projects/${slug}/screening/check`, { method: 'POST', json: body }))
      setChecked(party)
    } catch (e) {
      setReport(null)
      setCheckError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }

  const hits = report?.results[0]?.hits ?? []

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Sanctions lists</h2>
            <p className="text-sm text-slate-600">
              Official lists are stored on this computer. Lists older than {lists.data?.max_age_days ?? 7} days count as stale.
            </p>
          </div>
          <Button variant="secondary" busy={updating} onClick={() => void update()}>
            Update lists
          </Button>
        </div>
        {updateError && <Banner tone="error">{updateError}</Banner>}
        {failures.map((f) => (
          <Banner key={f.source} tone="error">
            {listLabel(f.source)} was not updated: {f.error}
          </Banner>
        ))}
        {lists.error && <Banner tone="error">{lists.error}</Banner>}
        {!lists.data && !lists.error && <Spinner />}
        {lists.data && (
          <table className="w-full text-sm">
            <caption className="sr-only">Sanctions list coverage</caption>
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1 font-medium">List</th>
                <th className="py-1 font-medium">Status</th>
                <th className="py-1 text-right font-medium">Entries</th>
                <th className="py-1 text-right font-medium">List date</th>
              </tr>
            </thead>
            <tbody>
              {lists.data.sources.map((s) => (
                <tr key={s.source} className="border-t border-slate-100">
                  <td className="py-1.5 text-slate-900">{listLabel(s.source)}</td>
                  <td className="py-1.5">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_STYLE[s.status] ?? ''}`}>{s.status}</span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-slate-700">{s.entry_count || '-'}</td>
                  <td className="py-1.5 text-right text-slate-700">{s.list_date || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card className="space-y-3">
        <h2 className="text-base font-semibold text-slate-900">Check a name</h2>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            void check()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" value={name} maxLength={300} onChange={(e) => setName(e.target.value)} />
            <div>
              <label htmlFor="screen-kind" className="mb-1 block text-sm font-medium text-slate-700">
                Type
              </label>
              <select
                id="screen-kind"
                value={kind}
                onChange={(e) => setKind(e.target.value as 'person' | 'organization')}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="organization">Company</option>
                <option value="person">Person</option>
              </select>
            </div>
            <Field label="Birth year (optional)" value={year} inputMode="numeric" error={yearError} onChange={(e) => setYear(e.target.value)} />
            <Field label="Country (optional)" value={country} maxLength={100} onChange={(e) => setCountry(e.target.value)} />
          </div>
          <Button type="submit" busy={checking} disabled={!name.trim() || Boolean(yearError)}>
            Check
          </Button>
        </form>

        {checkError && <Banner tone="error">{checkError}</Banner>}

        {report && (
          <div className="space-y-3" aria-label="Screening result">
            {hits.length === 0 ? (
              <p className="text-sm text-slate-800">
                No possible match for <strong>{checked}</strong> in the lists above. This is not a clearance.
              </p>
            ) : (
              <>
                <p className="text-sm text-slate-800">
                  {hits.length} possible {hits.length === 1 ? 'match' : 'matches'} for <strong>{checked}</strong>. A person must review each one.
                </p>
                <table className="w-full text-sm">
                  <caption className="sr-only">Possible matches</caption>
                  <thead className="text-left text-xs text-slate-500">
                    <tr>
                      <th className="py-1 font-medium">Match</th>
                      <th className="py-1 text-right font-medium">Score</th>
                      <th className="py-1 font-medium">List</th>
                      <th className="py-1 font-medium">Listed name</th>
                      <th className="py-1 font-medium">Programs</th>
                      <th className="py-1 font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hits.map((h, i) => (
                      <tr key={i} className="border-t border-slate-100 align-top">
                        <td className="py-1.5 font-medium text-slate-900">{BAND_LABEL[h.band] ?? h.band}</td>
                        <td className="py-1.5 text-right tabular-nums">{Math.round(h.score)}</td>
                        <td className="py-1.5">{listLabel(h.entry.source)}</td>
                        <td className="py-1.5">{h.matched_name}</td>
                        <td className="py-1.5">{h.entry.programs.join(', ') || '-'}</td>
                        <td className="py-1.5">{h.corroboration.join(', ') || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {report.gaps.length > 0 && (
              <Banner tone="info">
                <p className="font-medium">Not every list was fully searched:</p>
                <ul className="mt-1 list-disc pl-5">
                  {report.gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </Banner>
            )}
            {report.user_errors.length > 0 && (
              <Banner tone="error">
                <ul className="list-disc pl-5">
                  {report.user_errors.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </Banner>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
