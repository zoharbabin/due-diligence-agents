import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RunPanel } from '../components/RunPanel'
import { initialProgress, type RunProgress } from '../lib/progress'

const running = (over: Partial<RunProgress>): RunProgress => ({ ...initialProgress, status: 'running', ...over })
const agent = (name: string, done: number, total: number) => ({ name, status: 'running' as const, done, total, costUsd: 0 })

describe('RunPanel', () => {
  it('names agents the way the Agents tab does', () => {
    const agents = { hr: agent('hr', 0, 2), esg: agent('esg', 0, 2), producttech: agent('producttech', 0, 2) }
    render(<RunPanel progress={running({ agents })} onCancel={() => {}} cancelling={false} />)
    for (const label of ['HR / People', 'ESG', 'Product & Tech']) expect(screen.getByText(label)).toBeInTheDocument()
  })
  it('never shows more subjects done than the total', () => {
    render(<RunPanel progress={running({ agents: { esg: agent('esg', 3, 2) } })} onCancel={() => {}} cancelling={false} />)
    expect(screen.getByText('3/3')).toBeInTheDocument()
  })
  it.each([[0], [3000]])('hides a time left of %i ms, too short to mean anything', (etaMs) => {
    render(<RunPanel progress={running({ stepName: 'Merge', etaMs })} onCancel={() => {}} cancelling={false} />)
    expect(screen.queryByText(/left/)).toBeNull()
  })
  it('shows a time left of a minute', () => {
    render(<RunPanel progress={running({ stepName: 'Merge', etaMs: 60_000 })} onCancel={() => {}} cancelling={false} />)
    expect(screen.getByText(/about 1 min left/)).toBeInTheDocument()
  })
})
