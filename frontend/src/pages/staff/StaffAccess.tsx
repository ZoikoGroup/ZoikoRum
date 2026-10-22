import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { submittedNotice } from '../../api/approvals'
import { authApi, PLATFORM_ROLES, ROLE_LABEL, type PlatformRole, type StaffMember } from '../../api/auth'
import { useAuth } from '../../auth/AuthContext'
import { ErrorAlert, Field, useStepUp } from '../../components/ui'
import {
  AdminHeader, AdminKpi, Callout, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, HBars, Initials, KpiStrip, ListDetail, Panel,
  PanelRow, Pill, StatusPill, TableFoot, shortDateTime,pickRow } from '../../components/admin'

/* Staff & Access Control (design 72), replacing StaffAdmin. Sources: GET /v1/admin/staff, GET /v1/admin/identities/lookup,
   POST/DELETE /v1/admin/identities/{id}/platform-roles. Platform roles are never self-assigned; every change asks for
   a fresh two-step code, is a maker-checker request that another Platform Admin approves (Approvals page) before it
   applies, and is audited. A grant can be just-in-time: it ends on its own after the chosen time. */

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

/** Just-in-time access: how long a grant lasts ('' = permanent). */
const DURATIONS: [string, string][] = [['1', '1 hour'], ['8', '8 hours'], ['24', '24 hours'], ['', 'Permanent']]
const endsAt = (hours: string) => (hours ? new Date(Date.now() + Number(hours) * 3_600_000).toISOString() : null)
const REASON_MIN = 10

export default function StaffAccess() {
  const { user } = useAuth()
  const [staff, setStaff] = useState<StaffMember[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<PlatformRole>('TS_ANALYST')
  const [hours, setHours] = useState('8')
  const [reason, setReason] = useState('')
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
      const request = await authApi.grantRole(target.id, role, reason.trim(), endsAt(hours))
      setNotice(`${ROLE_LABEL[role]} for ${target.email}: ${submittedNotice(request)}`)
      setEmail(''); setReason('')
      await load()
    })
  }

  function grantTo(member: StaffMember, r: PlatformRole, why: string, duration: string) {
    setError(null); setNotice('')
    void run(async () => {
      const request = await authApi.grantRole(member.id, r, why, endsAt(duration))
      setNotice(`${ROLE_LABEL[r]} for ${member.email}: ${submittedNotice(request)}`)
      await load()
    })
  }

  function revoke(member: StaffMember, r: PlatformRole, why: string) {
    if (!confirm(`Ask to remove ${ROLE_LABEL[r]} from ${member.email}? Once another Platform Admin approves, they are signed out everywhere.`)) return
    setError(null); setNotice('')
    void run(async () => {
      const request = await authApi.revokeRole(member.id, r, why)
      setNotice(`Removing ${ROLE_LABEL[r]} from ${member.email}: ${submittedNotice(request)}`)
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
        subtitle="Ask to grant or revoke internal platform roles. Roles are never self-assigned; every change needs a fresh two-step code and a second Platform Admin's approval, and is audited." />
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
        <Panel title="Request a staff role" meta="The person must already have a Zoikorum account">
          <form onSubmit={grant}>
            <Field label="Account email" id="staff-email">
              <input id="staff-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Role" id="staff-role">
              <select id="staff-role" className="input" value={role} onChange={(e) => setRole(e.target.value as PlatformRole)}>
                {PLATFORM_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </Field>
            <Field label="Access for" id="staff-duration">
              <select id="staff-duration" className="input" value={hours} onChange={(e) => setHours(e.target.value)}>
                {DURATIONS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Reason (the approver reads it)" id="staff-reason">
              <textarea id="staff-reason" className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <button className="btn btn-primary" disabled={!email || reason.trim().length < REASON_MIN}>Request approval</button>
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
            <div className="adm-note">No self-grants · every change needs a second Platform Admin · removing a role signs the person out everywhere</div>
            <div className="adm-table-wrap">
              <table className="data">
                <thead><tr><th scope="col">Name</th><th scope="col">Roles</th><th scope="col">Two-step</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {staff === null && <tr><td colSpan={5} className="empty-row">Loading staff…</td></tr>}
                  {staff && shown.length === 0 && <tr><td colSpan={5} className="empty-row">No staff here.</td></tr>}
                  {shown.map((m) => (
                    <tr {...pickRow} key={m.id} className={`pick ${m.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(m.id)}>
                      <td><span className="name-cell"><Initials name={m.displayName} /><span><div className="cell-main">{m.displayName}</div><div className="cell-sub">{m.email}</div></span></span></td>
                      <td><div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{m.platformRoles.map((r) => <Pill key={r} tone={PRIVILEGED.includes(r) ? 'violet' : 'blue'}>
                        {ROLE_LABEL[r]}{m.roleExpiries?.[r] ? ` · until ${shortDateTime(m.roleExpiries[r])}` : ''}</Pill>)}</div></td>
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
  revoke: (m: StaffMember, r: PlatformRole, why: string) => void; grant: (m: StaffMember, r: PlatformRole, why: string, hours: string) => void
}) {
  const missing = PLATFORM_ROLES.filter((r) => !m.platformRoles.includes(r))
  const [role, setRole] = useState<PlatformRole | ''>('')
  const [hours, setHours] = useState('8')
  const [why, setWhy] = useState('')
  const reasoned = why.trim().length >= REASON_MIN
  return (
    <DetailPanel title={m.displayName} subtitle={m.email} badge={<StatusPill status={m.status} />} onClose={onClose}>
      {!m.mfaEnabled && <Callout tone="amber" title="Two-step sign-in is off">This person cannot complete actions that need a fresh two-step code until they turn it on.</Callout>}
      {isPrivileged(m) && <Callout tone="blue" title="Privileged access">Holds a role that can move money, change platform controls or override decisions.</Callout>}
      <Facts title="Account" rows={[['Status', m.status.toLowerCase()], ['Two-step sign-in', m.mfaEnabled ? 'On' : 'Off'], ['Roles held', m.platformRoles.length]]} />
      <Field label="Reason for a change (the approving admin reads it)" id={`why-${m.id}`}>
        <textarea id={`why-${m.id}`} className="input" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} />
      </Field>
      <div className="adm-facts"><h3>Roles</h3>
        {m.platformRoles.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No platform role.</p> : (
          <ul className="adm-metrics">{m.platformRoles.map((r) => (
            <li key={r}><span>{ROLE_LABEL[r]}<span className="cell-sub" style={{ display: 'block' }}>
              {m.roleExpiries?.[r] ? `Time-limited: ends ${shortDateTime(m.roleExpiries[r])}` : ROLE_SCOPE[r]}</span></span>
              {self && r === 'PLATFORM_ADMIN' ? <span className="muted small">Your own admin role</span> : (
                <button type="button" className="btn btn-ghost btn-sm" style={{ color: 'var(--zk-danger)' }} aria-label={`Ask to remove ${ROLE_LABEL[r]} from ${m.email}`}
                  disabled={!reasoned} title={reasoned ? undefined : 'Give a reason first'} onClick={() => revoke(m, r, why.trim())}>Request removal</button>)}</li>))}</ul>)}
      </div>
      {self && <Callout tone="blue" title="Your own account">Another Platform Admin must ask for, and a third approve, any role you need.</Callout>}
      {!self && missing.length > 0 && (
        <form onSubmit={(e) => { e.preventDefault(); if (role && reasoned) { grant(m, role, why.trim(), hours); setRole('') } }} style={{ display: 'grid', gap: 6 }}>
          <label className="small" htmlFor={`grant-${m.id}`}>Request another role</label>
          <select id={`grant-${m.id}`} className="input" value={role} onChange={(e) => setRole(e.target.value as PlatformRole | '')}>
            <option value="">Choose a role</option>
            {missing.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <label className="small" htmlFor={`hours-${m.id}`}>Access for</label>
          <select id={`hours-${m.id}`} className="input" value={hours} onChange={(e) => setHours(e.target.value)}>
            {DURATIONS.map(([v, l]) => <option key={l} value={v}>{l}</option>)}
          </select>
          <button className="btn btn-primary btn-sm" disabled={!role || !reasoned}>Request approval for {m.displayName}</button>
        </form>
      )}
    </DetailPanel>
  )
}
