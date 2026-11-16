import { describe, expect, it } from 'vitest'
import { parseSse } from '../api/sse'

const ev = (seq: number) => JSON.stringify({ seq, type: 'step_started', run_id: 'r', data: {} })

describe('parseSse', () => {
  it('parses complete frames and keeps the partial rest', () => {
    const { events, rest } = parseSse(`id: 1\ndata: ${ev(1)}\n\nid: 2\ndata: ${ev(2)}\n\ndata: {"seq"`)
    expect(events.map((e) => e.seq)).toEqual([1, 2])
    expect(rest).toBe('data: {"seq"')
  })
  it('ignores keep-alive comments and damaged frames', () => {
    const { events } = parseSse(`: keepalive\n\ndata: {oops\n\ndata: ${ev(3)}\n\n`)
    expect(events.map((e) => e.seq)).toEqual([3])
  })
})
