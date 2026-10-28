import QRCode from 'qrcode'
import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { tokens } from '../api/client'
import { authApi, type Passkey } from '../api/auth'
import { createPasskey, passkeyCancelled, passkeysSupported } from '../lib/passkeys'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, Field, useStepUp } from '../components/ui'
import { dashboardPath } from '../staffRoutes'

/** QR code for the authenticator app, drawn in the browser: the secret never leaves this page. */
function SetupQr({ uri }: { uri: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    QRCode.toDataURL(uri, { margin: 1, width: 220, errorCorrectionLevel: 'M' }).then((url) => { if (live) setSrc(url) }).catch(() => setSrc(null))
    return () => { live = false }
  }, [uri])
  return <div className="qr-box">{src ? <img src={src} width={220} height={220} alt="QR code to add Zoikorum to your authenticator app" /> : <span className="muted small">Preparing QR code…</span>}</div>
}

/** Two-step verification (TOTP). Required for staff, Firm Admins and Enterprise Admins. */
export default function Security() {
  const { user, reloadUser } = useAuth()
  const navigate = useNavigate()
  const required = (useLocation().state as { required?: boolean } | null)?.required || user?.mfaRequired
  const [setup, setSetup] = useState<{ secret: string; otpauthUri: string } | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [codes, setCodes] = useState<string[] | null>(null)  // shown once, right after they are made
  const confirm = useStepUp(setError)  // asks for the authenticator code when the server wants a fresh confirmation
  if (!user) return null

  function replaceCodes() {
    setError(null)
    confirm.run(async () => setCodes((await authApi.newRecoveryCodes()).recoveryCodes))
  }

  async function start() {
    setError(null)
    try {
      setSetup(await authApi.enrollMfa())
    } catch (err) {
      setError(err)
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { recoveryCodes, tokens: upgraded } = await authApi.verifyMfa(code)
      setCodes(recoveryCodes)  // show them even if the step below fails: they are already active
      // The server already upgraded this sign-in to a two-step session (the same code cannot be used twice).
      if (upgraded) { tokens.set(upgraded); window.dispatchEvent(new Event('zk:session-upgraded')) }
      await reloadUser()
      setSetup(null)
      setCode('')
      setCodes(recoveryCodes)  // the user continues after saving them
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>Security</h1><p className="muted" style={{ margin: 0 }}>Protect your account and the engagements it controls.</p></div></div>
      {required && !user.mfaEnabled && (
        <div className="alert alert-warn">
          Your role ({user.platformRoles.length ? 'platform staff' : user.personas.includes('FIRM_ADMIN') ? 'firm admin' : 'organization admin'}) requires
          two-step verification. Every other section stays locked and sends you back here until you turn it on below.
        </div>
      )}
      <ErrorAlert error={error} />
      {confirm.modal}
      <section className="card panel" style={{ maxWidth: 640 }}>
        <h2>Two-step verification</h2>
        {codes ? (
          <div>
            <div className="alert alert-warn" role="status"><strong>Save these recovery codes now.</strong> If you lose your phone,
              each code signs you in once instead of the authenticator. They will not be shown again.</div>
            <ul className="recovery-codes" aria-label="Recovery codes" style={{ columns: 2, fontFamily: 'monospace', fontSize: 16, padding: 0, listStyle: 'none' }}>
              {codes.map((c) => <li key={c}>{c}</li>)}</ul>
            <div className="row">
              <button type="button" className="btn btn-secondary" onClick={() => navigator.clipboard?.writeText(codes.join('\n')).catch(() => {})}>Copy</button>
              <button type="button" className="btn btn-primary" onClick={() => { setCodes(null); if (required || user.platformRoles.length) navigate(dashboardPath(user), { replace: true }) }}>
                I have saved them</button>
            </div>
          </div>
        ) : user.mfaEnabled ? (
          <>
            <p><span className="badge green">On</span> Signing in and sensitive actions (signing contracts, releasing funds,
              changing roles) ask for a code from your authenticator app.</p>
            <p className="muted small">Lost your recovery codes? Make new ones; the old ones stop working.</p>
            <button type="button" className="btn btn-secondary btn-sm" onClick={replaceCodes}>Make new recovery codes</button>
          </>
        ) : !setup ? (
          <>
            <p className="muted">Use an authenticator app such as Google Authenticator, Microsoft Authenticator or 1Password.</p>
            <button className="btn btn-primary" onClick={start}>Set up two-step verification</button>
          </>
        ) : (
          <form onSubmit={verify}>
            <p><strong>1.</strong> Open your authenticator app, tap <strong>+</strong> → <strong>Scan a QR code</strong>, and scan this:</p>
            <SetupQr uri={setup.otpauthUri} />
            <details className="small" style={{ marginTop: 8 }}>
              <summary>Can't scan? Enter the setup key instead</summary>
              <div className="secret" aria-label="Setup key" style={{ marginTop: 8 }}>{setup.secret}</div>
              <p className="muted" style={{ margin: '8px 0 0' }}>
                On a phone with an authenticator installed you can also <a href={setup.otpauthUri}>open the setup link</a>.
              </p>
            </details>
            <p style={{ marginTop: 16 }}><strong>2.</strong> Enter the 6-digit code the app shows:</p>
            <Field label="Authentication code" id="mfa-code">
              <input id="mfa-code" className="input code-input" inputMode="numeric" autoComplete="one-time-code"
                maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
            </Field>
            <button className="btn btn-primary" disabled={busy || code.length !== 6}>{busy ? 'Verifying…' : 'Turn on'}</button>
          </form>
        )}
      </section>
      <PasskeysSection />
    </>
  )
}

/** Passkeys: sign in with this device's fingerprint, face or PIN. Adding one needs your password. */
function PasskeysSection() {
  const [rows, setRows] = useState<Passkey[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const load = () => authApi.passkeys().then(setRows).catch(setError)
  useEffect(() => { load() }, [])
  const supported = passkeysSupported()

  async function add(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const options = await authApi.passkeyOptions(password)
      const credential = await createPasskey(options)
      await authApi.addPasskey(name.trim() || 'Passkey', credential)
      setAdding(false)
      setPassword('')
      setName('')
      setNotice('Passkey added. Next time, choose "Sign in with a passkey".')
      await load()
    } catch (err) {
      if (!passkeyCancelled(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }
  async function remove(pk: Passkey) {
    if (!confirm(`Remove the passkey "${pk.name}"? You will not be able to sign in with it any more.`)) return
    try { await authApi.removePasskey(pk.id); setNotice(`Passkey "${pk.name}" removed.`); await load() } catch (err) { setError(err) }
  }

  return (
    <section className="card panel" style={{ maxWidth: 640 }}>
      <h2>Passkeys</h2>
      <p className="muted">Sign in with your fingerprint, face or device PIN instead of your password and code. A passkey only
        works on Zoikorum, so it cannot be phished. It also confirms sensitive actions.</p>
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      {rows && rows.length > 0 && (
        <table className="data"><thead><tr><th>Name</th><th>Added</th><th>Last used</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{rows.map((pk) => (
            <tr key={pk.id}>
              <td><strong>{pk.name}</strong>{pk.backedUp && <div className="muted small">Synced to your other devices</div>}</td>
              <td className="small">{new Date(pk.createdAt).toLocaleDateString()}</td>
              <td className="small">{pk.lastUsedAt ? new Date(pk.lastUsedAt).toLocaleString() : 'Not yet'}</td>
              <td><button className="btn btn-ghost btn-sm" onClick={() => remove(pk)}>Remove</button></td>
            </tr>))}</tbody></table>
      )}
      {!supported ? <p className="muted small">This browser does not support passkeys.</p> : adding ? (
        <form onSubmit={add} style={{ marginTop: 12 }}>
          <Field label="Name for this passkey (optional)" id="pk-name" hint="So you can tell them apart, e.g. Work laptop">
            <input id="pk-name" className="input" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Your password" id="pk-password" hint="Adding a way to sign in needs your password.">
            <input id="pk-password" className="input" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <div className="row">
            <button className="btn btn-primary" disabled={busy || !password}>{busy ? 'Waiting for your device…' : 'Create passkey'}</button>
            <button type="button" className="btn btn-ghost" onClick={() => { setAdding(false); setPassword('') }}>Cancel</button>
          </div>
        </form>
      ) : <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => setAdding(true)}>Add a passkey</button>}
    </section>
  )
}
