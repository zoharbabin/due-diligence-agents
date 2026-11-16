import { useState } from 'react'
import type { Doctor } from '../api/types'
import { Button, Card } from './ui'
import { CliDownload } from './CliDownload'
import { KeyForm } from './KeyForm'

/** Shown until the app can reach a model. */
export function SetupCard({ doctor, onChange }: { doctor: Doctor; onChange: () => void }) {
  const [connected, setConnected] = useState(false)

  if (!doctor.cli.found) return <CliDownload onDone={onChange} />

  return (
    <Card className="space-y-3">
      <h2 className="font-semibold text-slate-900">Connect a model</h2>
      {doctor.provider === 'anthropic' ? (
        <KeyForm onSaved={(r) => setConnected(r.ok)} />
      ) : (
        <p className="text-sm text-slate-600">
          Provider: <strong>{doctor.provider}</strong>. Set one of {doctor.credential_env.join(', ')} before starting the app.
        </p>
      )}
      {connected && <Button onClick={onChange}>Continue</Button>}
    </Card>
  )
}
