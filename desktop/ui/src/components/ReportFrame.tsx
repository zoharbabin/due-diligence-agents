import { useEffect, useState } from 'react'
import { fetchBlob } from '../api/client'
import { Banner, Button, Spinner } from './ui'

/** Shows the HTML report in a sandboxed frame from a blob URL, so the token never leaves the app. */
export function ReportFrame({ slug, runId, hasXlsx }: { slug: string; runId: string; hasXlsx: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let revoked: string | null = null
    let live = true
    fetchBlob(`/projects/${slug}/runs/${runId}/report/html`).then(
      (b) => {
        if (!live) return
        revoked = URL.createObjectURL(new Blob([b], { type: 'text/html' }))
        setUrl(revoked)
      },
      (e: unknown) => live && setError(e instanceof Error ? e.message : String(e)),
    )
    return () => {
      live = false
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [slug, runId])

  async function download(kind: 'html' | 'xlsx') {
    const b = await fetchBlob(`/projects/${slug}/runs/${runId}/report/${kind}`)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(b)
    a.download = `dd_report.${kind}`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  if (error) return <Banner tone="error">{error}</Banner>
  if (!url) return <Spinner />
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button variant="secondary" onClick={() => download('html')}>
          Save HTML
        </Button>
        {hasXlsx && (
          <Button variant="secondary" onClick={() => download('xlsx')}>
            Save Excel
          </Button>
        )}
      </div>
      <iframe title="Report" src={url} sandbox="allow-scripts" className="h-[70vh] w-full rounded-xl border border-slate-200 bg-white" />
    </div>
  )
}
