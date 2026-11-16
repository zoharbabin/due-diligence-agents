import { useEffect, useState } from 'react'
import { checkForUpdate, installUpdate, type UpdateInfo } from '../lib/native'
import { Banner, Button } from './ui'

/** Offers a newer signed version. Installing stops the local service, so a running review must be resumed after. */
export function UpdateBanner() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    void checkForUpdate().then((found) => live && setUpdate(found))
    return () => {
      live = false
    }
  }, [])

  async function install() {
    setBusy(true)
    setFailure(null)
    try {
      await installUpdate()
    } catch (err) {
      setFailure(typeof err === 'string' ? err : 'The update failed. Try again later.')
      setBusy(false)
    }
  }

  if (!update) return null
  return (
    <div className="mb-6 space-y-2">
      <Banner tone="info">
        <div className="flex items-center justify-between gap-4">
          <span>
            Version {update.version} is available. The app restarts to install it. A running review stops and can be resumed.
          </span>
          <Button onClick={install} busy={busy}>
            Update and restart
          </Button>
        </div>
      </Banner>
      {failure && <Banner tone="error">{failure}</Banner>}
    </div>
  )
}
