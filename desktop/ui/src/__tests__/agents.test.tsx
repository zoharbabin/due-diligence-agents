import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentsPanel } from '../components/AgentsPanel'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

interface State {
  override: string | null
  reject?: boolean
}

function mock(state: State) {
  const calls: { method: string; path: string; body?: unknown }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '')
    const method = (init as RequestInit | undefined)?.method ?? 'GET'
    const body = (init as RequestInit | undefined)?.body
    calls.push({ method, path, body: body ? JSON.parse(String(body)) : undefined })
    if (path === '/projects/p/agents')
      return json([
        { name: 'legal', display_name: 'Legal', status: 'enabled', has_override: state.override !== null },
        { name: 'finance', display_name: 'Finance', status: 'enabled', has_override: false },
      ])
    if (path === '/profiles') return json([{ name: 'saas', content: '## Additional Focus Areas\n\n- arr\n' }])
    if (path.endsWith('/preview')) return json({ prompt: 'FULL PROMPT TEXT' })
    if (method === 'PUT') {
      if (state.reject)
        return json({ detail: { message: 'The override is not valid', issues: [{ level: 'error', message: 'safety floor' }] } }, 422)
      state.override = (JSON.parse(String(body)) as { content: string }).content
      return json({ content: state.override })
    }
    if (method === 'DELETE') {
      state.override = null
      return new Response(null, { status: 204 })
    }
    if (path.startsWith('/projects/p/agents/'))
      return json({ name: path.split('/').pop(), description: 'Built-in description', override: state.override })
    return json({}, 404)
  })
  return calls
}

describe('AgentsPanel', () => {
  it('lists agents and marks the customized one', async () => {
    mock({ override: '## Additional Instructions\n\nx\n' })
    render(<AgentsPanel slug="p" />)
    expect(await screen.findByText('Customized')).toBeInTheDocument()
    expect(screen.getByText('Finance')).toBeInTheDocument()
  })
  it('saves an override started from a profile', async () => {
    const state: State = { override: null }
    const calls = mock(state)
    render(<AgentsPanel slug="p" />)
    await screen.findByLabelText('Your changes for this project')
    await userEvent.selectOptions(screen.getByLabelText('Start from'), 'saas')
    expect(screen.getByLabelText('Your changes for this project')).toHaveValue('## Additional Focus Areas\n\n- arr\n')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Saved. The next review uses it.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ content: '## Additional Focus Areas\n\n- arr\n' })
    expect(await screen.findByText('Customized')).toBeInTheDocument()
  })
  it('shows the reasons when the override is rejected', async () => {
    mock({ override: null, reject: true })
    render(<AgentsPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Your changes for this project'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('The override is not valid')).toBeInTheDocument()
    expect(screen.getByText('safety floor')).toBeInTheDocument()
  })
  it('previews the prompt only for saved text', async () => {
    mock({ override: '## Additional Instructions\n\nx\n' })
    render(<AgentsPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Your changes for this project'), 'y')
    expect(screen.getByRole('button', { name: 'Preview prompt' })).toBeDisabled()
    await userEvent.clear(screen.getByLabelText('Your changes for this project'))
    await userEvent.type(screen.getByLabelText('Your changes for this project'), '## Additional Instructions\n\nx\n')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Preview prompt' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Preview prompt' }))
    expect(await screen.findByLabelText('Assembled prompt')).toHaveTextContent('FULL PROMPT TEXT')
  })
  it('goes back to the built-in agent', async () => {
    const state: State = { override: '## Additional Instructions\n\nx\n' }
    const calls = mock(state)
    render(<AgentsPanel slug="p" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Use built-in agent' }))
    expect(await screen.findByText('Back to the built-in agent.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
    await waitFor(() => expect(screen.queryByText('Customized')).not.toBeInTheDocument())
  })
})
