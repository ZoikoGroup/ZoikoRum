import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PASSWORD_LABEL, passwordScore } from '../lib/password'

/** Public header. Every link stays inside the Zoikorum app. */
export function SiteHeader() {
  const { user } = useAuth()
  return (
    <>
      <header className="site-header">
        <div className="inner">
          <Link className="logo" to="/" aria-label="Zoikorum home">
            <img src="/logo.png" alt="Zoikorum" />
          </Link>
          <nav aria-label="Primary">
            <Link to="/professionals">Find professionals</Link>
            <Link to="/join?type=PROFESSIONAL">For professionals</Link>
            <Link to="/enterprise">Enterprise</Link>
          </nav>
          <div className="actions">
            {user ? (
              <Link className="btn btn-primary btn-sm" to={`/app/${user.defaultDashboard}`}>Go to dashboard</Link>
            ) : (
              <>
                <Link className="btn btn-ghost btn-sm" to="/login">Sign In</Link>
                <Link className="btn btn-primary btn-sm" to="/join">Get started</Link>
              </>
            )}
          </div>
        </div>
      </header>
      <div className="trust-strip" aria-label="Platform guarantees">
        <span>Identity Verified</span><span>Contract Required</span><span>Escrow Protected</span><span>Audit Ready</span>
      </div>
    </>
  )
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="inner">
        <nav aria-label="Footer">
          <Link to="/professionals">Find professionals</Link>
          <Link to="/join?type=PROFESSIONAL">Join as a professional</Link>
          <Link to="/enterprise">Enterprise</Link>
          <Link to="/legal/terms">Terms</Link>
          <Link to="/legal/privacy">Privacy</Link>
        </nav>
        <p className="small">
          Zoikorum provides marketplace infrastructure, verification, contracting facilitation and payment protection.
          Professional services are delivered by independent professionals and firms.
        </p>
      </div>
    </footer>
  )
}

const DEFAULT_POINTS = [
  'Verification-first onboarding with Trust Tiers A, B and C',
  'Contract-required engagements with scope versioning',
  'Escrow-protected payments released on acceptance',
  'Every action recorded in an audit-grade ledger',
]

export function AuthLayout({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <>
      <SiteHeader />
      <main className="auth-wrap">
        <section className="card auth-card">{children}</section>
        <aside className="card auth-aside" aria-label="Why Zoikorum">
          {aside ?? (
            <>
              <h3>Governed from start to finish</h3>
              <ul>
                {DEFAULT_POINTS.map((p) => (
                  <li key={p}><span className="check" aria-hidden>✓</span><span>{p}</span></li>
                ))}
              </ul>
              <p className="small muted" style={{ marginTop: 20 }}>
                AI assists. Policy constrains. Humans decide.
              </p>
            </>
          )}
        </aside>
      </main>
    </>
  )
}

/** Shows an API error in plain language, with the support reference. */
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null
  const msg = error instanceof Error ? error.message : 'Something went wrong. Please try again.'
  const ref = error instanceof ApiError ? error.correlationId : undefined
  return (
    <div className="alert alert-error" role="alert">
      {msg}
      {error instanceof ApiError && ['APPROVAL_REQUIRED', 'EXCEPTION_REQUIRED'].includes(error.code) &&
        <Link to={`/app/policies?${new URLSearchParams({ orgId: String(error.extra?.organizationId || ''),
          tab: error.code === 'EXCEPTION_REQUIRED' ? 'exceptions' : 'approvals',
          subjectType: String(error.extra?.subjectType || ''), subjectId: String(error.extra?.subjectId || ''),
          action: String(error.extra?.action || '') })}`}>View policy authorisation</Link>}
      {ref && <span className="ref">Reference: {ref}</span>}
    </div>
  )
}

export function Field(props: {
  label: string
  id: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="field">
      <label htmlFor={props.id}>{props.label}</label>
      {props.children}
      {props.error ? <span className="error" id={`${props.id}-err`}>{props.error}</span>
        : props.hint && <span className="hint" id={`${props.id}-hint`}>{props.hint}</span>}
    </div>
  )
}

/** Password strength meter (Onboarding s.6). Text + bar, never colour alone. */
export function PasswordStrength({ value }: { value: string }) {
  if (!value) return null
  const score = passwordScore(value)
  const label = PASSWORD_LABEL[score]
  return (
    <div className={`pw-strength s${score}`} aria-live="polite">
      <span className="pw-bar"><span style={{ width: `${(score + 1) * 25}%` }} /></span>
      <span className="small">Password strength: <strong>{label}</strong></span>
    </div>
  )
}

/** Password field with a show/hide (eye) toggle. */
export function PasswordInput(props: {
  id: string
  value: string
  onChange: (value: string) => void
  autoComplete: 'current-password' | 'new-password'
  invalid?: boolean
}) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="password-wrap">
      <input id={props.id} className="input" type={visible ? 'text' : 'password'} autoComplete={props.autoComplete}
        value={props.value} onChange={(e) => props.onChange(e.target.value)} aria-invalid={props.invalid} />
      <button type="button" className="eye" onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} title={visible ? 'Hide password' : 'Show password'}>
        {visible ? (
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><path fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2.5 12 2.5 12s3.5 7 9.5 7a9.7 9.7 0 0 0 5.4-1.6" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><path fill="none" stroke="currentColor" strokeWidth="1.8" d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z" /><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>
        )}
      </button>
    </div>
  )
}

/** Asks for the authenticator code before a sensitive action (step-up MFA). */
export function StepUpModal({ open, onDone, onCancel }: { open: boolean; onDone: () => void; onCancel: () => void }) {
  const { stepUp } = useAuth()
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  if (!open) return null

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await stepUp(code)
      setCode('')
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="stepup-title">
      <form className="card modal" onSubmit={submit}>
        <h2 id="stepup-title">Confirm it's you</h2>
        <p className="muted">This action needs a fresh confirmation. Enter the 6-digit code from your authenticator app.</p>
        <ErrorAlert error={error} />
        <Field label="Authentication code" id="stepup-code">
          <input id="stepup-code" className="input code-input" inputMode="numeric" autoComplete="one-time-code"
            maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
        </Field>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || code.length !== 6}>{busy ? 'Checking…' : 'Confirm'}</button>
        </div>
      </form>
    </div>
  )
}

/** Runs an API action; if the backend asks for step-up MFA, prompts for the code and retries once. */
export function useStepUp(onError: (err: unknown) => void) {
  const [pending, setPending] = useState<null | (() => Promise<void>)>(null)
  async function run(action: () => Promise<void>) {
    try {
      await action()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'STEP_UP_REQUIRED') setPending(() => action)
      else onError(err)
    }
  }
  const modal = (
    <StepUpModal
      open={!!pending}
      onCancel={() => setPending(null)}
      onDone={async () => {
        const action = pending
        setPending(null)
        if (!action) return
        try {
          await action()
        } catch (err) {
          onError(err)
        }
      }}
    />
  )
  return { run, modal }
}
