import { useEffect, useState } from 'react'
import { passkeyApi, type Passkey } from '../api/passkeys'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, useStepUp } from './ui'

export default function PasskeySettings() {
  const { accept, reloadUser } = useAuth()
  const [keys, setKeys] = useState<Passkey[]>([])
  const [label, setLabel] = useState('My passkey')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const step = useStepUp(setError)
  useEffect(() => { let live = true; passkeyApi.list().then(k => { if (live) setKeys(k) }).catch(e => { if (live) setError(e) }); return () => { live = false } }, [])
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(null)
    await step.run(async () => {
      try { await action(); setKeys(await passkeyApi.list()); await reloadUser() } finally { setBusy(false) }
    })
  }
  return <section className="card panel" style={{ maxWidth: 640 }}><h2>Passkeys</h2>
    <p>Use your device’s fingerprint, face or security key to sign in and verify sensitive actions.</p><ErrorAlert error={error} />
    <label htmlFor="passkey-name">Passkey name</label><input id="passkey-name" className="input" value={label} maxLength={100} onChange={e => setLabel(e.target.value)} />
    <button className="btn btn-primary" disabled={busy || !label.trim()} onClick={() => perform(async () => { if (keys.length) accept(await passkeyApi.authenticate(true)); await passkeyApi.register(label.trim()) })}>Add passkey</button>
    <button className="btn btn-secondary" disabled={busy || !keys.length} onClick={() => perform(async () => { accept(await passkeyApi.authenticate(true)) })}>Verify with passkey</button>
    {step.modal}
    <ul>{keys.map(k => <li key={k.id}>{k.label} <button className="btn btn-ghost" disabled={busy} onClick={() => perform(async () => { accept(await passkeyApi.authenticate(true)); await passkeyApi.remove(k.id) })}>Remove</button></li>)}</ul>
  </section>
}
