import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { askQuestion } from '../api/ask'
import type { ChatStatus } from '../api/types'
import { useLoad } from '../lib/useApi'
import { Markdown } from './Markdown'
import { Banner, Button, Card, EmptyState, Spinner } from './ui'

interface Turn {
  question: string
  answer: string
  status: 'working' | 'done' | 'failed'
  tool?: string
}

const TOOL_LABEL: Record<string, string> = {
  search_in_file: 'Searching a document',
  get_page_content: 'Reading a page',
  verify_citation: 'Checking a quote',
  batch_verify_citations: 'Checking quotes',
  get_subject_files: 'Finding the entity files',
  search_similar: 'Looking for similar findings',
}
const toolLabel = (name: string) => TOOL_LABEL[name] ?? 'Working'

const usd = (n: number) => `$${n.toFixed(2)}`

/** Ask questions about the latest review. Answers come from the findings and the documents. */
export function AskPanel({ slug }: { slug: string }) {
  const status = useLoad(() => api<ChatStatus>(`/projects/${slug}/chat`), `chat-${slug}`)
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [cost, setCost] = useState<number | null>(null)
  const abort = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const working = turns.at(-1)?.status === 'working'

  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' })
  }, [turns])

  if (status.loading && !status.data) return <Spinner />
  if (status.error || !status.data) return <Banner tone="error">{status.error ?? 'Ask could not be loaded'}</Banner>
  if (!status.data.ready)
    return <EmptyState title="Nothing to ask yet" body="Ask answers from a finished review. Run one first, then come back." />

  const s = status.data
  const spent = cost ?? s.session_cost
  const patchLast = (change: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === all.length - 1 ? change(t) : t)))

  async function send() {
    const question = text.trim()
    if (!question || working) return
    setText('')
    setError(null)
    setTurns((all) => [...all, { question, answer: '', status: 'working' }])
    const ctl = new AbortController()
    abort.current = ctl
    try {
      await askQuestion(
        slug,
        question,
        (e) => {
          if (e.type === 'tool') patchLast((t) => ({ ...t, tool: e.name }))
          else if (e.type === 'text') patchLast((t) => ({ ...t, answer: t.answer + e.text }))
          else if (e.type === 'done') {
            patchLast((t) => ({ ...t, answer: e.done.text, status: 'done', tool: undefined }))
            setCost(e.done.session_cost)
          } else {
            patchLast((t) => ({ ...t, status: 'failed', tool: undefined }))
            setError(e.message)
          }
        },
        ctl.signal,
      )
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
    patchLast((t) => (t.status === 'working' ? { ...t, status: 'failed', tool: undefined } : t))
  }

  async function reset() {
    try {
      await api<void>(`/projects/${slug}/chat`, { method: 'DELETE' })
      setTurns([])
      setCost(null)
      setError(null)
      status.reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <div className="flex items-center justify-between gap-4 text-sm text-slate-600">
          <span>Answers use the {s.finding_count} findings of the latest review and its documents. Each question costs money.</span>
          <span className="whitespace-nowrap" aria-label="Session cost">
            {usd(spent)} of {usd(s.max_session_cost)}
          </span>
        </div>

        {turns.length === 0 && (
          <p className="text-sm text-slate-500">
            Try: &ldquo;Which contracts need consent if the company is sold?&rdquo; or &ldquo;Why is the top finding rated P0?&rdquo;
          </p>
        )}

        <ol aria-label="Conversation" className="space-y-4">
          {turns.map((t, i) => (
            <li key={i} className="space-y-2">
              <p className="rounded-lg bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-900">{t.question}</p>
              {t.answer && <Markdown text={t.answer} />}
              {t.status === 'working' && (
                <p className="flex items-center gap-2 px-1 text-xs text-slate-500">
                  <Spinner small />
                  {t.tool ? `${toolLabel(t.tool)}...` : 'Thinking...'}
                </p>
              )}
            </li>
          ))}
        </ol>
        <div ref={end} />

        {error && <Banner tone="error">{error}</Banner>}

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void send()
          }}
        >
          <textarea
            aria-label="Your question"
            value={text}
            rows={2}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="Ask about this review"
            className="min-h-[2.5rem] flex-1 resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-indigo-600"
          />
          <Button type="submit" busy={working} disabled={!text.trim()}>
            Ask
          </Button>
        </form>
      </Card>
      {(turns.length > 0 || s.active) && (
        <Button variant="ghost" onClick={() => void reset()} disabled={working}>
          New conversation
        </Button>
      )}
    </div>
  )
}
