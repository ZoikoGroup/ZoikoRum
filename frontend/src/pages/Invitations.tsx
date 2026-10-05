import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { firmApi, FIRM_ROLE_INFO, formatMoney, ORG_ROLE_INFO, orgApi, type Invitation } from '../api/orgs'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert } from '../components/ui'

type Kind = 'org' | 'firm'
const roleLabel = (r: string) => ORG_ROLE_INFO[r as keyof typeof ORG_ROLE_INFO]?.label ?? FIRM_ROLE_INFO[r as keyof typeof FIRM_ROLE_INFO]?.label ?? r

/** After joining, wait until the new workspace is on the token, then open it. */
function useJoinRedirect() {
  const { refreshClaims } = useAuth()
  const navigate = useNavigate()
  return async (kind: Kind) => {
    const want = kind === 'org' ? ['ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER'] : ['PROFESSIONAL', 'FIRM_ADMIN']
    const me = await refreshClaims((u) => u.personas.some((p) => want.includes(p)))
    navigate(kind === 'org' ? '/app/enterprise' : me?.personas.includes('FIRM_ADMIN') ? '/app/firm' : '/app/professional',
      { replace: true, state: { joined: true } })
  }
}

/** In-app inbox: invitations sent to the signed-in user's email. */
export function InvitationsPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<(Invitation & { kind: Kind })[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const goAfterJoin = useJoinRedirect()

  const load = useCallback(async () => {
    try {
      const [o, f] = await Promise.all([orgApi.myInvitations(), firmApi.myInvitations()])
      setItems([...o.map((i) => ({ ...i, kind: 'org' as const })), ...f.map((i) => ({ ...i, kind: 'firm' as const }))])
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])

  async function respond(inv: Invitation & { kind: Kind }, accept: boolean) {
    setBusy(inv.id)
    setError(null)
    try {
      const a = inv.kind === 'org' ? orgApi : firmApi
      if (accept) {
        await a.acceptById(inv.id)
        await goAfterJoin(inv.kind)
      } else {
        await a.decline(inv.id)
        await load()
      }
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="page-head"><div><h1>Invitations</h1>
        <p className="muted" style={{ margin: 0 }}>Invitations sent to {user?.email}.</p></div></div>
      <ErrorAlert error={error} />
      {user && !user.emailConfirmed && items.length > 0 && (
        <div className="alert alert-warn">Confirm your email address to accept invitations here, or use the link in the invitation email.</div>
      )}
      {loading ? <p className="muted">Loading…</p> : items.length === 0 ? (
        <section className="card panel"><p className="muted" style={{ margin: 0 }}>You have no pending invitations.</p></section>
      ) : items.map((i) => (
        <section key={i.id} className="card panel">
          <h2>{i.organizationName ?? i.firmName}</h2>
          <p className="muted small">{i.kind === 'org' ? 'Enterprise organization' : 'Professional firm'} · expires {new Date(i.expiresAt).toLocaleDateString()}</p>
          <div className="badges" style={{ marginBottom: 12 }}>{i.roles.map((r) => <span key={r} className="badge green">{roleLabel(r)}</span>)}</div>
          {i.spendLimit && <p className="small">Approval spend limit: <strong>{formatMoney(i.spendLimit)}</strong></p>}
          <div className="row">
            <button className="btn btn-primary" disabled={!!busy} onClick={() => respond(i, true)}>{busy === i.id ? 'Joining…' : 'Accept'}</button>
            <button className="btn btn-secondary" disabled={!!busy} onClick={() => respond(i, false)}>Decline</button>
          </div>
        </section>
      ))}
    </>
  )
}

/** Landing page for the link in an invitation email: /invite?kind=org|firm&token=... */
export function InviteLanding() {
  const [params] = useSearchParams()
  const kind: Kind = params.get('kind') === 'firm' ? 'firm' : 'org'
  const token = params.get('token') ?? ''
  const { user, loading } = useAuth()
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const goAfterJoin = useJoinRedirect()
  const here = `/invite?kind=${kind}&token=${encodeURIComponent(token)}`
  const tried = useRef(false)

  async function accept() {
    setBusy(true)
    setError(null)
    try {
      await (kind === 'org' ? orgApi.acceptByToken(token) : firmApi.acceptByToken(token))
      await goAfterJoin(kind)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  // Signed in already (e.g. came back from sign-in): accept right away, once.
  useEffect(() => {
    if (!loading && user && token && !tried.current) {
      tried.current = true
      accept()
    }
  })

  const what = kind === 'org' ? 'an enterprise organization' : 'a professional firm'
  return (
    <AuthLayout>
      <h1>You've been invited to Zoikorum</h1>
      <p className="sub">You were invited to join {what}. Sign in or create an account with the email address the invitation was sent to.</p>
      <ErrorAlert error={error} />
      {!token && <div className="alert alert-error">This invitation link is incomplete.</div>}
      {user ? (
        <>
          <p>Signed in as <strong>{user.email}</strong>.</p>
          <button className="btn btn-primary btn-block" disabled={busy || !token} onClick={accept}>{busy ? 'Joining…' : 'Accept invitation'}</button>
          <p className="auth-foot"><Link to="/app/invitations">See all my invitations</Link></p>
        </>
      ) : (
        <div className="row">
          <Link className="btn btn-primary" style={{ flex: 1 }} to={`/login?next=${encodeURIComponent(here)}`}>Sign in to accept</Link>
          <Link className="btn btn-secondary" style={{ flex: 1 }} to={`/join?next=${encodeURIComponent(here)}`}>Create an account</Link>
        </div>
      )}
    </AuthLayout>
  )
}
