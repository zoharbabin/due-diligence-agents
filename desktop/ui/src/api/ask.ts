import { ApiError, authHeaders } from './client'
import type { ChatDone } from './types'

export type AskEvent =
  | { type: 'tool'; name: string }
  | { type: 'text'; text: string }
  | { type: 'done'; done: ChatDone }
  | { type: 'error'; message: string }

/** Split a buffer into complete named SSE frames. Returns the parsed events and the unread rest. */
export function parseAsk(buffer: string): { events: AskEvent[]; rest: string } {
  const events: AskEvent[] = []
  const frames = buffer.split('\n\n')
  const rest = frames.pop() ?? ''
  for (const frame of frames) {
    const lines = frame.split('\n')
    const name = lines.find((l) => l.startsWith('event: '))?.slice(7)
    const data = lines.find((l) => l.startsWith('data: '))?.slice(6)
    if (!name || !data) continue
    try {
      const body = JSON.parse(data) as Record<string, unknown>
      if (name === 'tool') events.push({ type: 'tool', name: String(body.name) })
      else if (name === 'text') events.push({ type: 'text', text: String(body.text) })
      else if (name === 'done') events.push({ type: 'done', done: body as unknown as ChatDone })
      else if (name === 'error') events.push({ type: 'error', message: String(body.message) })
    } catch {
      /* skip a damaged frame */
    }
  }
  return { events, rest }
}

async function refusal(res: Response): Promise<ApiError> {
  let detail = res.statusText
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail)) detail = (body.detail as { msg?: string }[]).map((d) => d.msg).join('. ')
  } catch {
    /* keep the status text */
  }
  return new ApiError(res.status, detail)
}

/** Ask one question and report each event as it arrives. Throws ApiError when the server refuses. */
export async function askQuestion(
  slug: string,
  question: string,
  onEvent: (e: AskEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`/api/projects/${encodeURIComponent(slug)}/chat`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ question }),
      signal,
    })
  } catch {
    if (signal.aborted) return
    throw new ApiError(0, 'Cannot reach the local service. Restart the app.')
  }
  if (!res.ok || !res.body) throw await refusal(res)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value
      const parsed = parseAsk(buffer)
      buffer = parsed.rest
      parsed.events.forEach(onEvent)
    }
  } catch {
    if (!signal.aborted) onEvent({ type: 'error', message: 'The connection was lost. Open Ask again in a moment to see the session.' })
  }
}
