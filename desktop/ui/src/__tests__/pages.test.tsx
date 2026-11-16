import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { baseName } from '../lib/format'
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
