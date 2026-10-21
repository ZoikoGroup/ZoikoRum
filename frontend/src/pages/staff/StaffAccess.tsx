import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { authApi, PLATFORM_ROLES, ROLE_LABEL, type PlatformRole, type StaffMember } from '../../api/auth'
import { useAuth } from '../../auth/AuthContext'
import { ErrorAlert, Field, useStepUp } from '../../components/ui'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, Initials, KpiStrip, ListDetail, Panel,
  PanelRow, Pill, StatusPill, TableFoot,
} from '../../components/admin'

/* Staff & Access Control (design 72), replacing StaffAdmin. Sources: GET /v1/admin/staff, GET /v1/admin/identities/lookup,
   POST/DELETE /v1/admin/identities/{id}/platform-roles. Platform roles are never self-assigned; every change asks for
   a fresh two-step code and is audited. */

const ROLE_SCOPE: Record<PlatformRole, string> = {
  PLATFORM_ADMIN: 'System operations, staff roles, switches and flags',
  TS_ANALYST: 'Enforcement case investigation and reports',
  COMPLIANCE_OFFICER: 'Verification and policy oversight',
  RISK_LEAD: 'Risk decisions and incident leadership',
  LEGAL: 'Contracts, evidence and legal holds',
  MEDIATOR: 'Assigned dispute mediation only',
  FINANCIAL_OPS: 'Payouts, refunds and money replays',
  EXECUTIVE: 'Final authority and executive overrides',
  AI_SAFETY_REVIEWER: 'AI output and model safety review',
  SUPPORT_AGENT: 'Customer help requests',
}
/** Roles that can move money, change platform controls or override decisions. */
const PRIVILEGED: PlatformRole[] = ['PLATFORM_ADMIN', 'FINANCIAL_OPS', 'EXECUTIVE']
const isPrivileged = (m: StaffMember) => m.platformRoles.some((r) => PRIVILEGED.includes(r))

type TabKey = 'all' | 'privileged' | 'nomfa' | 'inactive'

export default function StaffAccess() {
  const { user } = useAuth()
  const [staff, setStaff] = useState<StaffMember[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<PlatformRole>('TS_ANALYST')
  const [tab, setTab] = useState<TabKey>('all')
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)

  const load = useCallback(async () => {
    try { setStaff(await authApi.listStaff()) } catch (err) { setError(err) }
  }, [])
  useEffect(() => { void load() }, [load])

  function grant(e: FormEvent) {
    e.preventDefault()
    setError(null); setNotice('')
    void run(async () => {
      const target = await authApi.lookup(email.trim())
      await authApi.grantRole(target.id, role)
      setNotice(`${ROLE_LABEL[role]} granted to ${target.email}.`)
      setEmail('')
      await load()
    })
  }

  function grantTo(member: StaffMember, r: PlatformRole) {
    setError(null); setNotice('')
    void run(async () => {
      await authApi.grantRole(member.id, r)
      setNotice(`${ROLE_LABEL[r]} granted to ${member.email}.`)
      await load()
    })
  }

  function revoke(member: StaffMember, r: PlatformRole) {
    if (!confirm(`Remove ${ROLE_LABEL[r]} from ${member.email}? They will be signed out everywhere.`)) return
    setError(null); setNotice('')
    void run(async () => {
      await authApi.revokeRole(member.id, r)
      setNotice(`${ROLE_LABEL[r]} removed from ${member.email}.`)
      await load()
    })
  }

  const all = staff ?? []
  const mfa = all.filter((m) => m.mfaEnabled).length
  const privileged = all.filter(isPrivileged)
  const inactive = all.filter((m) => m.status !== 'ACTIVE')
  const holders = (r: PlatformRole) => all.filter((m) => m.platformRoles.includes(r)).length
  const s = q.trim().toLowerCase()
  const shown = all.filter((m) => (tab === 'privileged' ? isPrivileged(m) : tab === 'nomfa' ? !m.mfaEnabled : tab === 'inactive' ? m.status !== 'ACTIVE' : true)
    && (!roleFilter || m.platformRoles.includes(roleFilter as PlatformRole))
    && (!s || [m.displayName, m.email, ...m.platformRoles.map((r) => ROLE_LABEL[r])].some((v) => v.toLowerCase().includes(s))))
  const selected = all.find((m) => m.id === selectedId) ?? null

  return (
    <>
      <AdminHeader crumb="Administration & support / Identity governance" title="Staff & Access Control"
        subtitle="Grant and revoke internal platform roles. Roles are never self-assigned; every change asks for a fresh two-step code and is audited." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {modal}

      <KpiStrip>
        <AdminKpi icon="team" tone="blue" label="Staff accounts" value={staff ? all.length : '—'} sub={staff ? `${all.length - inactive.length} active · ${inactive.length} not active` : undefined} />
        <AdminKpi icon="lock" tone="green" label="Two-step sign-in on" value={staff ? `${mfa} / ${all.length}` : '—'} sub={staff && mfa < all.length ? `${all.length - mfa} without` : 'All staff'} />
        <AdminKpi icon="shield" tone="violet" label="Privileged" value={staff ? privileged.length : '—'} sub="Platform Admin, Financial Ops or Executive" />
        <AdminKpi icon="list" tone="teal" label="Roles in use" value={staff ? `${PLATFORM_ROLES.filter((r) => holders(r) > 0).length} / ${PLATFORM_ROLES.length}` : '—'} />
        <AdminKpi icon="alert" tone={inactive.length ? 'amber' : 'green'} label="Not active" value={staff ? inactive.length : '—'} sub="Suspended or deleted accounts holding roles" />
      </KpiStrip>

      <PanelRow cols={3}>
        <Panel title="Platform role catalogue" meta={`${PLATFORM_ROLES.length} roles`}>
          <ul className="adm-metrics">{PLATFORM_ROLES.map((r) => (
            <li key={r}><span><strong style={{ color: 'var(--zk-ink)' }}>{ROLE_LABEL[r]}</strong><span className="cell-sub" style={{ display: 'block' }}>{ROLE_SCOPE[r]}</span></span>
              <strong>{holders(r)}</strong></li>))}</ul>
        </Panel>
        <Panel title="Role holders" meta="Staff per role">
          <HBars rows={PLATFORM_ROLES.map((r) => ({ label: ROLE_LABEL[r], value: holders(r) }))} />
        </Panel>
        <Panel title="Grant a staff role" meta="The person must already have a Zoikorum account">
          <form onSubmit={grant}>
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
        </Panel>
      </PanelRow>

      <ListDetail
        list={
          <div className="card">
            <CountTabs tabs={[
              { key: 'all' as TabKey, label: 'Staff directory', count: all.length },
              { key: 'privileged' as TabKey, label: 'Privileged', count: privileged.length },
              { key: 'nomfa' as TabKey, label: 'Without two-step', count: all.length - mfa },
              { key: 'inactive' as TabKey, label: 'Not active', count: inactive.length },
            ]} value={tab} onChange={setTab} />
            <FilterBar search={q} onSearch={setQ} placeholder="Search name, email or role…">
              <FilterSelect label="Role" value={roleFilter} onChange={setRoleFilter} options={PLATFORM_ROLES.map((r) => [r, ROLE_LABEL[r]])} />
            </FilterBar>
            <div className="adm-note">No self-grants · removing a role signs the person out everywhere</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th>Name</th><th>Roles</th><th>Two-step</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {staff === null && <tr><td colSpan={5} className="empty-row">Loading staff…</td></tr>}
                  {staff && shown.length === 0 && <tr><td colSpan={5} className="empty-row">No staff here.</td></tr>}
                  {shown.map((m) => (
                    <tr key={m.id} className={`pick ${m.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(m.id)}>
                      <td><span className="name-cell"><Initials name={m.displayName} /><span><div className="cell-main">{m.displayName}</div><div className="cell-sub">{m.email}</div></span></span></td>
                      <td><div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{m.platformRoles.map((r) => <Pill key={r} tone={PRIVILEGED.includes(r) ? 'violet' : 'blue'}>{ROLE_LABEL[r]}</Pill>)}</div></td>
                      <td>{m.mfaEnabled ? <Pill tone="green">On</Pill> : <Pill tone="amber">Off</Pill>}</td>
                      <td><StatusPill status={m.status} /></td>
                      <td><button type="button" className="btn btn-secondary btn-sm" onClick={(e) => { e.stopPropagation(); setSelectedId(m.id) }}>Review</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TableFoot shown={shown.length} total={all.length} noun="staff accounts" />
          </div>
        }
        detail={selected && (
          <MemberDetail key={selected.id} m={selected} self={selected.id === user?.id} onClose={() => setSelectedId(null)} revoke={revoke} grant={grantTo} />
        )}
      />
    </>
  )
}

function MemberDetail({ m, self, onClose, revoke, grant }: {
  m: StaffMember; self: boolean; onClose: () => void
  revoke: (m: StaffMember, r: PlatformRole) => void; grant: (m: StaffMember, r: PlatformRole) => void
}) {
  const missing = PLATFORM_ROLES.filter((r) => !m.platformRoles.includes(r))
  const [role, setRole] = useState<PlatformRole | ''>('')
  return (
    <DetailPanel title={m.displayName} subtitle={m.email} badge={<StatusPill status={m.status} />} onClose={onClose}>
      {!m.mfaEnabled && <Callout tone="amber" title="Two-step sign-in is off">This person cannot complete actions that need a fresh two-step code until they turn it on.</Callout>}
      {isPrivileged(m) && <Callout tone="blue" title="Privileged access">Holds a role that can move money, change platform controls or override decisions.</Callout>}
      <Facts title="Account" rows={[['Status', m.status.toLowerCase()], ['Two-step sign-in', m.mfaEnabled ? 'On' : 'Off'], ['Roles held', m.platformRoles.length]]} />
      <div className="adm-facts"><h3>Roles</h3>
        {m.platformRoles.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No platform role.</p> : (
          <ul className="adm-metrics">{m.platformRoles.map((r) => (
            <li key={r}><span>{ROLE_LABEL[r]}<span className="cell-sub" style={{ display: 'block' }}>{ROLE_SCOPE[r]}</span></span>
              {self && r === 'PLATFORM_ADMIN' ? <span className="muted small">Your own admin role</span> : (
                <button type="button" className="btn btn-ghost btn-sm" style={{ color: 'var(--zk-danger)' }} aria-label={`Remove ${ROLE_LABEL[r]} from ${m.email}`}
                  onClick={() => revoke(m, r)}>Revoke</button>)}</li>))}</ul>)}
      </div>
      {missing.length > 0 && (
        <form onSubmit={(e) => { e.preventDefault(); if (role) { grant(m, role); setRole('') } }} style={{ display: 'grid', gap: 6 }}>
          <label className="small" htmlFor={`grant-${m.id}`}>Grant another role</label>
          <select id={`grant-${m.id}`} className="input" value={role} onChange={(e) => setRole(e.target.value as PlatformRole | '')}>
            <option value="">Choose a role</option>
            {missing.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <button className="btn btn-primary btn-sm" disabled={!role}>Grant role to {m.displayName}</button>
        </form>
      )}
    </DetailPanel>
  )
}
