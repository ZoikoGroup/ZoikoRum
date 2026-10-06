import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { auditApi, exportAuditCsv, type AuditRecord } from '../../api/audit'
import { formatMoney, ORG_ROLE_INFO, orgApi, type BillingContact, type Invitation, type Organization, type OrgMember, type OrgRole } from '../../api/orgs'
import { useAuth } from '../../auth/AuthContext'
import { ago, ActivityList } from '../../components/activity'
import { Avatar, Icon } from '../../components/dashboard'
import { PortalHeader, SidePanel, StatCard, Tabs } from '../../components/portal'
import { ErrorAlert, Field } from '../../components/ui'
import { countryName } from '../ProfessionalPages'

type Tab = 'overview' | 'members' | 'roles' | 'billing' | 'security'
const ACCESS: Record<string, string> = {
  ORG_ADMIN: 'Full access', REQUESTER: 'Requests & proposals', APPROVER: 'Approvals', BUDGET_OWNER: 'Budgets & payments',
  LEGAL_REVIEWER: 'Contracts & audit', EXCEPTION_AUTHORITY: 'Policy exceptions',
}
const INDUSTRIES = ['Professional Services', 'Financial Services', 'Technology', 'Healthcare', 'Manufacturing', 'Retail & Consumer',
  'Energy & Utilities', 'Public Sector', 'Education', 'Real Estate', 'Other']
const TIME_ZONES = ['UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles',
  'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Australia/Sydney', 'Africa/Johannesburg']

/** Organisation (management design 10): profile, members & access, roles & authority, billing contacts, audit. */
export default function OrganisationPage() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'overview'
  const setTab = (t: Tab) => setParams(t === 'overview' ? {} : { tab: t }, { replace: true })
  const [org, setOrg] = useState<Organization | null>(null)
  const [members, setMembers] = useState<OrgMember[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [billing, setBilling] = useState<BillingContact[]>([])
  const [activity, setActivity] = useState<AuditRecord[] | null>(null)
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      let found: Organization | undefined
      for (let attempt = 0; attempt < 10 && !found; attempt++) {
        const orgs = await orgApi.mine()
        found = orgs.find((o) => o.orgType !== 'INDIVIDUAL') ?? orgs[0]
        if (!found) await new Promise((r) => setTimeout(r, 800))
      }
      if (!found) return
      setOrg(found)
      const admin = found.myRoles.includes('ORG_ADMIN')
      const [m, b] = await Promise.all([orgApi.members(found.id), orgApi.billingContacts(found.id)])
      setMembers(m)
      setBilling(b)
      if (admin) setInvites(await orgApi.invitations(found.id))
      // A token issued before the organisation existed has no org roles yet; treat that as "not visible" rather than an error.
      if (admin || found.myRoles.includes('LEGAL_REVIEWER')) setActivity(await auditApi.recent(found.id, 30).catch(() => null))
    } catch (err) {
      setError(err)
    }
  }, [])
  useEffect(() => { load() }, [load])

  if (!user) return null
  if (!org) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const isAdmin = org.myRoles.includes('ORG_ADMIN')
  const canBill = isAdmin || org.myRoles.includes('BUDGET_OWNER')
  const isTeam = org.orgType !== 'INDIVIDUAL'
  const admins = members.filter((m) => m.roles.includes('ORG_ADMIN')).length
  const approvers = members.filter((m) => m.roles.includes('APPROVER'))
  const orgCode = `ORG-${org.id.slice(0, 8).toUpperCase()}`

  const quickActions: { label: string; icon: 'team' | 'shield' | 'wallet' | 'clock'; onClick: () => void }[] = [
    ...(isTeam && isAdmin ? [{ label: 'Invite member', icon: 'team' as const, onClick: () => setTab('members') }] : []),
    { label: 'Review access', icon: 'shield', onClick: () => setTab('members') },
    { label: 'Update billing contact', icon: 'wallet', onClick: () => setTab('billing') },
    { label: 'View audit log', icon: 'clock', onClick: () => setTab('security') },
  ]

  return (
    <>
      <PortalHeader eyebrow="Account" title="Organisation" subtitle="Manage your organisation profile, access, authority and governance settings."
        actions={isTeam && isAdmin ? <Link className="btn btn-primary" to="/app/enterprise/team"><Icon name="team" /> Invite member</Link> : undefined} />
      <ErrorAlert error={error} />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <div className="stat-row four">
        <StatCard icon="team" tone="violet" value={members.length} label="Members" sub={`${admins} admin${admins === 1 ? '' : 's'} · ${members.length - admins} member${members.length - admins === 1 ? '' : 's'}`} />
        <StatCard icon="shield" tone="amber" value="Not started" label="Verification" sub="Organisation verification arrives with enterprise onboarding" />
        <StatCard icon="building" tone="blue" value={approvers.length ? 'Configured' : 'Not configured'} label="Approval authority"
          sub={approvers.length ? `${approvers.length} approver${approvers.length > 1 ? 's' : ''}` : 'Name approvers and spend limits'} />
        <StatCard icon="clock" tone="amber" value={invites.length + (billing.length ? 0 : 1)} label="Open actions"
          sub={`${invites.length} pending invitation${invites.length === 1 ? '' : 's'}${billing.length ? '' : ' · billing contact missing'}`} />
      </div>

      <Tabs<Tab> tabs={[{ key: 'overview', label: 'Overview' }, { key: 'members', label: 'Members & access' },
        { key: 'roles', label: 'Roles & authority' }, { key: 'billing', label: 'Billing contacts' }, { key: 'security', label: 'Security & audit' }]}
        value={tab} onChange={setTab} />

      {tab === 'overview' && (
        <div className="home-grid wide">
          <div>
            <section className="card panel">
              <div className="panel-head"><h2>Organisation profile</h2>
                {isAdmin && !editing && <button className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>Edit profile</button>}</div>
              {editing ? <ProfileForm org={org} onDone={(o) => { if (o) { setOrg(o); setNotice('Organisation profile saved.') } setEditing(false) }} /> : (
                <dl className="facts">
                  <dt>Organisation name</dt><dd>{org.name}</dd>
                  <dt>Organisation type</dt><dd>{{ INDIVIDUAL: 'Individual buyer', BUSINESS: 'Business', ENTERPRISE: 'Enterprise' }[org.orgType]}</dd>
                  <dt>Industry</dt><dd>{org.industry ?? '—'}</dd>
                  <dt>Primary region</dt><dd>{countryName(org.country)}</dd>
                  <dt>Time zone</dt><dd>{org.timeZone ?? '—'}</dd>
                  <dt>Organisation ID</dt><dd><code>{orgCode}</code></dd>
                  <dt>Member since</dt><dd>{new Date(org.createdAt).toLocaleDateString()}</dd>
                </dl>
              )}
            </section>
            <MembersTable members={members.slice(0, 6)} onViewAll={() => setTab('members')} />
            <RolesSummary members={members} />
          </div>
          <aside>
            <SidePanel title="Quick actions">
              <ul className="quick-actions">{quickActions.map((q) => (
                <li key={q.label}><button onClick={q.onClick}><Icon name={q.icon} /><span>{q.label}</span><span aria-hidden>›</span></button></li>
              ))}</ul>
            </SidePanel>
            <SidePanel title="Billing contacts" action={canBill && <button className="btn btn-ghost btn-sm" onClick={() => setTab('billing')}>Edit</button>}>
              <BillingList billing={billing} />
            </SidePanel>
            <SidePanel title="Recent audit activity" action={activity && <button className="btn btn-ghost btn-sm" onClick={() => setTab('security')}>View all</button>}>
              {activity === null ? <p className="muted small" style={{ margin: 0 }}>Visible to Org Admins and Legal Reviewers.</p> : <ActivityList records={activity} limit={5} />}
            </SidePanel>
          </aside>
        </div>
      )}

      {tab === 'members' && (
        <>
          <MembersTable members={members} />
          {isTeam && isAdmin && (
            <section className="card panel">
              <div className="panel-head"><h2>Invitations</h2><Link className="btn btn-primary btn-sm" to="/app/enterprise/team">Invite or change roles</Link></div>
              {invites.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No pending invitations.</p> : (
                <table className="data"><thead><tr><th>Email</th><th>Roles</th><th>Expires</th></tr></thead>
                  <tbody>{invites.map((i) => <tr key={i.id}><td>{i.email}</td><td>{i.roles.map((r) => ORG_ROLE_INFO[r as OrgRole]?.label ?? r).join(', ')}</td>
                    <td>{new Date(i.expiresAt).toLocaleDateString()}</td></tr>)}</tbody></table>
              )}
            </section>
          )}
          {!isTeam && <p className="muted small">You're the only member of this individual buyer account. Create an enterprise account to work with a team.</p>}
        </>
      )}

      {tab === 'roles' && <RolesDetail members={members} canManage={isTeam && isAdmin} />}

      {tab === 'billing' && (
        <section className="card panel" style={{ maxWidth: 720 }}>
          <div className="panel-head"><h2>Billing contacts</h2></div>
          <p className="muted small">Billing contacts receive invoices, receipts and payment notices. Org Admins and Budget Owners can change them.</p>
          <BillingList billing={billing} />
          {canBill && <BillingForm org={org} members={members} billing={billing} onSaved={(b) => { setBilling(b); setNotice('Billing contacts saved.') }} />}
        </section>
      )}

      {tab === 'security' && (
        <section className="card panel">
          <div className="panel-head"><h2>Security &amp; audit</h2>
            {activity && <button className="btn btn-secondary btn-sm" onClick={async () => {
              try {
                const csv = await exportAuditCsv(org.id)
                const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
                Object.assign(document.createElement('a'), { href: url, download: `${orgCode}-audit.csv` }).click()
                URL.revokeObjectURL(url)
              } catch (err) { setError(err) }
            }}><Icon name="download" /> Export audit log (CSV)</button>}</div>
          <ul className="why">
            <li>Org Admins must use two-step verification; sensitive changes ask for a fresh code.</li>
            <li>Every change is recorded in a tamper-evident, hash-chained audit log.</li>
          </ul>
          {activity === null ? <p className="muted small">The audit log is visible to Org Admins and Legal Reviewers.</p>
            : <ActivityList records={activity} limit={30} />}
        </section>
      )}
    </>
  )
}

function MembersTable({ members, onViewAll }: { members: OrgMember[]; onViewAll?: () => void }) {
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Members &amp; access</h2>{onViewAll && <button className="btn btn-ghost btn-sm" onClick={onViewAll}>View all members →</button>}</div>
      <table className="data">
        <thead><tr><th>Member</th><th>Role</th><th>Access scope</th><th>Status</th><th>Last active</th></tr></thead>
        <tbody>{members.map((m) => (
          <tr key={m.identityId}>
            <td><div className="name-row"><Avatar name={m.displayName} size={32} /><span><strong>{m.displayName}</strong><br /><span className="muted small">{m.email}</span></span></div></td>
            <td><span className={`badge ${m.roles.includes('ORG_ADMIN') ? 'violet' : ''}`}>{m.roles.includes('ORG_ADMIN') ? 'Admin' : 'Member'}</span></td>
            <td className="small">{m.roles.map((r) => ACCESS[r] ?? r).filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</td>
            <td><span className="badge green">Active</span></td>
            <td className="small">{m.lastActiveAt ? ago(m.lastActiveAt) : '—'}</td>
          </tr>
        ))}</tbody>
      </table>
    </section>
  )
}

function RolesSummary({ members }: { members: OrgMember[] }) {
  const approvers = members.filter((m) => m.roles.includes('APPROVER'))
  const legal = members.filter((m) => m.roles.includes('LEGAL_REVIEWER'))
  const budget = members.filter((m) => m.roles.includes('BUDGET_OWNER'))
  const card = (icon: 'contract' | 'wallet' | 'gear', title: string, people: OrgMember[]) => (
    <div className="authority-card"><Icon name={icon} /><span><strong>{title}</strong><br />
      <span className="muted small">{people.length ? people.map((p) => p.displayName).join(', ') : 'Nobody assigned'}</span></span></div>
  )
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Authority &amp; controls</h2></div>
      <div className="authority-row">
        {card('contract', 'Contract approval authority', [...approvers, ...legal].filter((v, i, a) => a.indexOf(v) === i))}
        {card('wallet', 'Payment approval authority', [...approvers, ...budget].filter((v, i, a) => a.indexOf(v) === i))}
        <div className="authority-card"><Icon name="gear" /><span><strong>Engagement policy controls</strong><br /><span className="muted small">Policy profiles arrive with enterprise policies</span></span></div>
      </div>
    </section>
  )
}

function RolesDetail({ members, canManage }: { members: OrgMember[]; canManage: boolean }) {
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Roles &amp; authority</h2>{canManage && <Link className="btn btn-secondary btn-sm" to="/app/enterprise/team">Change roles &amp; limits</Link>}</div>
      <p className="muted small">Authority is explicit and separated: the person who requests is not the person who approves, and only the Exception Authority can approve policy exceptions.</p>
      <table className="data">
        <thead><tr><th>Role</th><th>What it allows</th><th>Held by</th></tr></thead>
        <tbody>{(Object.keys(ORG_ROLE_INFO) as OrgRole[]).map((r) => {
          const holders = members.filter((m) => m.roles.includes(r))
          return (
            <tr key={r}><td><strong>{ORG_ROLE_INFO[r].label}</strong></td><td className="small">{ORG_ROLE_INFO[r].desc}</td>
              <td className="small">{holders.length ? holders.map((h) => `${h.displayName}${h.spendLimit && r === 'APPROVER' ? ` (up to ${formatMoney(h.spendLimit)})` : ''}`).join(', ') : <span className="muted">Nobody</span>}</td></tr>
          )
        })}</tbody>
      </table>
    </section>
  )
}

function BillingList({ billing }: { billing: BillingContact[] }) {
  if (billing.length === 0) return <p className="muted small" style={{ margin: 0 }}>No billing contact yet.</p>
  return (
    <ul className="pro-list">{billing.map((b) => (
      <li key={b.identityId}><Avatar name={b.displayName} size={32} /><span><strong>{b.displayName}</strong><br /><span className="muted small">{b.email}</span></span>
        <span className={`badge ${b.isPrimary ? 'green' : ''}`}>{b.isPrimary ? 'Primary' : 'Backup'}</span></li>
    ))}</ul>
  )
}

function BillingForm({ org, members, billing, onSaved }: { org: Organization; members: OrgMember[]; billing: BillingContact[]; onSaved: (b: BillingContact[]) => void }) {
  const [primary, setPrimary] = useState(billing.find((b) => b.isPrimary)?.identityId ?? members[0]?.identityId ?? '')
  const [backup, setBackup] = useState(billing.find((b) => !b.isPrimary)?.identityId ?? '')
  const [error, setError] = useState<unknown>(null)
  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try { onSaved(await orgApi.setBillingContacts(org.id, primary, backup || null)) } catch (err) { setError(err) }
  }
  return (
    <form onSubmit={save} style={{ marginTop: 16 }}>
      <ErrorAlert error={error} />
      <div className="row">
        <Field label="Primary contact" id="bc-primary">
          <select id="bc-primary" className="input" value={primary} onChange={(e) => setPrimary(e.target.value)}>
            {members.map((m) => <option key={m.identityId} value={m.identityId}>{m.displayName} — {m.email}</option>)}
          </select>
        </Field>
        <Field label="Backup contact (optional)" id="bc-backup">
          <select id="bc-backup" className="input" value={backup} onChange={(e) => setBackup(e.target.value)}>
            <option value="">None</option>
            {members.filter((m) => m.identityId !== primary).map((m) => <option key={m.identityId} value={m.identityId}>{m.displayName}</option>)}
          </select>
        </Field>
      </div>
      <div style={{ height: 12 }} />
      <button className="btn btn-primary" disabled={!primary}>Save billing contacts</button>
    </form>
  )
}

function ProfileForm({ org, onDone }: { org: Organization; onDone: (o: Organization | null) => void }) {
  const [f, setF] = useState({ name: org.name, industry: org.industry ?? '', timeZone: org.timeZone ?? '' })
  const [error, setError] = useState<unknown>(null)
  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try { onDone(await orgApi.update(org.id, f)) } catch (err) { setError(err) }
  }
  return (
    <form onSubmit={save}>
      <ErrorAlert error={error} />
      <Field label="Organisation name" id="o-name"><input id="o-name" className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></Field>
      <div className="row">
        <Field label="Industry" id="o-ind">
          <select id="o-ind" className="input" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })}>
            <option value="">Select…</option>{INDUSTRIES.map((i) => <option key={i}>{i}</option>)}
          </select>
        </Field>
        <Field label="Time zone" id="o-tz">
          <select id="o-tz" className="input" value={f.timeZone} onChange={(e) => setF({ ...f, timeZone: e.target.value })}>
            <option value="">Select…</option>{TIME_ZONES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
      </div>
      <p className="muted small">Primary region: {countryName(org.country)} (set at sign-up).</p>
      <div className="row"><button type="button" className="btn btn-secondary" onClick={() => onDone(null)}>Cancel</button><button className="btn btn-primary">Save profile</button></div>
    </form>
  )
}
