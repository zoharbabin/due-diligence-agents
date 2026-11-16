export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`
}

export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return ''
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} h ${m % 60} min`
}

export function formatUsd(n: number): string {
  return n >= 100 ? `$${n.toFixed(0)}` : `$${n.toFixed(2)}`
}

export function formatDate(iso: string | null): string {
  if (!iso) return 'Never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const SEVERITY_LABEL: Record<string, string> = {
  P0: 'Deal-stopper',
  P1: 'Critical',
  P2: 'Important',
  P3: 'Minor',
}

export function riskLabel(score: number): string {
  if (score >= 70) return 'High'
  if (score >= 40) return 'Medium'
  if (score > 0) return 'Low'
  return 'None'
}

/** "/a/b/Acme/" -> "Acme" */
export function baseName(path: string): string {
  const parts = path.replace(/[\\/]+$/, '').split(/[\\/]/)
  return parts[parts.length - 1] ?? ''
}

/** "20260201_093000" -> "Feb 1, 2026, 9:30 AM". Other ids are shown as they are. */
export function runLabel(id: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id)
  if (!m) return id
  const [y, mo, day, h, mi, sec] = m.slice(1).map(Number) as [number, number, number, number, number, number]
  const d = new Date(y, mo - 1, day, h, mi, sec)
  return Number.isNaN(d.getTime()) ? id : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
