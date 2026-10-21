import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi, ROLE_LABEL, type UserRoleFilter, type UserRow } from '../../api/auth'
import { adminConsoleApi, type AdminOrganization, type AdminOrganizationSummary } from '../../api/adminConsole'
import { adminApi, type AdminOverview } from '../../api/saved'
import { useAuth } from '../../auth/AuthContext'
import {
  AdminHeader, AdminKpi, Checklist, CountTabs, DetailPanel, Facts, FilterBar, FilterSelect, Initials, KpiStrip, ListDetail,
  Pill, StatusPill, TableFoot, label, shortDate, shortDateTime, toneFor, type CheckState,
} from '../../components/admin'
import { ErrorAlert, useStepUp } from '../../components/ui'

type Tab = 'all' | 'orgs' | 'pros' | 'buyers' | 'admins' | 'suspended'
const TAB_ROLE: Partial<Record<Tab, UserRoleFilter>> = { pros: 'PROFESSIONAL', buyers: 'BUYER', admins: 'STAFF' }

const ROLE_FILTERS: [string, string][] = [
  ['BUYER', 'Customers'], ['PROFESSIONAL', 'Professionals'], ['FIRM_ADMIN', 'Firm admins'], ['ENTERPRISE_ADMIN', 'Enterprise admins'],
  ['ENTERPRISE_MEMBER', 'Enterprise members'], ['STAFF', 'Staff'],
]
const STATUS_FILTERS: [string, string][] = [['ACTIVE', 'Active'], ['SUSPENDED', 'Suspended'], ['DELETED', 'Deleted']]
const KIND_FILTERS: [string, string][] = [['BUYER', 'Buyer'], ['ENTERPRISE', 'Enterprise'], ['FIRM', 'Firm']]
const stateOf = (s: string | null | undefined): CheckState => {
  const t = toneFor(s)
  return t === 'green' ? 'done' : t === 'red' ? 'missing' : 'pending'
}

/** Platform Admin / Trust & Safety: every account and organisation, searchable. Restricting an account is done through an
 *  evidence-based safety case (four-eyes), never directly from this list. Every read is recorded in the audit log. */
export default function Accounts() {
  const [tab, setTab] = useState<Tab>('all')
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [kind, setKind] = useState('')
  const [users, setUsers] = useState<UserRow[]>([])
  const [orgs, setOrgs] = useState<AdminOrganization[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [orgSummary, setOrgSummary] = useState<AdminOrganizationSummary | null>(null)
  const [selId, setSelId] = useState<string | null>(null)
  const { run, modal } = useStepUp(setError)
  const { user: me } = useAuth()
  const isAdmin = !!me?.platformRoles.includes('PLATFORM_ADMIN')

  // KPI sources load independently; one being unavailable does not hide the others.
  useEffect(() => {
    adminApi.overview().then(setOverview).catch(() => setOverview(null))
    adminConsoleApi.organizationSummary().then(setOrgSummary).catch(() => setOrgSummary(null))
  }, [])

  // useStepUp's run changes every render; keep the latest in a ref so loading does not loop.
  const runRef = useRef(run)
  useEffect(() => { runRef.current = run })

  // Search after a short pause in typing, not on every key.
  useEffect(() => { const t = window.setTimeout(() => setSearch(q.trim()), 350); return () => window.clearTimeout(t) }, [q])

  const isOrgs = tab === 'orgs'
  const load = useCallback((cursor: string | null) => runRef.current(async () => {
    setLoading(true)
    setError(null)
    try {
      if (isOrgs) {
        const page = await adminConsoleApi.organizations({ q: search, kind, status, cursor })
        setOrgs((current) => (cursor ? [...current, ...page.items] : page.items))
        setNext(page.nextCursor)
      } else {
        const r = (TAB_ROLE[tab] ?? role) as UserRoleFilter
        const page = await authApi.listUsers({ q: search, role: r, status: tab === 'suspended' ? 'SUSPENDED' : status, cursor })
        setUsers((current) => (cursor ? [...current, ...page.items] : page.items))
        setNext(page.nextCursor)
      }
    } finally {
      setLoading(false)
    }
  }), [isOrgs, tab, search, role, status, kind])
  useEffect(() => { load(null) }, [load])

  function changeTab(t: Tab) {
    setTab(t); setSelId(null); setRole(''); setStatus(''); setKind(''); setNext(null)
    if (t === 'orgs') setOrgs([]); else setUsers([])
  }

  /** Only after confirming who the person is some other way (e.g. a video call with their ID). */
  function resetTwoStep(u: UserRow) {
    const reason = window.prompt(`Reset two-step verification for ${u.displayName}? They set it up again at their next sign-in.\n\n`
      + 'How did you confirm it is really them? (recorded in the audit log)')
    if (!reason || reason.trim().length < 10) return
    run(async () => {
      await authApi.resetMfa(u.id, reason.trim())
      setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, mfaEnabled: false } : x)))
      setNotice(`Two-step verification was reset for ${u.displayName}. They have been signed out everywhere.`)
    })
  }

  const acc = overview?.accounts
  const tabs: { key: Tab; label: string; count?: number | null }[] = [
    { key: 'all', label: 'All accounts', count: acc?.total },
    { key: 'orgs', label: 'Organizations', count: orgSummary?.total },
    { key: 'pros', label: 'Professionals', count: acc?.professionals },
    { key: 'buyers', label: 'Buyers', count: acc?.buyers },
    { key: 'admins', label: 'Admins' },
    { key: 'suspended', label: 'Suspended' },
  ]
  const tabCount = tabs.find((t) => t.key === tab)?.count
  const selUser = !isOrgs ? users.find((u) => u.id === selId) ?? null : null
  const selOrg = isOrgs ? orgs.find((o) => o.id === selId) ?? null : null
  const shown = isOrgs ? orgs.length : users.length

  const list = (
    <div className="card">
      <CountTabs tabs={tabs} value={tab} onChange={changeTab} />
      <FilterBar search={q} onSearch={setQ} placeholder={isOrgs ? 'Search organisation name…' : 'Search name or email…'}>
        {isOrgs && <FilterSelect label="All types" value={kind} onChange={setKind} options={KIND_FILTERS} />}
        {(tab === 'all' || tab === 'suspended') && <FilterSelect label="All roles" value={role} onChange={setRole} options={ROLE_FILTERS} />}
        {tab !== 'suspended' && <FilterSelect label="Any status" value={status} onChange={setStatus}
          options={isOrgs ? [['ACTIVE', 'Active'], ['SUSPENDED', 'Suspended']] : STATUS_FILTERS} />}
      </FilterBar>
      <div className="adm-note">Opening this list is recorded in the audit log</div>
      <div className="adm-table-wrap">
        {isOrgs ? (
          <table className="data">
            <thead><tr><th>Organisation</th><th>Type</th><th>Status</th><th>Country</th><th>Verification</th><th>Members</th><th>Contracts</th><th>Joined</th></tr></thead>
            <tbody>
              {orgs.length === 0 && <tr><td colSpan={8} className="empty-row">{loading ? 'Loading…' : 'No organisations match.'}</td></tr>}
              {orgs.map((o) => (
                <tr key={o.id} className={`pick ${selId === o.id ? 'selected' : ''}`} onClick={() => setSelId(o.id)}>
                  <td><div className="name-cell"><Initials name={o.name} /><div><div className="cell-main">{o.name}</div>
                    <div className="cell-sub">{o.primaryContact?.email ?? o.industry ?? ''}</div></div></div></td>
                  <td><Pill tone={o.kind === 'ENTERPRISE' ? 'violet' : o.kind === 'FIRM' ? 'blue' : 'grey'}>{label(o.kind)}</Pill></td>
                  <td><StatusPill status={o.status} /></td>
                  <td>{o.country ?? '—'}</td>
                  <td>{o.verificationStatus ? <StatusPill status={o.verificationStatus} /> : <span className="muted">—</span>}</td>
                  <td>{o.memberCount}</td>
                  <td>{o.contractCount}</td>
                  <td>{shortDate(o.createdAt)}</td>
                </tr>))}
            </tbody>
          </table>
        ) : (
          <table className="data">
            <thead><tr><th>Name</th><th>Roles</th><th>Status</th><th>Country</th><th>Email</th><th>Two-step</th><th>Joined</th><th>Last sign-in</th></tr></thead>
            <tbody>
              {users.length === 0 && <tr><td colSpan={8} className="empty-row">{loading ? 'Loading…' : 'No accounts match.'}</td></tr>}
              {users.map((u) => (
                <tr key={u.id} className={`pick ${selId === u.id ? 'selected' : ''}`} onClick={() => setSelId(u.id)}>
                  <td><div className="name-cell"><Initials name={u.displayName} /><div><div className="cell-main">{u.displayName}</div>
                    <div className="cell-sub">{u.email}</div></div></div></td>
                  <td><div className="badges">{[...u.personas, ...u.platformRoles].map((r) => <Pill key={r} tone={u.platformRoles.includes(r) ? 'violet' : 'grey'}>{ROLE_LABEL[r] ?? r}</Pill>)}</div></td>
                  <td><StatusPill status={u.status} /></td>
                  <td>{u.country}</td>
                  <td>{u.emailConfirmed ? <Pill tone="green">Confirmed</Pill> : <Pill tone="amber">Not confirmed</Pill>}</td>
                  <td>{u.mfaEnabled ? 'On' : 'Off'}</td>
                  <td>{shortDate(u.createdAt)}</td>
                  <td>{shortDate(u.lastSignInAt)}</td>
                </tr>))}
            </tbody>
          </table>
        )}
      </div>
      <TableFoot shown={shown} total={tabCount} noun={isOrgs ? 'organisations' : 'accounts'} />
      {next && <div style={{ padding: '0 16px 12px' }}>
        <button type="button" className="btn btn-secondary btn-sm" disabled={loading} onClick={() => load(next)}>{loading ? 'Loading…' : 'Load more'}</button></div>}
    </div>
  )

  let detail = null
  if (selUser) {
    const u = selUser
    const canSafety = u.platformRoles.length === 0 && u.status === 'ACTIVE'
    const canReset = isAdmin && u.mfaEnabled && u.id !== me?.id
    detail = (
      <DetailPanel title={u.displayName} subtitle={u.email} badge={<StatusPill status={u.status} />} onClose={() => setSelId(null)}
        footer={(canSafety || canReset) ? <>
          {canSafety && <Link className="btn btn-secondary btn-sm" to={`/app/ops/safety?subjectType=IDENTITY&subjectId=${u.id}`}>Open safety case</Link>}
          {canReset && <button type="button" className="btn btn-ghost btn-sm" onClick={() => resetTwoStep(u)}>Reset two-step</button>}
        </> : undefined}>
        <Facts title="Key information" rows={[
          ['Account ID', <span key="id" className="cell-id">{u.id}</span>],
          ['Roles', [...u.personas, ...u.platformRoles].map((r) => ROLE_LABEL[r] ?? r).join(', ') || '—'],
          ['Country', u.country],
          ['Joined', shortDate(u.createdAt)],
          ['Last sign-in', shortDateTime(u.lastSignInAt)],
        ]} />
        <Checklist title="Verification & compliance" items={[
          { label: 'Email address', state: u.emailConfirmed ? 'done' : 'pending', note: u.emailConfirmed ? 'Confirmed' : 'Not confirmed' },
          { label: 'Two-step verification', state: u.mfaEnabled ? 'done' : 'pending', note: u.mfaEnabled ? 'On' : 'Off' },
          { label: 'Account standing', state: stateOf(u.status), note: label(u.status) },
        ]} />
      </DetailPanel>
    )
  } else if (selOrg) {
    const o = selOrg
    detail = (
      <DetailPanel title={o.name} subtitle={`${label(o.kind)} organisation`} badge={<StatusPill status={o.status} />} onClose={() => setSelId(null)}>
        <Facts title="Key information" rows={[
          ['Account ID', <span key="id" className="cell-id">{o.id}</span>],
          ['Organisation type', label(o.kind)],
          ['Primary contact', o.primaryContact?.name ?? '—'],
          ['Email', o.primaryContact?.email ?? '—'],
          ['Country', o.country ?? '—'],
          ['Industry', o.industry ?? '—'],
          ['Members', o.memberCount],
          ['Contracts', o.contractCount],
          ['Date joined', shortDate(o.createdAt)],
        ]} />
        <Checklist title="Verification & compliance" items={[
          { label: 'Organisation verification', state: stateOf(o.verificationStatus), note: o.verificationStatus ? label(o.verificationStatus) : 'Not started' },
          { label: 'Account standing', state: stateOf(o.status), note: label(o.status) },
        ]} />
      </DetailPanel>
    )
  }

  return (
    <>
      {modal}
      <AdminHeader crumb="People & Organizations" title="Accounts & Organizations"
        subtitle="Every buyer, professional and organisation on the platform. Restrictions go through a safety case, never directly from here." />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      {(overview || orgSummary) && <KpiStrip>
        {acc && <AdminKpi icon="team" tone="green" label="Total accounts" value={acc.total.toLocaleString()} />}
        {orgSummary && <AdminKpi icon="building" tone="blue" label="Buyer organisations" value={orgSummary.buyer.toLocaleString()}
          sub={`${orgSummary.enterprise} enterprise · ${orgSummary.firm} firms`} />}
        {acc && <AdminKpi icon="user" tone="violet" label="Professional accounts" value={acc.professionals.toLocaleString()} />}
        {overview && <AdminKpi icon="shield" tone="amber" label="Pending verification" value={overview.verification.open.toLocaleString()}
          sub={`${overview.verification.overdue} overdue`} />}
        {orgSummary && <AdminKpi icon="alert" tone="red" label="Suspended organisations" value={orgSummary.suspended.toLocaleString()}
          sub={`${orgSummary.newLast30Days} new organisations in 30 days`} />}
      </KpiStrip>}
      <ListDetail list={list} detail={detail} />
    </>
  )
}
