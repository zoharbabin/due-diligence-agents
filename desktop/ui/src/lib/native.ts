/** Thin bridge to the desktop shell. In a browser these return null and the UI falls back to text input. */
interface TauriWindow {
  __TAURI_INTERNALS__?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> }
}

export function isDesktop(): boolean {
  return Boolean((window as unknown as TauriWindow).__TAURI_INTERNALS__)
}

export async function pickFolder(): Promise<string | null> {
  const t = (window as unknown as TauriWindow).__TAURI_INTERNALS__
  if (!t) return null
  const result = await t.invoke('plugin:dialog|open', { options: { directory: true, multiple: false } })
  return typeof result === 'string' ? result : null
}
