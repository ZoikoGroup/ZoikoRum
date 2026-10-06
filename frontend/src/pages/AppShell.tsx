import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { firmApi, orgApi } from '../api/orgs'
import { proposalApi } from '../api/proposals'
import { DASHBOARD_FOR_PERSONA, ROLE_LABEL } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/dashboard'

/* Signed-in layout: navy sidebar (only the areas this account's roles can use) and a top bar with
   search, notifications and the account menu. Areas still being built are listed as "Soon", not linked. */

function Item({ to, icon, children, end, count }: { to: string; icon: IconName; children: ReactNode; end?: boolean; count?: number }) {
  return (
    <NavLink to={to} end={end} className="side-link">
      <Icon name={icon} /><span>{children}</span>{!!count && <span className="count">{count}</span>}
    </NavLink>
  )
}

function Soon({ icon, children }: { icon: IconName; children: ReactNode }) {
  return <span className="side-link soon" aria-disabled="true"><Icon name={icon} /><span>{children}</span><em>Soon</em></span>
}

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [inviteCount, setInviteCount] = useState(0)
  const [inFirm, setInFirm] = useState(false)
  const [newRequests, setNewRequests] = useState(0)
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => {
    setOpen(false)  // close the mobile menu after navigating
    Promise.all([orgApi.myInvitations(), firmApi.myInvitations(), firmApi.mine()])
      .then(([o, f, firms]) => { setInviteCount(o.length + f.length); setInFirm(firms.length > 0) })
      .catch(() => {})
    if (user?.personas.includes('PROFESSIONAL')) proposalApi.summary('professional').then((s) => setNewRequests(s.requests.OPEN ?? 0)).catch(() => {})
  }, [location.pathname, user])
  if (!user) return null

  const dashboards = new Set(user.personas.map((p) => DASHBOARD_FOR_PERSONA[p]))
  const isStaff = user.platformRoles.length > 0
  const isAdmin = user.platformRoles.includes('PLATFORM_ADMIN')
  const isOfficer = user.platformRoles.includes('COMPLIANCE_OFFICER')
  const customer = dashboards.has('enterprise') ? 'enterprise' : dashboards.has('buyer') ? 'buyer' : null
  const initials = user.displayName.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  const roleName = customer && !user.platformRoles.length && !dashboards.has('professional') && !dashboards.has('firm')
    ? 'Customer' : ROLE_LABEL[user.primaryPersona ?? ''] ?? ROLE_LABEL[user.platformRoles[0] ?? ''] ?? ''

  function search(e: FormEvent) {
    e.preventDefault()
    const base = customer ? '/app/find' : '/professionals'
    navigate(q.trim() ? `${base}?q=${encodeURIComponent(q.trim())}` : base)
  }

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
          <Item to="/app/proposals" icon="proposal">Proposals</Item>
          <Item to="/app/engagements" icon="briefcase">Engagements</Item>
          <Item to="/app/payments" icon="wallet">Payments &amp; Protection</Item>
          <Item to="/app/messages" icon="message">Messages</Item>
        </>}

        {dashboards.has('professional') && <>
          <div className="side-group">Professional</div>
          <Item to="/app/professional" icon="building" end>Dashboard</Item>
          <Item to="/app/professional/profile" icon="user">My Profile</Item>
          <Item to="/app/professional/offerings" icon="request">Service Offerings</Item>
          <Item to="/app/professional/verification" icon="shield">Verification &amp; Trust</Item>
          {inFirm && !dashboards.has('firm') && <Item to="/app/firm/team" icon="team">My Firm</Item>}
          <Item to="/app/professional/requests" icon="proposal" count={newRequests}>Requests</Item>
          <Soon icon="contract">Engagements</Soon>
          <Soon icon="clock">Earnings</Soon>
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
          {isOfficer && <Item to="/app/ops/verification" icon="shield">Verification Reviews</Item>}
          {isAdmin && <Item to="/app/ops/staff" icon="team">Staff &amp; Roles</Item>}
          {!customer && <Item to="/professionals" icon="search">Professionals</Item>}
          <Soon icon="bell">Disputes</Soon>
          <Soon icon="contract">Reports</Soon>
        </>}

        <div className="side-group">Account</div>
        {customer && <>
          <Item to="/app/organisation" icon="building">Organisation</Item>
          {customer === 'enterprise' && <Item to="/app/enterprise/structure" icon="folder">Structure &amp; Budgets</Item>}
          <Item to="/app/verification" icon="shield">Verification</Item>
        </>}
        {!customer && <Soon icon="message">Messages</Soon>}
        <Item to="/app/invitations" icon="mail" count={inviteCount}>Invitations</Item>
        <Item to="/app/settings" icon="gear">Settings</Item>
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
          <form className="top-search" role="search" onSubmit={search}>
            <Icon name="search" />
            <input aria-label="Search professionals" placeholder="Search professionals and services…" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <div style={{ flex: 1 }} />
          <NavLink to="/app/help" className="icon-btn" aria-label="Help &amp; support"><Icon name="help" /></NavLink>
          <NavLink to="/app/invitations" className="icon-btn" aria-label={`Notifications${inviteCount ? `: ${inviteCount} new` : ''}`}>
            <Icon name="bell" />{inviteCount > 0 && <span className="dot-count">{inviteCount}</span>}
          </NavLink>
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
          <Outlet />
        </main>
      </div>
    </div>
  )
}
