import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SuggestCard } from '../components/SuggestCard'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

function mock(states: unknown[], post: () => Response = () => json({ state: 'running' }, 202)) {
  const calls: string[] = []
  let i = 0
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
    const method = (init as RequestInit | undefined)?.method ?? 'GET'
    calls.push(method)
    if (method === 'POST') return post()
    return json(states[Math.min(i++, states.length - 1)])
  })
  return calls
}

describe('SuggestCard', () => {
  it('is disabled until buyer and target are saved', async () => {
    mock([{ state: 'idle' }])
    render(<SuggestCard slug="p" ready={false} onDraft={() => undefined} />)
    expect(await screen.findByRole('button', { name: 'Suggest a setup' })).toBeDisabled()
    expect(screen.getByText(/Save the buyer and target names/)).toBeInTheDocument()
  })

  it('starts a draft, follows it, and hands the draft over without saving', async () => {
    const draft = { buyer: { name: 'B' } }
    const calls = mock([{ state: 'idle' }, { state: 'running' }, { state: 'done', config: draft }])
    const onDraft = vi.fn()
    render(<SuggestCard slug="p" ready onDraft={onDraft} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Suggest a setup' }))
    expect(await screen.findByText(/Reading your data room/)).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Review the draft' }, { timeout: 4000 }))
    expect(onDraft).toHaveBeenCalledWith(draft)
    expect(calls.filter((m) => m === 'POST')).toHaveLength(1)
    expect(calls).not.toContain('PUT')
  })

  it('shows a failure and allows another try', async () => {
    mock([{ state: 'error', error: 'RuntimeError: provider down' }])
    render(<SuggestCard slug="p" ready onDraft={() => undefined} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('provider down')
    expect(screen.getByRole('button', { name: 'Suggest again' })).toBeEnabled()
  })

  it('shows the server reason when it refuses to start', async () => {
    mock([{ state: 'idle' }], () => json({ detail: 'A draft is already being made' }, 409))
    render(<SuggestCard slug="p" ready onDraft={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Suggest a setup' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already being made')
  })
})
