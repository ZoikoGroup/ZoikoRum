import QRCode from 'qrcode'
import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, Field } from '../components/ui'

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
  const { user, reloadUser, stepUp } = useAuth()
  const navigate = useNavigate()
  const required = (useLocation().state as { required?: boolean } | null)?.required || user?.mfaRequired
  const [setup, setSetup] = useState<{ secret: string; otpauthUri: string } | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  if (!user) return null

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
      await authApi.verifyMfa(code)
      await stepUp(code) // upgrade this session to MFA strength right away
      const me = await reloadUser()
      setSetup(null)
      setCode('')
      if (required && me) navigate(`/app/${me.defaultDashboard}`, { replace: true })
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
          Your role ({user.platformRoles.length ? 'platform staff' : 'organization admin'}) requires two-step verification
          before you can continue.
        </div>
      )}
      <ErrorAlert error={error} />
      <section className="card panel" style={{ maxWidth: 640 }}>
        <h2>Two-step verification</h2>
        {user.mfaEnabled ? (
          <p><span className="badge green">On</span> Signing in and sensitive actions (signing contracts, releasing funds,
            changing roles) ask for a code from your authenticator app.</p>
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
    </>
  )
}
