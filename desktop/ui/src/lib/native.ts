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

/** Keep provider settings in the OS keychain. Returns false in a browser, where nothing can be saved. */
export async function saveProviderEnv(values: Record<string, string>): Promise<boolean> {
  const t = (window as unknown as TauriWindow).__TAURI_INTERNALS__
  if (!t) return false
  await t.invoke('save_provider_env', { values })
  return true
}

export interface UpdateInfo {
  version: string
  notes: string | null
}

/** Newer signed build, or null (also null in a browser and when the update server is unreachable). */
export async function checkForUpdate(): Promise<UpdateInfo | null> {
  const t = (window as unknown as TauriWindow).__TAURI_INTERNALS__
  if (!t) return null
  try {
    return ((await t.invoke('check_for_update')) as UpdateInfo | null) ?? null
  } catch {
    return null
  }
}

/** Downloads, installs and restarts the app. Resolves only if it fails. */
export async function installUpdate(): Promise<void> {
  const t = (window as unknown as TauriWindow).__TAURI_INTERNALS__
  if (t) await t.invoke('install_update')
}
