export type Severity = 'P0' | 'P1' | 'P2' | 'P3'
export const SEVERITIES: Severity[] = ['P0', 'P1', 'P2', 'P3']

export interface Project {
  name: string
  slug: string
  path: string
  config_path: string
  created_at: string
  last_run_at: string | null
  last_run_id: string | null
  status: 'created' | 'running' | 'completed' | 'failed' | 'cancelled' | 'archived'
  total_runs: number
  total_subjects: number
  total_findings: number
  finding_counts: Record<string, number>
  deal_type: string
  buyer: string
  target: string
  risk_score: number
}

export type RunStatus = 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface RunState {
  status: RunStatus
  pid: number | null
  run_id: string
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
}

export interface RunOptions {
  mode?: 'full' | 'incremental'
  quick_scan?: boolean
  no_narrative?: boolean
  no_knowledge?: boolean
  model_profile?: 'economy' | 'standard' | 'premium'
}

export type RunEventType =
  | 'run_started'
  | 'step_started'
  | 'step_completed'
  | 'step_failed'
  | 'agent_started'
  | 'agent_progress'
  | 'agent_completed'
  | 'finding_counts'
  | 'cost'
  | 'run_completed'
  | 'run_failed'

export interface RunEvent {
  schema_version: number
  seq: number
  ts: string
  type: RunEventType
  run_id: string
  step: string | null
  step_number: number | null
  data: Record<string, unknown>
}

export interface Finding {
  id: string
  severity: Severity
  category: string
  title: string
  description: string
  confidence: string
  agent: string
  subject: string
  citations: { source_path?: string; exact_quote?: string; page?: string | number; location?: string }[]
  metadata?: Record<string, unknown>
}

export interface FindingsPage {
  run_id: string
  total: number
  items: Finding[]
  facets: Record<'severity' | 'agent' | 'category', Record<string, number>>
}

export interface RunSummary {
  run_id: string
  is_latest: boolean
  has_findings: boolean
  reports: ('html' | 'xlsx')[]
}

export interface ScanSummary {
  total_files: number
  total_bytes: number
  by_extension: Record<string, number>
  truncated: boolean
}

export interface ConfigIssue {
  loc: string
  msg: string
  type: string
}

export interface ConfigValidation {
  valid: boolean
  errors: ConfigIssue[]
}

export type DealConfig = Record<string, unknown>

export interface Doctor {
  provider: 'anthropic' | 'bedrock' | 'vertex' | 'gateway'
  base_url: string | null
  credential_present: boolean
  credential_env: string[]
  cli: { found: boolean; source: 'env' | 'system' | 'managed' | 'sdk' | null }
  ready: boolean
}

export interface CliInstall {
  state: 'idle' | 'downloading' | 'done' | 'error'
  done: number
  total: number | null
  error: string | null
}
