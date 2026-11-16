import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ComparePanel } from '../components/ComparePanel'
import { runLabel } from '../lib/format'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

const run = (id: string, has = true) => ({ run_id: id, is_latest: false, has_findings: has, reports: [] })

describe('ComparePanel', () => {
  it('asks for a second review when there is only one', () => {
    render(<ComparePanel slug="p" runs={[run('a')]} />)
    expect(screen.getByText(/Run a second review/)).toBeInTheDocument()
  })
  it('ignores runs without findings', () => {
    render(<ComparePanel slug="p" runs={[run('a'), run('b', false)]} />)
    expect(screen.getByText(/Run a second review/)).toBeInTheDocument()
  })
  it('compares the two newest runs and groups the changes', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json({
        current_run_id: 'n',
        prior_run_id: 'o',
        summary: {},
        changes: [
          { change_type: 'new_finding', subject: 'Acme', finding_summary: 'Change of control', prior_severity: null, current_severity: 'P0', details: '' },
          { change_type: 'changed_severity', subject: 'Acme', finding_summary: 'Renewal', prior_severity: 'P2', current_severity: 'P0', details: '' },
        ],
      }),
    )
    render(<ComparePanel slug="p" runs={[run('n'), run('o')]} />)
    expect(await screen.findByText('Change of control')).toBeInTheDocument()
    expect(screen.getByText('Renewal')).toBeInTheDocument()
    expect(screen.getByText('No findings were resolved.')).toBeInTheDocument()
    expect(String(f.mock.calls[0]?.[0])).toContain('/api/projects/p/compare?current=n&prior=o')
  })
  it('picks the two newest runs when a run finishes while the tab is open', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ current_run_id: 'n', prior_run_id: 'o', summary: {}, changes: [] }))
    const { rerender } = render(<ComparePanel slug="p" runs={[run('o')]} />)
    expect(screen.getByText(/Run a second review/)).toBeInTheDocument()
    rerender(<ComparePanel slug="p" runs={[run('n'), run('o')]} />)
    expect(await screen.findByLabelText('Newer review')).toHaveValue('n')
    expect(screen.getByLabelText('Older review')).toHaveValue('o')
    expect(String(f.mock.calls[0]?.[0])).toContain('current=n&prior=o')
  })
  it('does not compare a run with itself', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ current_run_id: 'n', prior_run_id: 'o', summary: {}, changes: [] }))
    render(<ComparePanel slug="p" runs={[run('n'), run('o')]} />)
    await userEvent.selectOptions(screen.getByLabelText('Older review'), 'n')
    expect(await screen.findByText('Pick two different reviews.')).toBeInTheDocument()
  })
})

describe('runLabel', () => {
  it('formats a run id and leaves other ids alone', () => {
    expect(runLabel('20260201_093000')).toMatch(/2026/)
    expect(runLabel('custom-run')).toBe('custom-run')
  })
})
