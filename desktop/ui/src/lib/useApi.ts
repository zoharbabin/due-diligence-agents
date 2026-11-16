import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'

export interface Loaded<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

/** Load data once per key. Ignores results that arrive after the key changed. */
export function useLoad<T>(load: () => Promise<T>, key: string): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  })
  const [tick, setTick] = useState(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, [key])
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true }))
    run().then(
      (data) => live && setState({ data, error: null, loading: false }),
      (e: unknown) => live && setState({ data: null, error: e instanceof ApiError ? e.message : String(e), loading: false }),
    )
    return () => {
      live = false
    }
  }, [run, tick])
  return { ...state, reload: () => setTick((t) => t + 1) }
}
