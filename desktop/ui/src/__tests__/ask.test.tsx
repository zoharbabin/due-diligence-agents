import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseAsk } from '../api/ask'
import { AskPanel } from '../components/AskPanel'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => vi.restoreAllMocks())

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
const stream = (...frames: string[]) =>
  new Response(
    new ReadableStream({
      start(c) {
        const enc = new TextEncoder()
        frames.forEach((f) => c.enqueue(enc.encode(f)))
        c.close()
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )

const STATUS = { ready: true, active: false, busy: false, turn_count: 0, session_cost: 0, finding_count: 4, max_session_cost: 10 }

function mock(opts: { status?: object; ask?: () => Response } = {}) {
  const calls: { method: string; path: string; body?: unknown }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    const path = String(url).replace(/^.*\/api/, '')
    const method = (init as RequestInit | undefined)?.method ?? 'GET'
    const body = (init as RequestInit | undefined)?.body
    calls.push({ method, path, body: body ? JSON.parse(String(body)) : undefined })
    if (method === 'GET') return json(opts.status ?? STATUS)
    if (method === 'DELETE') return new Response(null, { status: 204 })
    return opts.ask ? opts.ask() : json({}, 500)
  })
  return calls
}

describe('parseAsk', () => {
  it('parses named frames and keeps the unfinished rest', () => {
    const buf = frame('tool', { name: 'search_in_file' }) + frame('text', { text: 'Hi' }) + 'event: text\ndata: {"te'
    const { events, rest } = parseAsk(buf)
    expect(events).toEqual([
      { type: 'tool', name: 'search_in_file' },
      { type: 'text', text: 'Hi' },
    ])
    expect(rest).toBe('event: text\ndata: {"te')
  })

  it('skips damaged and unknown frames', () => {
    expect(parseAsk('event: text\ndata: {oops\n\nevent: other\ndata: {}\n\n').events).toEqual([])
  })
})

describe('AskPanel', () => {
  it('asks the user to run a review first', async () => {
    mock({ status: { ...STATUS, ready: false } })
    render(<AskPanel slug="p" />)
    expect(await screen.findByText('Nothing to ask yet')).toBeInTheDocument()
  })

  it('sends a question, shows the answer and the session cost', async () => {
    const calls = mock({
      ask: () =>
        stream(
          frame('tool', { name: 'search_in_file' }),
          frame('text', { text: 'Two ' }),
          frame('done', { text: 'Two contracts need consent.', tools_used: [], session_cost: 0.5, estimated_cost: 0.5 }),
        ),
    })
    render(<AskPanel slug="p" />)
    const box = await screen.findByLabelText('Your question')
    await userEvent.type(box, 'Which need consent?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByText('Two contracts need consent.')).toBeInTheDocument()
    expect(screen.getByText('Which need consent?')).toBeInTheDocument()
    expect(screen.getByLabelText('Session cost')).toHaveTextContent('$0.50 of $10.00')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ question: 'Which need consent?' })
    expect(box).toHaveValue('')
  })

  it('sends on Enter and keeps Shift+Enter for a new line', async () => {
    const calls = mock({ ask: () => stream(frame('done', { text: 'ok', tools_used: [], session_cost: 0, estimated_cost: 0 })) })
    render(<AskPanel slug="p" />)
    const box = await screen.findByLabelText('Your question')
    await userEvent.type(box, 'a{Shift>}{Enter}{/Shift}b')
    expect(box).toHaveValue('a\nb')
    await userEvent.type(box, '{Enter}')
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1))
  })

  it('shows an error event from the stream', async () => {
    mock({ ask: () => stream(frame('error', { message: 'Session budget exhausted ($10.00)' })) })
    render(<AskPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Your question'), 'Hi')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Session budget exhausted ($10.00)')
  })

  it('shows the reason when the server refuses', async () => {
    mock({ ask: () => json({ detail: 'A question is already running' }, 409) })
    render(<AskPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Your question'), 'Hi')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A question is already running')
  })

  it('starts a new conversation', async () => {
    const calls = mock({ ask: () => stream(frame('done', { text: 'Answer one', tools_used: [], session_cost: 0.1, estimated_cost: 0.1 })) })
    render(<AskPanel slug="p" />)
    await userEvent.type(await screen.findByLabelText('Your question'), 'Hi')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText('Answer one')
    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }))
    await waitFor(() => expect(screen.queryByText('Answer one')).not.toBeInTheDocument())
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })
})
