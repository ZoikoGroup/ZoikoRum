import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field, PasswordInput } from '../components/ui'
import { passkeyCancelled, passkeysSupported, signWithPasskey } from '../lib/passkeys'
import { PORTAL, signInHref } from '../portal'
import { SsoSignInOptions } from '../components/SingleSignOn'
import { Icon } from '../components/AuthIcons'
import { dashboardPath } from '../staffRoutes'
import { safeNextPath } from '../auth/guards'

/** Two sign-in pages: /login for customers, professionals, firms and enterprise teams, and /staff/login for Zoikorum
    staff. The server holds each account to its own page; the backend says which dashboard to open. */
export default function SignIn({ staff = false }: { staff?: boolean }) {
  const { accept } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const from = params.get('next') || (location.state as { from?: string } | null)?.from
  const safeNext = safeNextPath(from)
  // Carried to the sign-up page too, so a new account lands on the same page (e.g. a request to one professional).
  const joinNext = safeNext ? `next=${encodeURIComponent(safeNext)}` : ''

  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? params.get('email') ?? '')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needsCode, setNeedsCode] = useState(false)
  const [remember, setRemember] = useState(true)
  const [useRecovery, setUseRecovery] = useState(false)  // lost authenticator: a one-time recovery code
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  /** The other sign-in page: on this app, or on the other app's address (separate staff and customer apps). */
  const other = signInHref(!staff)
  function goToOtherSignIn() {
    if (/^https?:/.test(other)) window.location.assign(email ? `${other}?email=${encodeURIComponent(email)}` : other)
    else navigate(other, { state: { email } })
  }

  /** Sign in with a passkey on this device: no email, password or code to type. */
  async function withPasskey() {
    setBusy(true)
    setError(null)
    try {
      const credential = await signWithPasskey(await authApi.passkeyLoginOptions())
      const result = await authApi.passkeyLogin(credential, staff ? 'staff' : 'customer')
      accept(result)
      navigate(result.user.mfaRequired ? '/app/security' : safeNext ?? dashboardPath(result.user), { replace: true })
    } catch (err) {
      if (!passkeyCancelled(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await authApi.login(email, password, needsCode && !useRecovery ? code : undefined,
        needsCode && useRecovery ? code.trim().toLowerCase() : undefined, staff ? 'staff' : 'customer', remember)
      accept(result)
      navigate(result.user.mfaRequired ? '/app/security' : safeNext ?? dashboardPath(result.user), { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'MFA_REQUIRED') {
        setNeedsCode(true) // password was right; ask for the authenticator code
      } else {
        setError(err)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      {staff ? <>
        <span className="badge" style={{ marginBottom: 8 }}>Staff</span>
        <h1>Zoikorum staff sign-in</h1>
        <p className="sub">For the Zoikorum team only: operations, compliance, disputes, finance and administration.
          Two-step verification is required.</p>
      </> : <>
        <img className="auth-form-logo" src="/logo.png" alt="Zoikorum" />
        <h1>Welcome back!</h1>
        <p className="sub">Sign in to your Zoikorum account.</p>
      </>}
      <ErrorAlert error={error} />
      {error instanceof ApiError && (error.code === 'USE_STAFF_SIGN_IN' || error.code === 'NOT_STAFF_ACCOUNT') && (
        // Wrong sign-in page for this account: one click to the right one, with the email carried over.
        <button type="button" className="btn btn-secondary btn-block" style={{ marginBottom: 16 }}
          onClick={() => { setError(null); goToOtherSignIn() }}>
          {staff ? 'Continue to the main sign-in' : 'Continue to staff sign-in'}
        </button>
      )}
      {!needsCode && !staff && <><SsoSignInOptions email={email} /><div className="divider">or sign in with email</div></>}
      <form onSubmit={submit} noValidate>
        {!needsCode ? (
          <>
            <Field label="Work email address" id="email">
              <span className="with-icon"><span className="ico"><Icon name="mail" /></span>
                <input id="email" className="input" type="email" autoComplete="email" required placeholder="name@company.com"
                  value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></span>
            </Field>
            <Field label="Password" id="password">
              <span className="with-icon"><span className="ico"><Icon name="lock" /></span>
                <PasswordInput id="password" autoComplete="current-password" value={password} onChange={setPassword} /></span>
            </Field>
            <div className="row-between">
              <label className="checkbox" style={{ margin: 0, alignItems: 'center' }}>
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                <span>Remember me for 30 days</span>
              </label>
              <Link to="/forgot-password">Forgot password?</Link>
            </div>
          </>
        ) : (
          <>
            <div className="alert alert-info">Two-step verification is on for this account.</div>
            {useRecovery ? (
              <Field label="Recovery code (looks like 1a2b3-c4d5e-6f7a8-b9c0d)" id="recovery" hint="Each code works once. Set up your authenticator again after signing in.">
                <input id="recovery" className="input code-input" autoComplete="off" maxLength={23} value={code}
                  onChange={(e) => setCode(e.target.value.replace(/[^0-9a-fA-F-]/g, ''))} autoFocus />
              </Field>
            ) : (
              <Field label="6-digit code from your authenticator app" id="totp">
                <input id="totp" className="input code-input" inputMode="numeric" autoComplete="one-time-code"
                  maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
              </Field>
            )}
            <button type="button" className="link-btn small" style={{ display: 'inline', padding: 0, marginBottom: 12 }}
              onClick={() => { setUseRecovery(!useRecovery); setCode('') }}>
              {useRecovery ? 'Use my authenticator app instead' : 'Lost your phone? Use a recovery code'}</button>
          </>
        )}
        <button className="btn btn-primary btn-block" disabled={busy || !email || !password || (needsCode && code.length !== (useRecovery ? 23 : 6))}>
          {busy ? 'Signing in…' : needsCode ? 'Verify and sign in' : 'Log In'}
        </button>
        {needsCode && (
          <button type="button" className="btn btn-ghost btn-block" onClick={() => { setNeedsCode(false); setUseRecovery(false); setCode('') }}>
            Use a different account
          </button>
        )}
      </form>
      {!needsCode && !staff && (
        <p className="auth-foot">New to Zoikorum? <Link to={joinNext ? `/join?${joinNext}` : '/join'}>Register</Link></p>
      )}
      {!needsCode && passkeysSupported() && (
        <button type="button" className="btn btn-secondary btn-block" style={{ marginTop: 12 }} disabled={busy} onClick={withPasskey}>
          Sign in with a passkey
        </button>
      )}
      {staff ? (
        <p className="auth-foot">Not Zoikorum staff? <a href={other} onClick={(e) => { e.preventDefault(); goToOtherSignIn() }}>Sign in here</a></p>
      ) : <>
        {PORTAL === 'both' && <p className="auth-foot small">Zoikorum staff? <Link to="/staff/login">Staff sign-in</Link></p>}
      </>}
    </AuthLayout>
  )
}
