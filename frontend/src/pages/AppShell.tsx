import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { firmApi, orgApi } from '../api/orgs'
import { DASHBOARD_FOR_PERSONA, ROLE_LABEL } from '../api/auth'
import { useAuth } from '../auth/AuthContext'

const DASH_LABEL: Record<string, string> = {
  buyer: 'Buyer dashboard',
  professional: 'Professional dashboard',
  firm: 'Firm dashboard',
  enterprise: 'Enterprise dashboard',
  ops: 'Operations',
}

/** Signed-in layout. The sidebar only lists areas this account's roles can use. */
export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [inviteCount, setInviteCount] = useState(0)
  const [inFirm, setInFirm] = useState(false)

  // Pending invitations badge + whether this professional belongs to a firm.
  useEffect(() => {
    Promise.all([orgApi.myInvitations(), firmApi.myInvitations(), firmApi.mine()])
      .then(([o, f, firms]) => { setInviteCount(o.length + f.length); setInFirm(firms.length > 0) })
      .catch(() => {})
  }, [location.pathname])
  if (!user) return null

  const dashboards = [...new Set(user.personas.map((p) => DASHBOARD_FOR_PERSONA[p]))]
  const isStaff = user.platformRoles.length > 0
  const isAdmin = user.platformRoles.includes('PLATFORM_ADMIN')
  const initials = user.displayName.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <>
      <header className="site-header">
        <div className="inner">
          <NavLink className="logo" to={`/app/${user.defaultDashboard}`} aria-label="Dashboard home">
            <img src="/logo.png" alt="Zoikorum" />
          </NavLink>
          <div style={{ flex: 1 }} />
          <div className="user-menu">
            <div className="badges" aria-label="Your roles">
              {[...user.personas, ...user.platformRoles].map((r) => <span key={r} className="badge">{ROLE_LABEL[r] ?? r}</span>)}
            </div>
            <span className="avatar" aria-hidden>{initials}</span>
            <span>{user.displayName}</span>
            <button className="btn btn-secondary btn-sm" onClick={async () => { await logout(); navigate('/login') }}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <div className="app">
        <nav className="sidebar" aria-label="Workspace">
          {dashboards.length > 0 && <div className="group">Workspaces</div>}
          {dashboards.map((d) => (
            <div key={d}>
              <NavLink to={`/app/${d}`} end>{DASH_LABEL[d]}</NavLink>
              {d === 'enterprise' && <>
                <NavLink className="sub" to="/app/enterprise/team">Team &amp; roles</NavLink>
                <NavLink className="sub" to="/app/enterprise/structure">Structure</NavLink>
              </>}
              {d === 'firm' && <>
                <NavLink className="sub" to="/app/firm/team">Firm team</NavLink>
                <NavLink className="sub" to="/app/firm/profile">Firm profile</NavLink>
              </>}
              {d === 'professional' && inFirm && !dashboards.includes('firm') && (
                <NavLink className="sub" to="/app/firm/team">My firm</NavLink>
              )}
            </div>
          ))}
          {isStaff && (
            <>
              <div className="group">Staff</div>
              <NavLink to="/app/ops" end>{DASH_LABEL.ops}</NavLink>
              {isAdmin && <NavLink to="/app/ops/staff">Staff &amp; roles</NavLink>}
            </>
          )}
          <div className="group">Account</div>
          <NavLink to="/app/invitations">Invitations{inviteCount > 0 && <span className="count">{inviteCount}</span>}</NavLink>
          <NavLink to="/app/account">Profile &amp; roles</NavLink>
          <NavLink to="/app/security">Security</NavLink>
        </nav>
        <main className="main">
          <Outlet />
        </main>
      </div>
    </>
  )
}
