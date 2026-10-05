import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { authApi, ROLE_LABEL } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert } from '../components/ui'

/** Welcome message after sign-up and the email-confirmation reminder, shown on every dashboard. */
export function AccountAlerts() {
  const { user } = useAuth()
  const welcome = (useLocation().state as { welcome?: boolean; confirmToken?: string } | null) ?? {}
  if (!user) return null
  return (
    <>
      {welcome.welcome && <div className="alert alert-success" role="status">Welcome to Zoikorum, {user.displayName}. Your account is ready.</div>}
      {!user.emailConfirmed && (
        <div className="alert alert-warn">
          Please confirm your email address. Your profile cannot be published until it is confirmed.
          {welcome.confirmToken && (
            <> {' '}Development mode: <Link to={`/confirm-email?token=${encodeURIComponent(welcome.confirmToken)}`}>confirm now</Link>.</>
          )}
        </div>
      )}
    </>
  )
}

/** Account overview: roles held, and adding the Buyer/Professional role to the same account. */
export function AccountPage() {
  const { user, accept } = useAuth()
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  if (!user) return null
  const canAdd = (['BUYER', 'PROFESSIONAL'] as const).filter((p) => !user.personas.includes(p))

  async function add(type: 'BUYER' | 'PROFESSIONAL') {
    setBusy(true)
    setError(null)
    try {
      accept(await authApi.addAccountType(type))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>Profile &amp; roles</h1><p className="muted" style={{ margin: 0 }}>One ZoikoID, every role you hold.</p></div></div>
      <ErrorAlert error={error} />
      <section className="card panel">
        <ul className="checklist">
          <li><span>Name</span><strong>{user.displayName}</strong></li>
          <li><span>Email</span><span>{user.email} {user.emailConfirmed ? <span className="badge green">Confirmed</span> : <span className="badge warn">Not confirmed</span>}</span></li>
          <li><span>Country</span><span>{user.country}</span></li>
          {user.organizationName && <li><span>Organization</span><span>{user.organizationName}</span></li>}
          <li><span>Two-step verification</span>{user.mfaEnabled ? <span className="badge green">On</span> : <Link to="/app/security">Turn on</Link>}</li>
        </ul>
      </section>
      <section className="card panel">
        <h2>Your roles</h2>
        <div className="badges" style={{ marginBottom: 16 }}>
          {[...user.personas, ...user.platformRoles].map((r) => <span key={r} className="badge green">{ROLE_LABEL[r] ?? r}</span>)}
        </div>
        {canAdd.length > 0 && (
          <>
            <p className="muted small">You can use the same account on both sides of the marketplace.</p>
            <div className="row">
              {canAdd.map((p) => (
                <button key={p} className="btn btn-secondary" disabled={busy} onClick={() => add(p)}>
                  Also use Zoikorum as a {ROLE_LABEL[p]}
                </button>
              ))}
            </div>
          </>
        )}
      </section>
    </>
  )
}

export function ForbiddenPage() {
  const { user } = useAuth()
  const needed = ((useLocation().state as { needed?: string[] } | null)?.needed ?? []).map((r) => ROLE_LABEL[r] ?? r)
  return (
    <section className="card panel" style={{ maxWidth: 560 }}>
      <h1>You don't have access to this area</h1>
      <p className="muted">
        {needed.length ? `It is available to ${needed.join(' or ')} accounts.` : 'Your account roles do not include this area.'}{' '}
        If you think this is a mistake, ask your organization admin or contact support.
      </p>
      {user && <Link className="btn btn-primary" to={`/app/${user.defaultDashboard}`}>Back to your dashboard</Link>}
    </section>
  )
}
