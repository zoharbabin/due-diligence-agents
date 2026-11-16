import type { RunEvent } from '../api/types'

export interface AgentProgress {
  name: string
  status: 'running' | 'done' | 'failed'
  done: number
  total: number
  costUsd: number
}

export interface RunProgress {
  status: 'idle' | 'running' | 'completed' | 'failed'
  runId: string
  stepNumber: number
  stepName: string
  totalSteps: number
  completedSteps: number
  etaMs: number | null
  elapsedMs: number
  costUsd: number
  agents: Record<string, AgentProgress>
  error: string | null
  lastSeq: number
}

export const initialProgress: RunProgress = {
  status: 'idle',
  runId: '',
  stepNumber: 0,
  stepName: '',
  totalSteps: 0,
  completedSteps: 0,
  etaMs: null,
  elapsedMs: 0,
  costUsd: 0,
  agents: {},
  error: null,
  lastSeq: 0,
}

/** "05_bulk_extraction" -> "Bulk extraction" */
export function stepLabel(step: string | null | undefined): string {
  if (!step) return ''
  const text = step.replace(/^\d+_/, '').replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const num = (v: unknown, fallback = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : fallback)

export function reduceEvent(state: RunProgress, e: RunEvent): RunProgress {
  if (e.seq <= state.lastSeq) return state // replay or duplicate
  const next: RunProgress = { ...state, lastSeq: e.seq, runId: e.run_id || state.runId }
  const d = e.data
  switch (e.type) {
    case 'run_started':
      return { ...initialProgress, status: 'running', runId: e.run_id, totalSteps: num(d.total_steps), lastSeq: e.seq }
    case 'step_started':
      return { ...next, stepNumber: e.step_number ?? next.stepNumber, stepName: stepLabel(e.step) }
    case 'step_completed':
      return {
        ...next,
        completedSteps: num(d.completed_steps, next.completedSteps + 1),
        totalSteps: num(d.total_steps, next.totalSteps),
        etaMs: typeof d.eta_ms === 'number' ? d.eta_ms : next.etaMs,
        elapsedMs: num(d.elapsed_ms, next.elapsedMs),
        costUsd: num(d.total_cost_usd, next.costUsd),
      }
    case 'agent_started': {
      const name = String(d.agent)
      return {
        ...next,
        agents: { ...next.agents, [name]: { name, status: 'running', done: 0, total: num(d.total_subjects), costUsd: 0 } },
      }
    }
    case 'agent_progress': {
      const name = String(d.agent)
      const prev = next.agents[name] ?? { name, status: 'running', done: 0, total: 0, costUsd: 0 }
      return {
        ...next,
        agents: { ...next.agents, [name]: { ...prev, done: num(d.subjects_done), total: num(d.total_subjects, prev.total) } },
      }
    }
    case 'agent_completed': {
      const name = String(d.agent)
      const prev = next.agents[name] ?? { name, status: 'running', done: 0, total: 0, costUsd: 0 }
      return {
        ...next,
        agents: {
          ...next.agents,
          [name]: {
            ...prev,
            status: d.ok === false ? 'failed' : 'done',
            done: num(d.subjects_done, prev.done),
            total: num(d.total_subjects, prev.total),
            costUsd: num(d.cost_usd),
          },
        },
      }
    }
    case 'cost':
      return { ...next, costUsd: num(d.total_cost_usd, next.costUsd) }
    case 'step_failed':
      return { ...next, error: typeof d.error === 'string' ? d.error : next.error }
    case 'run_completed':
      return { ...next, status: 'completed', completedSteps: Math.max(next.completedSteps, next.totalSteps) }
    case 'run_failed':
      return { ...next, status: 'failed', error: typeof d.error === 'string' ? d.error : next.error }
    default:
      return next
  }
}

export function percent(p: RunProgress): number {
  if (p.status === 'completed') return 100
  if (!p.totalSteps) return 0
  return Math.min(99, Math.round((p.completedSteps / p.totalSteps) * 100))
}
