import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, loadToken, setToken } from '../api/client'

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
  setToken(null)
})

describe('loadToken', () => {
  it('takes the token from the URL, stores it and strips it from the address bar', async () => {
    window.history.replaceState(null, '', '/?token=abc123&x=1#/p')
    expect(await loadToken()).toBe('abc123')
    expect(window.location.search).toBe('?x=1')
    expect(window.location.hash).toBe('#/p')
    expect(await loadToken()).toBe('abc123') // from sessionStorage now
  })
})

describe('api', () => {
  it('sends the bearer token and JSON body', async () => {
    setToken('tok')
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"ok":1}', { status: 200 }))
    await api('/x', { method: 'POST', json: { a: 1 } })
    const [url, init] = f.mock.calls[0]!
    expect(url).toBe('/api/x')
    const h = new Headers((init as RequestInit).headers)
    expect(h.get('Authorization')).toBe('Bearer tok')
    expect(h.get('Content-Type')).toBe('application/json')
    expect((init as RequestInit).body).toBe('{"a":1}')
  })
  it('turns validation errors into ApiError with issues', async () => {
    const body = { detail: { message: 'Config is not valid', errors: [{ loc: 'buyer', msg: 'required', type: 'missing' }] } }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), { status: 422 }))
    const err = await api('/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, message: 'Config is not valid' })
    expect((err as ApiError).issues).toHaveLength(1)
  })
  it('gives a plain message when the service is down', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('fail'))
    await expect(api('/x')).rejects.toMatchObject({ status: 0 })
  })
})
