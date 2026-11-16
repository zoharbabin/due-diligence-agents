import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UpdateBanner } from '../components/UpdateBanner'

type Invoke = (cmd: string) => Promise<unknown>
function withShell(invoke: Invoke) {
  ;(window as unknown as { __TAURI_INTERNALS__?: { invoke: Invoke } }).__TAURI_INTERNALS__ = { invoke }
}
afterEach(() => {
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
})

describe('UpdateBanner', () => {
  it('shows nothing in a browser', () => {
    const { container } = render(<UpdateBanner />)
    expect(container).toBeEmptyDOMElement()
  })
  it.each([
    ['is current', async () => null],
    [
      'update server is down',
      async () => {
        throw new Error('offline')
      },
    ],
  ])('shows nothing when the %s', async (_name, result) => {
    const invoke = vi.fn<Invoke>(result)
    withShell(invoke)
    const { container } = render(<UpdateBanner />)
    await waitFor(() => expect(invoke).toHaveBeenCalledWith('check_for_update'))
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
  })
  it('offers the new version and installs it on request', async () => {
    const invoke = vi.fn<Invoke>(async (cmd) => (cmd === 'check_for_update' ? { version: '2.0.0', notes: null } : undefined))
    withShell(invoke)
    render(<UpdateBanner />)
    expect(await screen.findByText(/Version 2\.0\.0 is available/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Update and restart' }))
    expect(invoke).toHaveBeenCalledWith('install_update')
  })
  it('shows why an install failed and lets the user retry', async () => {
    withShell(async (cmd) => {
      if (cmd === 'check_for_update') return { version: '2.0.0', notes: null }
      throw 'The update signature did not match.'
    })
    render(<UpdateBanner />)
    await userEvent.click(await screen.findByRole('button', { name: 'Update and restart' }))
    expect(await screen.findByText('The update signature did not match.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Update and restart' })).toBeEnabled()
  })
})
