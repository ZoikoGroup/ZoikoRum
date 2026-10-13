import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { authApi, PLATFORM_ROLES, ROLE_LABEL, type PlatformRole, type StaffMember } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { ErrorAlert, Field, useStepUp } from '../components/ui'

/** Platform Admin: grant and revoke staff roles. Every change asks for a fresh MFA code. */
export default function StaffAdmin() {
  const { user } = useAuth()
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<PlatformRole>('TS_ANALYST')
  const { run, modal } = useStepUp(setError)

  const load = useCallback(async () => {
    try {
      setStaff(await authApi.listStaff())
    } catch (err) {
      setError(err)
    }
  }, [])
  useEffect(() => { load() }, [load])

  function grant(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setNotice('')
    run(async () => {
      const target = await authApi.lookup(email.trim())
      await authApi.grantRole(target.id, role)
      setNotice(`${ROLE_LABEL[role]} granted to ${target.email}.`)
      setEmail('')
      await load()
    })
  }

  function revoke(member: StaffMember, r: PlatformRole) {
    if (!confirm(`Remove ${ROLE_LABEL[r]} from ${member.email}? They will be signed out everywhere.`)) return
    setError(null)
    setNotice('')
    run(async () => {
      await authApi.revokeRole(member.id, r)
      setNotice(`${ROLE_LABEL[r]} removed from ${member.email}.`)
      await load()
    })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Staff &amp; roles</h1>
          <p className="muted" style={{ margin: 0 }}>Platform roles are never self-assigned. Every change is audited.</p>
        </div>
      </div>
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <section className="card panel">
        <h2>Grant a staff role</h2>
        <p className="muted small">The person must already have a Zoikorum account.</p>
        <form className="row" onSubmit={grant}>
          <Field label="Account email" id="staff-email">
            <input id="staff-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Role" id="staff-role">
            <select id="staff-role" className="input" value={role} onChange={(e) => setRole(e.target.value as PlatformRole)}>
              {PLATFORM_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </Field>
          <button className="btn btn-primary" disabled={!email}>Grant role</button>
        </form>
      </section>

      <section className="card panel">
        <h2>Current staff</h2>
        <table className="data">
          <thead><tr><th>Name</th><th>Email</th><th>Roles</th><th>MFA</th></tr></thead>
          <tbody>
            {staff.map((m) => (
              <tr key={m.id}>
                <td>{m.displayName}</td>
                <td>{m.email}</td>
                <td>
                  <div className="badges">
                    {m.platformRoles.map((r) => (
                      <span key={r} className="badge">
                        {ROLE_LABEL[r]}
                        {!(m.id === user?.id && r === 'PLATFORM_ADMIN') && (
                          <button className="btn-ghost" style={{ border: 0, background: 'none', cursor: 'pointer', padding: 0, color: 'var(--zk-danger)' }}
                            aria-label={`Remove ${ROLE_LABEL[r]} from ${m.email}`} onClick={() => revoke(m, r)}>×</button>
                        )}
                      </span>
                    ))}
                  </div>
                </td>
                <td>{m.mfaEnabled ? <span className="badge green">On</span> : <span className="badge warn">Off</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {modal}
    </>
  )
}
