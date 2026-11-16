import { authHeaders } from './client'
import type { RunEvent } from './types'

/** Split a buffer into complete SSE frames. Returns the parsed events and the unread rest. */
export function parseSse(buffer: string): { events: RunEvent[]; rest: string } {
  const events: RunEvent[] = []
  const frames = buffer.split('\n\n')
  const rest = frames.pop() ?? ''
  for (const frame of frames) {
    const data = frame
      .split('\n')
      .filter((l) => l.startsWith('data: '))
      .map((l) => l.slice(6))
      .join('\n')
    if (!data) continue // keep-alive comment
    try {
      events.push(JSON.parse(data) as RunEvent)
    } catch {
      /* skip a damaged frame */
    }
  }
  return { events, rest }
}

const TERMINAL = new Set(['run_completed', 'run_failed'])

/**
 * Follow a project's run events. Uses fetch (not EventSource) so the bearer token can be
 * sent as a header. Reconnects with the last seen id until a terminal event or abort.
 */
export async function streamEvents(
  slug: string,
  onEvent: (e: RunEvent) => void,
  signal: AbortSignal,
  after = 0,
): Promise<void> {
  let last = after
  let delay = 500
  while (!signal.aborted) {
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(slug)}/events/stream?after=${last}`, {
        headers: authHeaders(),
        signal,
      })
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`)
      delay = 500
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += value
        const parsed = parseSse(buffer)
        buffer = parsed.rest
        for (const e of parsed.events) {
          last = Math.max(last, e.seq)
          onEvent(e)
          if (TERMINAL.has(e.type)) return
        }
      }
      return // server closed: nothing more to send
    } catch {
      if (signal.aborted) return
      await new Promise((r) => setTimeout(r, delay))
      delay = Math.min(delay * 2, 8000)
    }
  }
}
