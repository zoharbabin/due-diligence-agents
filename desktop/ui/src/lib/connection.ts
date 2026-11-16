import { api } from '../api/client'

export interface ProbeResult {
  ok: boolean
  text: string
}

/** Run one live test query and turn the answer into text the user can act on. */
export async function testConnection(): Promise<ProbeResult> {
  const probe = await api<{ ok: boolean; detail: string }>('/doctor/probe', { method: 'POST' })
  return { ok: probe.ok, text: probe.ok ? 'Connected.' : `The key did not work: ${probe.detail}` }
}
