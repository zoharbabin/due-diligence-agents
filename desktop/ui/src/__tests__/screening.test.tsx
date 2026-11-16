import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ScreeningPanel } from '../components/ScreeningPanel'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

const ROW = { detail: '', entry_count: 0, list_date: '' }
const LISTS = {
  max_age_days: 7,
  sources: [
    { ...ROW, source: 'ofac_sdn', status: 'screened', entry_count: 5, list_date: '2026-11-13' },
    { ...ROW, source: 'uk', status: 'stale', entry_count: 4, list_date: '2026-10-01' },
    { ...ROW, source: 'eu', status: 'missing' },
  ],
}
const HIT = {
  matched_name: 'EXAMPLE TRADING',
  score: 92.4,
  band: 'strong',
  entry: { source: 'uk', programs: ['TESTPROG1'] },
  corroboration: ['country agrees'],
}
const report = (hits: unknown[], gaps: string[] = []) => ({
  complete: gaps.length === 0,
  coverage: LISTS.sources,
  results: [{ hits }],
  user_errors: [],
  gaps,
})

function mock(opts: { update?: () => Response; check?: () => Response } = {}) {
  const calls: { method: string; path: string; body?: unknown }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '')
    const method = (init as RequestInit | undefined)?.method ?? 'GET'
    const body = (init as RequestInit | undefined)?.body
    calls.push({ method, path, body: body ? JSON.parse(String(body)) : undefined })
    if (path === '/screening') return json(LISTS)
    if (path === '/screening/update') return opts.update ? opts.update() : json({ results: [] })
    return opts.check ? opts.check() : json(report([]))
  })
  return calls
}

describe('ScreeningPanel', () => {
  it('shows the status of each list', async () => {
    mock()
    render(<ScreeningPanel slug="p" />)
    const table = await screen.findByRole('table', { name: 'Sanctions list coverage' })
    expect(within(table).getByText('US OFAC SDN list')).toBeInTheDocument()
    expect(within(table).getByText('stale')).toBeInTheDocument()
    expect(within(table).getByText('missing')).toBeInTheDocument()
    expect(within(table).getByText('2026-11-13')).toBeInTheDocument()
  })

  it('updates the lists and reloads the table', async () => {
    const calls = mock()
    render(<ScreeningPanel slug="p" />)
    await screen.findByRole('table', { name: 'Sanctions list coverage' })
    await userEvent.click(screen.getByRole('button', { name: 'Update lists' }))
    await vi.waitFor(() => expect(calls.filter((c) => c.path === '/screening')).toHaveLength(2))
    expect(calls.find((c) => c.path === '/screening/update')?.method).toBe('POST')
  })

  it('names a list that failed to update', async () => {
    mock({ update: () => json({ results: [{ source: 'uk', ok: false, error: 'HTTP 503 from server' }, { source: 'eu', ok: true }] }) })
    render(<ScreeningPanel slug="p" />)
    await screen.findByRole('table', { name: 'Sanctions list coverage' })
    await userEvent.click(screen.getByRole('button', { name: 'Update lists' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('UK sanctions list was not updated: HTTP 503 from server')
  })

  it('shows the reason when the update is refused', async () => {
    mock({ update: () => json({ detail: 'A list update is already running' }, 409) })
    render(<ScreeningPanel slug="p" />)
    await screen.findByRole('table', { name: 'Sanctions list coverage' })
    await userEvent.click(screen.getByRole('button', { name: 'Update lists' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A list update is already running')
  })

  it('sends the check and says a miss is not a clearance', async () => {
    const calls = mock()
    render(<ScreeningPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Name'), '  Acme Ltd ')
    await userEvent.selectOptions(screen.getByLabelText('Type'), 'person')
    await userEvent.type(screen.getByLabelText('Birth year (optional)'), '1970')
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText(/This is not a clearance/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/projects/p/screening/check')?.body).toEqual({
      name: 'Acme Ltd',
      kind: 'person',
      birth_year: 1970,
      country: null,
    })
  })

  it('lists possible matches and the coverage gaps', async () => {
    mock({ check: () => json(report([HIT], ['eu: no list stored'])) })
    render(<ScreeningPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Name'), 'Example Trading')
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    const table = await screen.findByRole('table', { name: 'Possible matches' })
    expect(within(table).getByText('EXAMPLE TRADING')).toBeInTheDocument()
    expect(within(table).getByText('Strong')).toBeInTheDocument()
    expect(within(table).getByText('92')).toBeInTheDocument()
    expect(within(table).getByText('TESTPROG1')).toBeInTheDocument()
    expect(screen.getByText('eu: no list stored')).toBeInTheDocument()
    expect(screen.getByText(/A person must review each one/)).toBeInTheDocument()
  })

  it('does not send a blank name or a bad year', async () => {
    const calls = mock()
    render(<ScreeningPanel slug="p" />)
    const check = await screen.findByRole('button', { name: 'Check' })
    expect(check).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Name'), 'A')
    await userEvent.type(screen.getByLabelText('Birth year (optional)'), '19x')
    expect(screen.getByText('Enter a 4-digit year')).toBeInTheDocument()
    expect(check).toBeDisabled()
    expect(calls.some((c) => c.path.includes('/check'))).toBe(false)
  })

  it('shows a server error from the check', async () => {
    mock({ check: () => json({ detail: 'Project not found' }, 404) })
    render(<ScreeningPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Name'), 'A')
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Project not found')
  })
})
