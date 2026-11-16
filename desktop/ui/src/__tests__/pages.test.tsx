import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { baseName } from '../lib/format'
import { CliDownload } from '../components/CliDownload'
import { NewProjectPage } from '../pages/NewProject'
import { ProjectsPage } from '../pages/Projects'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

describe('ProjectsPage', () => {
  it('shows the empty state with a call to action', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json([]))
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    expect(await screen.findByText('Start your first review')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New project' })).toBeInTheDocument()
  })
  it('lists projects with severity counts', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json([{ name: 'Deal A', slug: 'deal-a', status: 'completed', buyer: 'B', target: 'T', finding_counts: { P0: 2, P2: 1 }, last_run_at: null }]),
    )
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    expect(await screen.findByText('Deal A')).toBeInTheDocument()
    expect(screen.getByText('B acquiring T')).toBeInTheDocument()
    expect(screen.getByTitle('Deal-stopper')).toHaveTextContent('P02')
  })
  it('shows an error when the service fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'nope' }, 500))
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
  })
})

describe('NewProjectPage', () => {
  it('derives a name from the folder', () => {
    expect(baseName('/a/b/Acme/')).toBe('Acme')
    expect(baseName('C:\\Deals\\Acme')).toBe('Acme')
  })
  it('creates the project, shows the scan, then asks for buyer and target', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (String(url).endsWith('/scan')) return json({ total_files: 12, total_bytes: 2048, by_extension: {}, truncated: false })
      if ((init as RequestInit | undefined)?.method === 'POST') return json({ slug: 'acme', name: 'Acme' }, 201)
      return json({})
    })
    render(<MemoryRouter><NewProjectPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('Data room folder'), '/rooms/Acme')
    expect(screen.getByLabelText('Project name')).toHaveValue('Acme')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText(/Found 12 files/)).toBeInTheDocument()
    expect(screen.getByLabelText('Buyer')).toBeInTheDocument()
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2))
  })
  it('shows the server message when the folder is wrong', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'data_room must be an existing absolute folder path' }, 422))
    render(<MemoryRouter><NewProjectPage /></MemoryRouter>)
    await userEvent.type(screen.getByLabelText('Data room folder'), 'relative')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('existing absolute folder')
  })
})

describe('setup card', () => {
  const doctor = { provider: 'anthropic', credential_present: false, credential_env: ['ANTHROPIC_API_KEY'], cli: { found: true, source: 'system' }, ready: false, base_url: null }
  it('asks for a key when none is set, and tests it after saving', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const u = String(url)
      calls.push(u)
      if (u.endsWith('/projects')) return json([])
      if (u.endsWith('/doctor')) return json(doctor)
      if (u.endsWith('/doctor/probe')) return json({ ok: true, detail: '' })
      return json({ set: ['ANTHROPIC_API_KEY'] })
    })
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    await userEvent.type(await screen.findByLabelText('API key'), 'sk-ant-12345678')
    await userEvent.click(screen.getByRole('button', { name: 'Save and test' }))
    expect(await screen.findByText('Connected.')).toBeInTheDocument()
    expect(calls).toContain('/api/settings/env')
  })
  it('says so when the CLI is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) =>
      String(url).endsWith('/doctor') ? json({ ...doctor, cli: { found: false, source: null } }) : json([]),
    )
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    expect(await screen.findByText('Download the Claude engine')).toBeInTheDocument()
  })

  it('downloads the CLI, shows progress, and reports completion', async () => {
    let state: Record<string, unknown> = { state: 'idle', done: 0, total: null, error: null }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url)
      if (u.endsWith('/cli/install') && init?.method === 'POST') {
        state = { state: 'downloading', done: 1_048_576, total: 4_194_304, error: null }
        return json(state, 202)
      }
      if (u.endsWith('/cli/install')) {
        state = { state: 'done', done: 4_194_304, total: 4_194_304, error: null }
        return json(state)
      }
      return json({})
    })
    const onDone = vi.fn()
    render(<CliDownload onDone={onDone} />)
    await userEvent.click(screen.getByRole('button', { name: 'Download' }))
    expect(await screen.findByRole('progressbar', { name: 'Download progress' })).toHaveAttribute('aria-valuenow', '25')
    await waitFor(() => expect(onDone).toHaveBeenCalled(), { timeout: 3000 })
  })

  it('moves on to the key form after the download, without refetching in a loop', async () => {
    let cliFound = false
    let doctorCalls = 0
    const doctor = { provider: 'anthropic', base_url: null, credential_present: false, credential_env: ['ANTHROPIC_API_KEY'], ready: false }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const u = String(url)
      if (u.endsWith('/doctor')) {
        doctorCalls += 1
        await new Promise((r) => setTimeout(r, 30))
        return json({ ...doctor, cli: { found: cliFound, source: cliFound ? 'managed' : null } })
      }
      if (u.endsWith('/cli/install') && init?.method === 'POST') return json({ state: 'downloading', done: 1, total: 4 }, 202)
      if (u.endsWith('/cli/install')) {
        cliFound = true
        return json({ state: 'done', done: 4, total: 4, error: null })
      }
      return json([])
    })
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Download' }))
    expect(await screen.findByLabelText('API key', {}, { timeout: 3000 })).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 300))
    expect(doctorCalls).toBeLessThanOrEqual(3)
  })

  it('shows the failure and offers a retry', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      json({ state: 'error', done: 0, total: null, error: 'The download failed the integrity check.' }, 202),
    )
    render(<CliDownload onDone={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Download' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('integrity check')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
