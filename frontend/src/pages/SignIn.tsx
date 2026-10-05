import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field, PasswordInput } from '../components/ui'

/** One sign-in for every role. The backend tells us which dashboard to open. */
export default function SignIn() {
  const { accept } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needsCode, setNeedsCode] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await authApi.login(email, password, needsCode ? code : undefined)
      accept(result)
      navigate(from && from.startsWith('/app') ? from : `/app/${result.user.defaultDashboard}`, { replace: true })
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
      <h1>Sign in to Zoikorum</h1>
      <p className="sub">Buyers, professionals, firms, enterprise teams and staff all sign in here.</p>
      <ErrorAlert error={error} />
      <form onSubmit={submit} noValidate>
        {!needsCode ? (
          <>
            <Field label="Work email" id="email">
              <input id="email" className="input" type="email" autoComplete="email" required
                value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            </Field>
            <Field label="Password" id="password">
              <PasswordInput id="password" autoComplete="current-password" value={password} onChange={setPassword} />
            </Field>
            <p className="small" style={{ textAlign: 'right', marginTop: -6 }}>
              <Link to="/forgot-password">Forgot password?</Link>
            </p>
          </>
        ) : (
          <>
            <div className="alert alert-info">Two-step verification is on for this account.</div>
            <Field label="6-digit code from your authenticator app" id="totp">
              <input id="totp" className="input code-input" inputMode="numeric" autoComplete="one-time-code"
                maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
            </Field>
          </>
        )}
        <button className="btn btn-primary btn-block" disabled={busy || !email || !password || (needsCode && code.length !== 6)}>
          {busy ? 'Signing in…' : needsCode ? 'Verify and sign in' : 'Sign in'}
        </button>
        {needsCode && (
          <button type="button" className="btn btn-ghost btn-block" onClick={() => { setNeedsCode(false); setCode('') }}>
            Use a different account
          </button>
        )}
      </form>
      <div className="divider">New to Zoikorum?</div>
      <div className="row">
        <Link className="btn btn-secondary" style={{ flex: 1 }} to="/join">Create an account</Link>
        <Link className="btn btn-secondary" style={{ flex: 1 }} to="/join?type=PROFESSIONAL">Join as a Professional</Link>
      </div>
    </AuthLayout>
  )
}
