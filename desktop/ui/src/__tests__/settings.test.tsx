import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from '../pages/Settings'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

const doctor = (over: Record<string, unknown> = {}) => ({
  provider: 'anthropic',
  base_url: null,
  credential_present: true,
  credential_env: ['ANTHROPIC_API_KEY'],
  cli: { found: true, source: 'managed' },
  ready: true,
  ...over,
})

function mock(state: { doctor: Record<string, unknown>; probe?: { ok: boolean; detail: string } }) {
  const calls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '')
    const method = (init as RequestInit | undefined)?.method ?? 'GET'
    calls.push(`${method} ${path}`)
    if (path === '/doctor') return json(state.doctor)
    if (path === '/health') return json({ status: 'ok', version: '9.9.9' })
    if (path === '/doctor/probe') return json(state.probe ?? { ok: true, detail: '' })
    if (path === '/settings/env') {
      state.doctor = { ...state.doctor, credential_present: false, ready: false }
      return json({ set: [] })
    }
    return json({}, 404)
  })
  return calls
}

describe('SettingsPage', () => {
  it('shows the connection status and the version', async () => {
    mock({ doctor: doctor() })
    render(<SettingsPage />)
    expect(await screen.findByText('Downloaded by this app')).toBeInTheDocument()
    expect(screen.getByText('9.9.9')).toBeInTheDocument()
    expect(screen.getByText('Replace the API key')).toBeInTheDocument()
  })
  it('tests the connection on request', async () => {
    const calls = mock({ doctor: doctor(), probe: { ok: false, detail: 'invalid x-api-key' } })
    render(<SettingsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/invalid x-api-key/)).toBeInTheDocument()
    expect(calls).toContain('POST /doctor/probe')
  })
  it('removes the key and updates the status', async () => {
    const calls = mock({ doctor: doctor() })
    render(<SettingsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove key' }))
    expect(await screen.findByText('Missing')).toBeInTheDocument()
    expect(calls).toContain('PUT /settings/env')
    expect(screen.getByText('Add an API key')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeDisabled()
  })
  it('explains that other providers are set outside the app', async () => {
    mock({ doctor: doctor({ provider: 'bedrock', credential_env: ['AWS_PROFILE'] }) })
    render(<SettingsPage />)
    await waitFor(() => expect(screen.getByText(/set by environment variables \(AWS_PROFILE\)/)).toBeInTheDocument())
    expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  })
})
