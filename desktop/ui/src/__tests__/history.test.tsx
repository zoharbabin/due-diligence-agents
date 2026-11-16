import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { HistoryPanel } from '../components/HistoryPanel'

const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200 })
afterEach(() => vi.restoreAllMocks())

const entry = (id: string, type: string, title: string, extra: object = {}) => ({
  id,
  timestamp: '2026-01-02T10:00:00+00:00',
  interaction_type: type,
  title,
  findings_summary: null,
  entities_affected: [],
  duration_seconds: null,
  cost_usd: null,
  user_initiated: false,
  ...extra,
})

it('shows an empty message when nothing happened', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ entries: [], total: 0, by_type: {} }))
  render(<HistoryPanel slug="p" />)
  expect(await screen.findByText('Nothing has happened in this project yet.')).toBeInTheDocument()
})

it('lists entries with counts, cost and entities, and filters by type', async () => {
  const urls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
    urls.push(String(url))
    const all = [
      entry('b', 'chat', 'Asked about consent', { entities_affected: ['a', 'b', 'c', 'd'] }),
      entry('a', 'pipeline_run', 'Full review', { findings_summary: { total: 7, p0: 2, p1: 0, p2: 5, p3: 0, new_since_last: 0 }, cost_usd: 12.5 }),
    ]
    const only = String(url).includes('type=chat')
    return json({ entries: only ? [all[0]] : all, total: only ? 1 : 2, by_type: { chat: 1, pipeline_run: 1 } })
  })
  render(<HistoryPanel slug="p" />)
  expect(await screen.findByText('Full review')).toBeInTheDocument()
  expect(screen.getByText('7 findings')).toBeInTheDocument()
  expect(screen.getByText('$12.50')).toBeInTheDocument()
  expect(screen.getByText('a, b, c +1')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Show'), 'chat')
  await waitFor(() => expect(screen.queryByText('Full review')).not.toBeInTheDocument())
  expect(urls.at(-1)).toContain('?type=chat')
})

it('shows a load error', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'No project' }), { status: 404 }))
  render(<HistoryPanel slug="p" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('No project')
})
