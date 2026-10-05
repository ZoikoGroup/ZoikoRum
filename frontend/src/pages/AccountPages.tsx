import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field } from '../components/ui'

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<{ message: string; resetToken: string | null } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setSent(await authApi.forgotPassword(email))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Reset your password</h1>
      <p className="sub">Enter your account email and we'll send you a reset link. The link works once and expires in 30 minutes.</p>
      <ErrorAlert error={error} />
      {sent ? (
        <>
          <div className="alert alert-success" role="status">{sent.message}</div>
          {sent.resetToken && (
            <div className="alert alert-warn">
              Development mode (no email provider yet):{' '}
              <Link to={`/reset-password?token=${encodeURIComponent(sent.resetToken)}`}>open the reset link</Link>
            </div>
          )}
        </>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" id="email">
            <input id="email" className="input" type="email" autoComplete="email" value={email}
              onChange={(e) => setEmail(e.target.value)} autoFocus required />
          </Field>
          <button className="btn btn-primary btn-block" disabled={busy || !email}>{busy ? 'Sending…' : 'Send reset link'}</button>
        </form>
      )}
      <p className="auth-foot"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  )
}

export function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const mismatch = confirm.length > 0 && confirm !== password

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await authApi.resetPassword(token, password)
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Choose a new password</h1>
      <p className="sub">For your security, every device signed in to this account will be signed out.</p>
      <ErrorAlert error={error} />
      {!token && <div className="alert alert-error">This reset link is missing its token. <Link to="/forgot-password">Request a new one</Link>.</div>}
      <form onSubmit={submit}>
        <Field label="New password" id="pw" hint="At least 12 characters.">
          <input id="pw" className="input" type="password" autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm new password" id="pw2" error={mismatch ? 'Passwords do not match.' : undefined}>
          <input id="pw2" className="input" type="password" autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} aria-invalid={mismatch} />
        </Field>
        <button className="btn btn-primary btn-block" disabled={busy || !token || password.length < 12 || password !== confirm}>
          {busy ? 'Saving…' : 'Set new password'}
        </button>
      </form>
    </AuthLayout>
  )
}

export function ConfirmEmail() {
  const [params] = useSearchParams()
  const { user, reloadUser } = useAuth()
  const [state, setState] = useState<'working' | 'done' | 'error'>('working')
  const [error, setError] = useState<unknown>(null)
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    authApi
      .confirmEmail(params.get('token') ?? '')
      .then(async () => {
        setState('done')
        if (user) await reloadUser()
      })
      .catch((err) => {
        setError(err)
        setState('error')
      })
  }, [params, user, reloadUser])

  return (
    <AuthLayout>
      <h1>Confirm your email</h1>
      {state === 'working' && <p className="muted">Confirming…</p>}
      {state === 'done' && (
        <>
          <div className="alert alert-success" role="status">Your email is confirmed.</div>
          <Link className="btn btn-primary" to={user ? `/app/${user.defaultDashboard}` : '/login'}>Continue</Link>
        </>
      )}
      {state === 'error' && <ErrorAlert error={error} />}
    </AuthLayout>
  )
}
