import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi, ROLE_LABEL, type UserRoleFilter, type UserRow } from '../api/auth'
import { ErrorAlert, useStepUp } from '../components/ui'

const ROLE_FILTERS: { value: UserRoleFilter; label: string }[] = [
  { value: '', label: 'All roles' }, { value: 'BUYER', label: 'Customers' }, { value: 'PROFESSIONAL', label: 'Professionals' },
  { value: 'FIRM_ADMIN', label: 'Firm admins' }, { value: 'ENTERPRISE_ADMIN', label: 'Enterprise admins' },
  { value: 'ENTERPRISE_MEMBER', label: 'Enterprise members' }, { value: 'STAFF', label: 'Staff' },
]
const STATUS_TONE: Record<string, string> = { ACTIVE: 'green', SUSPENDED: 'warn', DELETED: '' }
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '—')

/** Platform Admin / Trust & Safety: every account, searchable. Restricting an account is done through an
 *  evidence-based safety case (four-eyes), never directly from this list. Every read is recorded in the audit log. */
export default function UsersAdmin() {
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<UserRoleFilter>('')
  const [status, setStatus] = useState('')
  const [rows, setRows] = useState<UserRow[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const { run, modal } = useStepUp(setError)
  // useStepUp's run changes every render; keep the latest in a ref so loading does not loop.
  const runRef = useRef(run)
  useEffect(() => { runRef.current = run })

  // Search after a short pause in typing, not on every key.
  useEffect(() => { const t = window.setTimeout(() => setSearch(q.trim()), 350); return () => window.clearTimeout(t) }, [q])

  const load = useCallback((cursor: string | null) => runRef.current(async () => {
    setLoading(true)
    setError(null)
    try {
      const page = await authApi.listUsers({ q: search, role, status, cursor })
      setRows((current) => (cursor ? [...current, ...page.items] : page.items))
      setNext(page.nextCursor)
    } finally {
      setLoading(false)
    }
  }), [search, role, status])
  useEffect(() => { load(null) }, [load])

  return (
    <>
      {modal}
      <div className="page-head"><div><h1>Users</h1>
        <p className="muted" style={{ margin: 0 }}>Every account on the platform. Opening this list is recorded in the audit log.</p></div></div>
      <ErrorAlert error={error} />
      <section className="card panel">
        <div className="row" style={{ marginBottom: 14 }}>
          <input className="input" style={{ flex: 2, minWidth: 220 }} type="search" placeholder="Search name or email" aria-label="Search users"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" style={{ flex: 1 }} aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as UserRoleFilter)}>
            {ROLE_FILTERS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <select className="input" style={{ flex: 1 }} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option><option value="ACTIVE">Active</option>
            <option value="SUSPENDED">Suspended</option><option value="DELETED">Deleted</option>
          </select>
        </div>
        {rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>{loading ? 'Loading…' : 'No accounts match.'}</p> : (
          <div className="table-scroll">
            <table className="data">
              <thead><tr><th>Name</th><th>Roles</th><th>Country</th><th>Status</th><th>Email</th><th>Two-step</th><th>Joined</th><th>Last sign-in</th><th /></tr></thead>
              <tbody>{rows.map((u) => (
                <tr key={u.id}>
                  <td><strong>{u.displayName}</strong><div className="muted small">{u.email}</div></td>
                  <td><div className="badges">{[...u.personas, ...u.platformRoles].map((r) => <span key={r} className="badge">{ROLE_LABEL[r] ?? r}</span>)}</div></td>
                  <td>{u.country}</td>
                  <td><span className={`badge ${STATUS_TONE[u.status] ?? ''}`}>{u.status.charAt(0) + u.status.slice(1).toLowerCase()}</span></td>
                  <td>{u.emailConfirmed ? <span className="badge green">Confirmed</span> : <span className="badge warn">Not confirmed</span>}</td>
                  <td>{u.mfaEnabled ? 'On' : 'Off'}</td>
                  <td>{fmt(u.createdAt)}</td>
                  <td>{fmt(u.lastSignInAt)}</td>
                  <td style={{ textAlign: 'right' }}>
                    {u.platformRoles.length === 0 && u.status === 'ACTIVE' &&
                      <Link className="btn btn-ghost btn-sm" to={`/app/ops/safety?subjectType=IDENTITY&subjectId=${u.id}`}>Open safety case</Link>}
                  </td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        {next && <button className="btn btn-secondary btn-sm" style={{ marginTop: 12 }} disabled={loading} onClick={() => load(next)}>
          {loading ? 'Loading…' : 'Load more'}</button>}
      </section>
    </>
  )
}
