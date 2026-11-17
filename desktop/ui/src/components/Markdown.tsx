import type { ReactNode } from 'react'

/**
 * Renders the small markdown subset the model uses in answers: paragraphs, headings, lists, tables,
 * code, bold, italic. It builds React elements, never HTML, and has no links, so model text cannot
 * inject markup or send the user to another page.
 */

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/g

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.length > 2 && part.startsWith('`') && part.endsWith('`'))
      return (
        <code key={i} className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      )
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.length > 2 && part.startsWith('*') && part.endsWith('*') && !part.startsWith('**')) return <em key={i}>{part.slice(1, -1)}</em>
    return part
  })
}

const FENCE = /^\s*```/
const HEADING = /^(#{1,4})\s+(.*)$/
const BULLET = /^\s*[-*]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const TABLE_ROW = /^\s*\|.*\|?\s*$/
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

const cells = (row: string) =>
  row
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())

const startsBlock = (line: string, next: string | undefined) =>
  !line.trim() ||
  FENCE.test(line) ||
  HEADING.test(line) ||
  BULLET.test(line) ||
  NUMBERED.test(line) ||
  (TABLE_ROW.test(line) && next !== undefined && TABLE_RULE.test(next))

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    const key = blocks.length
    if (!line.trim()) {
      i++
    } else if (FENCE.test(line)) {
      const body: string[] = []
      i++
      while (i < lines.length && !FENCE.test(lines[i]!)) body.push(lines[i++]!)
      i++
      blocks.push(
        <pre key={key} className="overflow-x-auto rounded-lg bg-slate-100 p-3 text-xs">
          {body.join('\n')}
        </pre>,
      )
    } else if (HEADING.test(line)) {
      blocks.push(
        <h4 key={key} className="pt-1 font-semibold text-slate-900">
          {inline(HEADING.exec(line)![2]!)}
        </h4>,
      )
      i++
    } else if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]!)) {
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && TABLE_ROW.test(lines[i]!)) rows.push(cells(lines[i++]!))
      blocks.push(
        <div key={key} className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr>
                {head.map((c, n) => (
                  <th key={n} scope="col" className="border-b border-slate-300 px-2 py-1 font-semibold text-slate-700">
                    {inline(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, n) => (
                <tr key={n} className="border-b border-slate-100 align-top">
                  {head.map((_, m) => (
                    <td key={m} className="px-2 py-1">
                      {inline(r[m] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line)
      const pattern = ordered ? NUMBERED : BULLET
      const items: string[] = []
      while (i < lines.length && pattern.test(lines[i]!)) items.push(pattern.exec(lines[i++]!)![1]!)
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List key={key} className={`space-y-1 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}>
          {items.map((t, n) => (
            <li key={n}>{inline(t)}</li>
          ))}
        </List>,
      )
    } else {
      const para: string[] = [line.trim()]
      i++
      while (i < lines.length && !startsBlock(lines[i]!, lines[i + 1])) para.push(lines[i++]!.trim())
      blocks.push(<p key={key}>{inline(para.join(' '))}</p>)
    }
  }
  return <div className="space-y-3 px-1 text-sm leading-relaxed text-slate-800">{blocks}</div>
}
