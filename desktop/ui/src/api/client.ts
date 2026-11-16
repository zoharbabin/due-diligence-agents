import type { ConfigIssue } from './types'

let token: string | null = null

export function setToken(value: string | null): void {
  token = value
}

interface TauriWindow {
  __TAURI_INTERNALS__?: { invoke: (cmd: string) => Promise<string> }
}

/**
 * Find the per-launch token. The desktop shell hands it over by IPC. In browser dev
 * mode it comes as `?token=...`, is kept for the tab, and is removed from the URL.
 */
export async function loadToken(): Promise<string | null> {
  const tauri = (window as unknown as TauriWindow).__TAURI_INTERNALS__
  if (tauri) {
    token = await tauri.invoke('get_api_token')
    return token
  }
  const url = new URL(window.location.href)
  const fromUrl = url.searchParams.get('token')
  if (fromUrl) {
    sessionStorage.setItem('dd_token', fromUrl)
    url.searchParams.delete('token')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
  }
  token = sessionStorage.getItem('dd_token')
  return token
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly issues: ConfigIssue[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function describe(detail: unknown): { message: string; issues: ConfigIssue[] } {
  if (typeof detail === 'string') return { message: detail, issues: [] }
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; errors?: ConfigIssue[] }
    return { message: d.message ?? 'Request failed', issues: d.errors ?? [] }
  }
  return { message: 'Request failed', issues: [] }
}

export function authHeaders(extra: HeadersInit = {}): Headers {
  const headers = new Headers(extra)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init
  const headers = authHeaders(rest.headers)
  let body = rest.body
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  }
  let res: Response
  try {
    res = await fetch(`/api${path}`, { ...rest, headers, body })
  } catch {
    throw new ApiError(0, 'Cannot reach the local service. Restart the app.')
  }
  if (!res.ok) {
    let detail: unknown
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail
    } catch {
      detail = res.statusText
    }
    const { message, issues } = describe(detail)
    throw new ApiError(res.status, message, issues)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export async function fetchBlob(path: string): Promise<Blob> {
  const res = await fetch(`/api${path}`, { headers: authHeaders() })
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? 'Not found' : 'Download failed')
  return res.blob()
}
