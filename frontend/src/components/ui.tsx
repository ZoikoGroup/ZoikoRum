import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const SITE = 'https://zoikorum.com'

/** Public header - same navigation as zoikorum.com. */
export function SiteHeader() {
  const { user } = useAuth()
  return (
    <>
      <header className="site-header">
        <div className="inner">
          <a className="logo" href={SITE} aria-label="Zoikorum home">
            <img src="/logo.png" alt="Zoikorum" />
          </a>
          <nav aria-label="Primary">
            <a href={`${SITE}/#platform`}>Platform</a>
            <a href={`${SITE}/#contracts`}>Contracts &amp; Controls</a>
            <a href={`${SITE}/#payments`}>Payment Protection</a>
            <a href={`${SITE}/#solutions`}>Solutions</a>
            <Link to="/join?type=PROFESSIONAL">Professionals</Link>
          </nav>
          <div className="actions">
            {user ? (
              <Link className="btn btn-primary btn-sm" to={`/app/${user.defaultDashboard}`}>Go to dashboard</Link>
            ) : (
              <>
                <Link className="btn btn-ghost btn-sm" to="/login">Sign In</Link>
                <Link className="btn btn-primary btn-sm" to="/enterprise">Enterprise Access</Link>
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
