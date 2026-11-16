import { describe, expect, it } from 'vitest'
import type { RunEvent } from '../api/types'
import { initialProgress, percent, reduceEvent, stepLabel, type RunProgress } from '../lib/progress'

let seq = 0
const ev = (type: RunEvent['type'], data: Record<string, unknown> = {}, step: string | null = null): RunEvent => ({
  schema_version: 1,
  seq: ++seq,
  ts: '',
  type,
  run_id: 'run_1',
  step,
  step_number: step ? 5 : null,
  data,
})
const fold = (events: RunEvent[]): RunProgress => events.reduce(reduceEvent, initialProgress)

describe('progress reducer', () => {
  it('labels steps', () => {
    expect(stepLabel('05_bulk_extraction')).toBe('Bulk extraction')
    expect(stepLabel(null)).toBe('')
  })
  it('tracks steps, agents and cost', () => {
    seq = 0
    const s = fold([
      ev('run_started', { total_steps: 10 }),
      ev('step_started', {}, '05_bulk_extraction'),
      ev('step_completed', { completed_steps: 5, total_steps: 10, total_cost_usd: 1.5, eta_ms: 60000 }),
      ev('agent_started', { agent: 'legal', total_subjects: 4 }),
      ev('agent_progress', { agent: 'legal', subjects_done: 2, total_subjects: 4 }),
    ])
    expect(s.status).toBe('running')
    expect(s.stepName).toBe('Bulk extraction')
    expect(s.costUsd).toBe(1.5)
    expect(s.agents.legal).toMatchObject({ done: 2, total: 4, status: 'running' })
    expect(percent(s)).toBe(50)
  })
  it('ignores replayed events', () => {
    seq = 0
    const a = ev('run_started', { total_steps: 4 })
    const s = fold([a, a])
    expect(s.lastSeq).toBe(a.seq)
  })
  it('ends on completion and failure', () => {
    seq = 0
    const done = fold([ev('run_started', { total_steps: 4 }), ev('run_completed')])
    expect(done.status).toBe('completed')
    expect(percent(done)).toBe(100)
    seq = 0
    const failed = fold([ev('run_started', { total_steps: 4 }), ev('run_failed', { error: 'boom' })])
    expect(failed).toMatchObject({ status: 'failed', error: 'boom' })
  })
  it('marks a failed agent', () => {
    seq = 0
    const s = fold([ev('agent_completed', { agent: 'finance', ok: false })])
    expect(s.agents.finance?.status).toBe('failed')
  })
})
