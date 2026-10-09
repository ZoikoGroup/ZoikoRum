import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { firmApi } from '../api/orgs'
import { messagingApi } from '../api/messaging'
import { notificationApi } from '../api/notifications'
import { useActionCounts } from '../components/actionCounts'
import { DASHBOARD_FOR_PERSONA, ROLE_LABEL } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/dashboard'
import { GlobalSearch } from '../components/GlobalSearch'
import { DuplicateNotice } from '../components/DuplicateNotice'

  /* Signed-in layout: navy sidebar (only the areas this account's roles can use) and a top bar with
   search, notifications and the account menu. Areas still being built are listed as "Soon", not linked. */

function Item({ to, icon, children, end, count }: { to: string; icon: IconName; children: ReactNode; end?: boolean; count?: number }) {
  return (
    <NavLink to={to} end={end} className="side-link">
      <Icon name={icon} /><span>{children}</span>{!!count && <span className="count">{count}</span>}
    </NavLink>
  )
}


export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [inFirm, setInFirm] = useState(false)
  const [unreadMessages, setUnreadMessages] = useState(0)
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  // Menus remember the page they were opened on, so navigating closes them without an effect.
  const [openAt, setOpenAt] = useState<string | null>(null)
  const [bellAt, setBellAt] = useState<string | null>(null)
  const open = openAt === location.pathname
  const bellOpen = bellAt === location.pathname
  const setOpen = (value: boolean) => setOpenAt(value ? location.pathname : null)
  const setBellOpen = (value: boolean) => setBellAt(value ? location.pathname : null)
  // "Waiting for you" counts: a red number on each tab and the total on the bell.
  const counts = useActionCounts(user, location.pathname)
  const n = (path: string) => counts.byPath[path] ?? 0

  // Firm membership (for the "My Firm" link): once per signed-in user.
  useEffect(() => {
    let active = true
    firmApi.mine().then((firms) => { if (active) setInFirm(firms.length > 0) }).catch(() => {})
    return () => { active = false }
  }, [user?.id])

  // Unread notifications: poll every 15s while signed in.
  useEffect(() => {
    let active = true
    const load = () => notificationApi.count().then((r) => { if (active) setUnreadNotifications(r.unread) }).catch(() => {})
    load()
    const timer = window.setInterval(load, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [user?.id])

  // Unread message threads: poll every 12s for accounts that can message.
  const canMessage = !!user?.personas.some((role) => ['BUYER', 'PROFESSIONAL', 'ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER'].includes(role))
  useEffect(() => {
    if (!canMessage) return
    let active = true
    const load = () => { messagingApi.summary().then((summary) => { if (active) setUnreadMessages(summary.unreadThreads) }).catch(() => { if (active) setUnreadMessages(0) }) }
    load()
    const timer = window.setInterval(load, 12000)
    return () => { active = false; window.clearInterval(timer) }
  }, [user?.id, canMessage])
  if (!user) return null

  const dashboards = new Set(user.personas.map((p) => DASHBOARD_FOR_PERSONA[p]))
  const isStaff = user.platformRoles.length > 0
  const isAdmin = user.platformRoles.includes('PLATFORM_ADMIN')
  const isOfficer = user.platformRoles.includes('COMPLIANCE_OFFICER')
  const customer = dashboards.has('enterprise') ? 'enterprise' : dashboards.has('buyer') ? 'buyer' : null
  const initials = user.displayName.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  const roleName = customer && !user.platformRoles.length && !dashboards.has('professional') && !dashboards.has('firm')
    ? 'Customer' : ROLE_LABEL[user.primaryPersona ?? ''] ?? ROLE_LABEL[user.platformRoles[0] ?? ''] ?? ''

  // The bell: work waiting for you (red tab counts) plus unread notifications.
  const bellItems = unreadNotifications > 0
    ? [...counts.items, { label: 'New notifications', to: '/app/notifications', count: unreadNotifications }] : counts.items
  const bellTotal = counts.total + unreadNotifications

  return (
    <div className="shell">
      <aside className={`side ${open ? 'open' : ''}`} aria-label="Workspace">
        <NavLink className="side-logo" to={`/app/${user.defaultDashboard}`} aria-label="Dashboard home">
          <img src="/logo.png" alt="Zoikorum" />
        </NavLink>

        {customer && <>
          <div className="side-group">Customer</div>
          <Item to={`/app/${customer}`} icon="home" end>Dashboard</Item>
          <Item to="/app/find" icon="search">Find Professionals</Item>
          <Item to="/app/saved" icon="bookmark">Saved Professionals</Item>
          <Item to="/app/requests" icon="request">Requests</Item>
          <Item to="/app/proposals" count={n('/app/proposals')} icon="proposal">Proposals</Item>
          <Item to="/app/engagements" count={n('/app/engagements')} icon="briefcase">Engagements</Item>
          <Item to="/app/payments" icon="wallet">Payments &amp; Protection</Item>
          <Item to="/app/messages" icon="message" count={unreadMessages}>Messages</Item>
          <Item to="/app/disputes" count={n('/app/disputes')} icon="shield">Disputes</Item>
          <Item to="/app/policies" icon="contract">Policies &amp; Approvals</Item>
          <Item to="/app/webhooks" icon="gear">Enterprise Webhooks</Item>
          <Item to="/app/reports" icon="contract">Reports</Item>
        </>}

        {dashboards.has('professional') && <>
          <div className="side-group">Professional</div>
          <Item to="/app/professional" icon="building" end>Dashboard</Item>
          <Item to="/app/professional/profile" icon="user">My Profile</Item>
          <Item to="/app/professional/offerings" icon="request">Service Offerings</Item>
          <Item to="/app/professional/verification" icon="shield">Verification &amp; Trust</Item>
          {inFirm && !dashboards.has('firm') && <Item to="/app/firm/team" icon="team">My Firm</Item>}
          <Item to="/app/professional/requests" icon="proposal" count={n('/app/professional/requests')}>Requests</Item>
          <Item to="/app/professional/engagements" icon="briefcase" count={n('/app/professional/engagements')}>Engagements</Item>
          <Item to="/app/messages" icon="message" count={unreadMessages}>Messages</Item>
          <Item to="/app/professional/buyers" icon="bookmark">Saved Buyers</Item>
          <Item to="/app/professional/earnings" count={n('/app/professional/earnings')} icon="wallet">Earnings</Item>
          <Item to="/app/professional/disputes" count={n('/app/professional/disputes')} icon="shield">Disputes</Item>
        </>}

        {dashboards.has('firm') && <>
          <div className="side-group">Firm</div>
          <Item to="/app/firm" icon="building" end>Firm Dashboard</Item>
          <Item to="/app/firm/team" icon="team">Firm Team</Item>
          <Item to="/app/firm/profile" icon="user">Firm Profile</Item>
          <Item to="/app/firm/verification" icon="shield">Firm Verification</Item>
        </>}

        {isStaff && <>
          <div className="side-group">Administration</div>
          <Item to="/app/ops" icon="building" end>Admin Dashboard</Item>
          {isOfficer && <Item to="/app/ops/verification" count={n('/app/ops/verification')} icon="shield">Verification Reviews</Item>}
          {user.platformRoles.some((r) => ['PLATFORM_ADMIN', 'TS_ANALYST'].includes(r)) && <Item to="/app/ops/users" icon="user">Users</Item>}
          {isAdmin && <Item to="/app/ops/staff" icon="team">Staff &amp; Roles</Item>}
          {isAdmin && <Item to="/app/ops/taxonomy" count={n('/app/ops/taxonomy')} icon="folder">Taxonomy</Item>}
          {user.platformRoles.some((r) => ['FINANCIAL_OPS', 'PLATFORM_ADMIN'].includes(r)) && <Item to="/app/ops/reconciliation" count={n('/app/ops/reconciliation')} icon="wallet">Reconciliation</Item>}
          {user.platformRoles.some((r) => ['TS_ANALYST', 'PLATFORM_ADMIN'].includes(r)) && <Item to="/app/ops/duplicates" count={n('/app/ops/duplicates')} icon="team">Duplicate Accounts</Item>}
          {!customer && <Item to="/professionals" icon="search">Professionals</Item>}
          {user.platformRoles.some((r) => ['MEDIATOR', 'LEGAL', 'PLATFORM_ADMIN'].includes(r)) && <Item to="/app/ops/disputes" count={n('/app/ops/disputes')} icon="shield">Disputes</Item>}
          <Item to="/app/ops/analytics" icon="contract">Platform Analytics</Item>
          <Item to="/app/ops/audit" icon="contract">Audit Exports</Item>
          <Item to="/app/ops/safety" icon="shield">Safety Cases</Item>
          {user.platformRoles.includes('AI_SAFETY_REVIEWER') && <Item to="/app/ops/ai" icon="gear">AI Governance</Item>}
          {user.platformRoles.some((r) => ['FINANCIAL_OPS', 'PLATFORM_ADMIN'].includes(r)) && <Item to="/app/ops/dead-letters" icon="gear">Failed Deliveries</Item>}
        </>}

        <div className="side-group">Account</div>
        {customer && <>
          <Item to="/app/organisation" icon="building">Organisation</Item>
          {customer === 'enterprise' && <Item to="/app/enterprise/structure" icon="folder">Structure &amp; Budgets</Item>}
          <Item to="/app/verification" icon="shield">Verification</Item>
        </>}
        <Item to="/app/invitations" icon="mail" count={n('/app/invitations')}>Invitations</Item>
        <Item to="/app/settings" icon="gear">Settings</Item>
        <Item to="/app/safety" icon="shield">Safety &amp; Appeals</Item>
        {!customer && !user.platformRoles.length && <Item to="/app/reports" icon="contract">Reports</Item>}
        <Item to="/app/help" icon="help">Help &amp; Support</Item>

        <div className="side-support">
          <strong>Need support?</strong>
          <span>Answers about verification, contracts and payments.</span>
          <NavLink to="/app/help" className="btn btn-sm">Get help</NavLink>
        </div>
      </aside>
      {open && <button className="side-backdrop" aria-label="Close menu" onClick={() => setOpen(false)} />}

      <div className="shell-main">
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label="Open menu" onClick={() => setOpen(true)}>
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          </button>
          <GlobalSearch side={customer ? 'buyer' : dashboards.has('professional') ? 'professional' : null} />
          <div style={{ flex: 1 }} />
          <NavLink to="/app/help" className="icon-btn" aria-label="Help &amp; support"><Icon name="help" /></NavLink>
          <div className="bell-pop">
            <button type="button" className="icon-btn" aria-label={`Notifications${bellTotal ? `: ${bellTotal} waiting for you` : ''}`}
              aria-expanded={bellOpen} onClick={() => {
                // Nothing waiting: open the notification history. One kind of work: go straight there. Several: show the list.
                if (bellItems.length === 0) navigate('/app/notifications')
                else if (bellItems.length === 1) { setBellOpen(false); navigate(bellItems[0].to) } else setBellOpen(!bellOpen)
              }}>
              <Icon name="bell" />{bellTotal > 0 && <span className="dot-count">{bellTotal > 99 ? '99+' : bellTotal}</span>}
            </button>
            {bellOpen && <>
              <button type="button" className="bell-backdrop" aria-label="Close notifications" onClick={() => setBellOpen(false)} />
              <div className="bell-menu card" role="menu">
                <strong>Waiting for you</strong>
                <ul>{bellItems.map((i) => (
                  <li key={i.to}><button type="button" role="menuitem" onClick={() => { setBellOpen(false); navigate(i.to) }}>
                    <span>{i.label}</span><span className="dot-count inline">{i.count}</span></button></li>))}</ul>
                <button type="button" className="text-btn small" onClick={() => { setBellOpen(false); navigate('/app/notifications') }}>All notifications</button>
              </div>
            </>}
          </div>
          <details className="user-menu-pop">
            <summary>
              <span className="avatar" aria-hidden>{initials}</span>
              <span className="who"><strong>{user.displayName}</strong><span>{roleName}</span></span>
            </summary>
            <div className="menu card">
              <div className="badges" style={{ padding: '4px 4px 10px' }}>
                {[...user.personas, ...user.platformRoles].map((r) => <span key={r} className="badge">{ROLE_LABEL[r] ?? r}</span>)}
              </div>
              <NavLink to="/app/settings">Settings</NavLink>
              <NavLink to="/app/account">Profile &amp; roles</NavLink>
              <NavLink to="/app/security">Two-step verification</NavLink>
              <button onClick={async () => { await logout(); navigate('/login') }}>Sign out</button>
            </div>
          </details>
        </header>
        <main className="main">
          {user.status === 'SUSPENDED' && <div className="alert alert-warn" role="status">Your account is restricted. <NavLink to="/app/safety">Read the notice and submit an appeal</NavLink>.</div>}
          {user.mfaBypass && <div className="alert alert-warn" role="status" style={{ margin: '0 0 12px' }}>Development mode: two-step verification (authenticator codes) is switched off. Never use this setting in production.</div>}
          <DuplicateNotice />
          <Suspense fallback={<p className="muted page-loading">Loading…</p>}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  )
}
