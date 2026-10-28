import { Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { firmApi } from '../api/orgs'
import { messagingApi } from '../api/messaging'
import { savedApi } from '../api/saved'
import { notificationApi } from '../api/notifications'
import { useActionCounts } from '../components/actionCounts'
import { DASHBOARD_FOR_PERSONA, PLATFORM_ROLES, ROLE_LABEL } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/dashboard'
import { GlobalSearch } from '../components/GlobalSearch'
import { DuplicateNotice } from '../components/DuplicateNotice'
import { dashboardPath, isStaffPath, STAFF_PREFIX } from '../staffRoutes'
import { useCapabilities, StaffSessionNotice } from '../auth/capabilities'

  /* Signed-in layout: navy sidebar (only the areas this account's roles can use) and a top bar with
   search, notifications and the account menu. Areas still being built are listed as "Soon", not linked. */

function Item({ to, icon, children, end, count }: { to: string; icon: IconName; children: ReactNode; end?: boolean; count?: number }) {
  return (
    <NavLink to={to} end={end} className="side-link">
      <Icon name={icon} /><span>{children}</span>{!!count && <span className="count">{count}</span>}
    </NavLink>
  )
}

/* Staff console navigation (Admin Navigation Registry): seven groups; each item shows only with its page's read
   capability (GET /v1/admin/me/capabilities). Nothing staff-only shows while those load, or if they cannot be loaded. */
type NavItem = { to: string; label: string; icon: IconName; cap: string }
const P = STAFF_PREFIX
const STAFF_NAV: { title: string; items: NavItem[] }[] = [
  { title: 'Overview', items: [
    { to: `${P}/command-center`, label: 'Command Center', icon: 'home', cap: 'dashboard.read' },
    { to: `${P}/my-work-queue`, label: 'My Work Queue', icon: 'list', cap: 'work.read' },
    { to: `${P}/analytics-insights`, label: 'Analytics & Insights', icon: 'chart', cap: 'analytics.read' },
  ] },
  { title: 'People & Organizations', items: [
    { to: `${P}/accounts-organizations`, label: 'Accounts & Organizations', icon: 'building', cap: 'accounts.read' },
    { to: `${P}/professional-directory`, label: 'Professional Directory', icon: 'team', cap: 'professionals.read' },
    { to: `${P}/enterprise-readiness`, label: 'Enterprise Readiness', icon: 'contract', cap: 'enterprise.read' },
    { to: `${P}/duplicate-identity-cases`, label: 'Duplicate Identity Cases', icon: 'team', cap: 'identity_cases.read' },
  ] },
  { title: 'Trust, Risk & Compliance', items: [
    { to: `${P}/verification-center`, label: 'Verification Center', icon: 'shield', cap: 'verification.read' },
    { to: `${P}/trust-safety`, label: 'Trust & Safety', icon: 'shield', cap: 'safety.read' },
    { to: `${P}/dispute-resolution`, label: 'Dispute Resolution', icon: 'scale', cap: 'disputes.read' },
    { to: `${P}/audit-evidence`, label: 'Audit & Evidence', icon: 'contract', cap: 'audit.read' },
  ] },
  { title: 'Engagement Operations', items: [
    { to: `${P}/engagement-oversight`, label: 'Engagement Oversight', icon: 'briefcase', cap: 'engagements.read' },
    { to: `${P}/contracts-milestones`, label: 'Contracts & Milestones', icon: 'contract', cap: 'contracts.read' },
    { to: `${P}/taxonomy-standards`, label: 'Taxonomy & Standards', icon: 'layers', cap: 'taxonomy.read' },
  ] },
  { title: 'Financial Operations', items: [
    { to: `${P}/protected-payments`, label: 'Protected Payments', icon: 'wallet', cap: 'payments.read' },
    { to: `${P}/reconciliation`, label: 'Reconciliation', icon: 'refresh', cap: 'recon.read' },
    { to: `${P}/financial-exceptions`, label: 'Financial Exceptions', icon: 'alert', cap: 'finexceptions.read' },
  ] },
  { title: 'Platform Reliability', items: [
    { to: `${P}/incident-command`, label: 'Incident Command', icon: 'alert', cap: 'incidents.read' },
    { to: `${P}/service-health-workers`, label: 'Service Health & Workers', icon: 'pulse', cap: 'health.read' },
    { to: `${P}/feature-controls`, label: 'Feature Controls', icon: 'sliders', cap: 'switches.read' },
    { to: `${P}/failed-event-deliveries`, label: 'Failed Event Deliveries', icon: 'mail', cap: 'dlq.read' },
  ] },
  { title: 'Administration & Support', items: [
    { to: `${P}/approvals`, label: 'Approvals', icon: 'check', cap: 'approvals.read' },
    { to: `${P}/staff-access-control`, label: 'Staff & Access Control', icon: 'lock', cap: 'iam.read' },
    { to: `${P}/support-cases`, label: 'Support Cases', icon: 'help', cap: 'support.read' },
    { to: `${P}/platform-configuration`, label: 'Platform Configuration', icon: 'gear', cap: 'configuration.read' },
    { to: `${P}/ai-governance`, label: 'AI Governance', icon: 'eye', cap: 'ai.read' },
  ] },
]
const COLLAPSED_KEY = 'zk.staffNav.collapsed'
function readCollapsed(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]') as string[]) } catch { return new Set() }
}


export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [inFirm, setInFirm] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(readCollapsed)
  useEffect(() => { try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed])) } catch { /* private mode */ } }, [collapsed])
  const [unreadMessages, setUnreadMessages] = useState(0)
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  // Menus remember the page they were opened on, so navigating closes them without an effect.
  const [openAt, setOpenAt] = useState<string | null>(null)
  const [bellAt, setBellAt] = useState<string | null>(null)
  const open = openAt === location.pathname
  const bellOpen = bellAt === location.pathname
  const setOpen = (value: boolean) => setOpenAt(value ? location.pathname : null)
  const setBellOpen = (value: boolean) => setBellAt(value ? location.pathname : null)

  // Mobile menu drawer (WCAG 2.2 AA): focus moves into it on open and stays there (Tab wraps), Escape closes it, and
  // focus returns to the menu button (or to the page, when a link in it was followed).
  const sideRef = useRef<HTMLElement>(null)
  const menuBtnRef = useRef<HTMLButtonElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const wasOpen = useRef(false)
  // Profile menu (<details>): closes on an outside click, on Escape, and after a menu link is followed.
  const userMenuRef = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    const close = () => { if (userMenuRef.current) userMenuRef.current.open = false }
    const onDown = (e: Event) => { const el = userMenuRef.current; if (el?.open && !el.contains(e.target as Node)) close() }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && userMenuRef.current?.open) { close(); userMenuRef.current.querySelector('summary')?.focus() } }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onDown); document.removeEventListener('keydown', onKey) }
  }, [])
  useEffect(() => {
    if (!open) {
      if (wasOpen.current) {
        wasOpen.current = false
        const navigated = openAt !== null  // closed by following a link, not by Escape / the backdrop
        const at = document.activeElement
        if (!at || at === document.body || sideRef.current?.contains(at)) (navigated ? mainRef.current : menuBtnRef.current)?.focus()
      }
      return
    }
    wasOpen.current = true
    const side = sideRef.current
    if (!side) return
    const focusable = () => Array.from(side.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), summary, input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'))
      .filter((el) => el.getClientRects().length > 0)  // skips links inside collapsed groups
    focusable()[0]?.focus()
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); setOpenAt(null); return }
      if (e.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0], last = items[items.length - 1], at = document.activeElement
      if (e.shiftKey && (at === first || !side.contains(at))) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (at === last || !side.contains(at))) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, openAt])
  // "Waiting for you" counts: a red number on each tab and the total on the bell.
  const capabilities = useCapabilities()
  const counts = useActionCounts(user, location.pathname, capabilities.status === 'ready' ? capabilities.caps : null)
  const n = (path: string) => counts.byPath[path] ?? 0

  // Firm membership (for the "My Firm" link): once per signed-in user.
  useEffect(() => {
    let active = true
    firmApi.mine().then((firms) => { if (active) setInFirm(firms.length > 0) }).catch(() => {})
    return () => { active = false }
  }, [user?.id])

  // Update immediately after local reads, then reconcile against the server.
  useEffect(() => {
    let active = true
    let revision = 0
    const pendingReads = new Set<string>()
    let followUp: number | undefined
    const load = () => {
      const request = ++revision
      notificationApi.count().then(r => {
        if (active && request === revision && pendingReads.size === 0) setUnreadNotifications(r.unread)
      }).catch(() => {})
    }
    const changed = () => {
      load()
      window.clearTimeout(followUp)
      followUp = window.setTimeout(load, 1500) // worker-produced notifications
    }
    const read = (event: Event) => {
      const { id, phase } = (event as CustomEvent<{ id: string; phase: 'start' | 'complete' | 'rollback' }>).detail
      revision++ // polling must not undo a read while its request is pending
      if (phase === 'start') {
        if (pendingReads.has(id)) return
        pendingReads.add(id)
        setUnreadNotifications(count => Math.max(0, count - 1))
      } else if (pendingReads.delete(id)) {
        if (phase === 'rollback') setUnreadNotifications(count => count + 1)
        if (pendingReads.size === 0) load()
      }
    }
    load()
    const timer = window.setInterval(load, 15000)
    window.addEventListener('zk:activity', changed)
    window.addEventListener('zk:notification-read', read)
    window.addEventListener('focus', load)
    return () => {
      active = false
      window.clearInterval(timer)
      window.clearTimeout(followUp)
      window.removeEventListener('zk:activity', changed)
      window.removeEventListener('zk:notification-read', read)
      window.removeEventListener('focus', load)
    }
  }, [user?.id])

  // Unread message threads: poll every 12s for accounts that can message.
  const canMessage = !!user?.personas.some((role) => ['BUYER', 'PROFESSIONAL', 'ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER'].includes(role))
  useEffect(() => {
    if (!canMessage) return
    let active = true
    const load = () => { messagingApi.summary().then((summary) => { if (active) setUnreadMessages(summary.unreadThreads) }).catch(() => { if (active) setUnreadMessages(0) }) }
    load()
    const timer = window.setInterval(load, 12000)
    window.addEventListener('zk:message-read', load)
    window.addEventListener('zk:activity', load)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('zk:message-read', load); window.removeEventListener('zk:activity', load) }
  }, [user?.id, canMessage])
  // Saved professionals + saved searches count on the sidebar entry; refreshed whenever something is saved or removed.
  const canSaveItems = !!user?.personas.some((role) => ['BUYER', 'ENTERPRISE_ADMIN', 'ENTERPRISE_MEMBER'].includes(role))
  const [savedCount, setSavedCount] = useState(0)
  useEffect(() => {
    if (!canSaveItems) return
    let active = true
    const load = () => {
      Promise.all([savedApi.list().catch(() => []), savedApi.searches().catch(() => [])])
        .then(([pros, searches]) => { if (active) setSavedCount(pros.length + searches.length) })
    }
    load()
    window.addEventListener('zk:saved', load)
    return () => { active = false; window.removeEventListener('zk:saved', load) }
  }, [user?.id, canSaveItems])
  if (!user) return null

  const dashboards = new Set(user.personas.map((p) => DASHBOARD_FOR_PERSONA[p]))
  const isStaff = user.platformRoles.length > 0
  const customer = dashboards.has('enterprise') ? 'enterprise' : dashboards.has('buyer') ? 'buyer' : null
  const staffOnly = user.platformRoles.length > 0 && user.personas.length === 0
  const initials = user.displayName.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  // Staff: the most senior role (PLATFORM_ROLES runs from Platform Admin down), not the first alphabetically.
  const staffRoles = PLATFORM_ROLES.filter((r) => user.platformRoles.includes(r))
  const staffName = staffRoles.length ? ROLE_LABEL[staffRoles[0]] + (staffRoles.length > 1 ? ` +${staffRoles.length - 1} roles` : '') : ''
  const roleName = customer && !user.platformRoles.length && !dashboards.has('professional') && !dashboards.has('firm')
    ? 'Customer' : ROLE_LABEL[user.primaryPersona ?? ''] ?? (staffName || '')

  // The bell: work waiting for you (red tab counts) plus unread notifications.
  const bellItems = unreadNotifications > 0
    ? [...counts.items, { label: 'New notifications', to: '/app/notifications', count: unreadNotifications }] : counts.items
  const bellTotal = counts.total + unreadNotifications

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content" onClick={(e) => { e.preventDefault(); mainRef.current?.focus() }}>Skip to main content</a>
      <aside ref={sideRef} id="app-sidebar" className={`side ${open ? 'open' : ''}`} aria-label="Workspace">
        <NavLink className="side-logo" to={dashboardPath(user)} aria-label="Dashboard home">
          <img src="/logo.png" alt="Zoikorum" />
        </NavLink>

        {customer && <>
          <div className="side-group">Customer</div>
          <Item to={`/app/${customer}`} icon="home" end>Dashboard</Item>
          <Item to="/app/find" icon="search">Find Professionals</Item>
          <Item to="/app/saved" icon="bookmark" count={savedCount}>Saved Professionals</Item>
          <Item to="/app/requests" icon="request">Requests</Item>
          <Item to="/app/briefs" icon="mail">Open Briefs</Item>
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
          <Item to="/app/professional/briefs" icon="mail">Open Briefs</Item>
          <Item to="/app/professional/engagements" icon="briefcase" count={n('/app/professional/engagements')}>Engagements</Item>
          <Item to="/app/messages" icon="message" count={unreadMessages}>Messages</Item>
          <Item to="/app/professional/buyers" icon="bookmark">Saved Buyers</Item>
          <Item to="/app/professional/earnings" count={n('/app/professional/earnings')} icon="wallet">Earnings</Item>
          <Item to="/app/professional/insights" icon="star">Performance</Item>
          <Item to="/app/professional/enterprise" icon="building">Enterprise Ready</Item>
          <Item to="/app/professional/disputes" count={n('/app/professional/disputes')} icon="shield">Disputes</Item>
        </>}

        {dashboards.has('firm') && <>
          <div className="side-group">Firm</div>
          <Item to="/app/firm" icon="building" end>Firm Dashboard</Item>
          <Item to="/app/firm/team" icon="team">Firm Team</Item>
          <Item to="/app/firm/profile" icon="user">Firm Profile</Item>
          <Item to="/app/firm/verification" icon="shield">Firm Verification</Item>
        </>}

        {isStaff && capabilities.status === 'ready' && STAFF_NAV.map((section) => {
          const items = section.items.filter((i) => capabilities.has(i.cap))
          if (!items.length) return null
          const here = items.some((i) => location.pathname === i.to || location.pathname.startsWith(`${i.to}/`))
          return (
            <details key={section.title} className="side-section" open={here || !collapsed.has(section.title)}
              onToggle={(e) => { const isOpen = (e.currentTarget as HTMLDetailsElement).open
                setCollapsed((s) => { const next = new Set(s); if (isOpen) next.delete(section.title); else next.add(section.title); return next }) }}>
              <summary className="side-group">{section.title}</summary>
              {items.map((i) => <Item key={i.to} to={i.to} icon={i.icon} count={n(i.to)}>{i.label}</Item>)}
            </details>
          )
        })}

        <div className="side-group">Account</div>
        {customer && <>
          <Item to="/app/organisation" icon="building">Organisation</Item>
          {customer === 'enterprise' && <Item to="/app/enterprise/structure" icon="folder">Structure &amp; Budgets</Item>}
          <Item to="/app/verification" icon="shield">Verification</Item>
        </>}
        {/* Organisation invitations and Safety & Appeals belong to customer and professional accounts, not staff-only ones. */}
        {!staffOnly && <Item to="/app/invitations" icon="mail" count={n('/app/invitations')}>Invitations</Item>}
        <Item to="/app/settings" icon="gear">Settings</Item>
        {staffOnly && <Item to="/app/security" icon="lock">Two-step &amp; Passkeys</Item>}
        {!staffOnly && <Item to="/app/safety" icon="shield">Safety &amp; Appeals</Item>}
        {!customer && !user.platformRoles.length && <Item to="/app/reports" icon="contract">Reports</Item>}
        <Item to="/app/help" icon="help">Help &amp; Support</Item>

        <div className="side-support">
          <strong>Need support?</strong>
          <span>Answers about verification, contracts and payments.</span>
          <NavLink to="/app/help" className="btn btn-sm">Get help</NavLink>
        </div>
      </aside>
      {open && <button className="side-backdrop" aria-label="Close menu" tabIndex={-1} onClick={() => setOpen(false)} />}

      <div className="shell-main">
        <header className="topbar">
          <button ref={menuBtnRef} className="icon-btn menu-btn" aria-label="Open menu" aria-expanded={open} aria-controls="app-sidebar" onClick={() => setOpen(true)}>
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          </button>
          <GlobalSearch side={customer ? 'buyer' : dashboards.has('professional') ? 'professional' : null}
            staff={isStaff && isStaffPath(location.pathname)} />
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
          <details ref={userMenuRef} className="user-menu-pop">
            <summary>
              <span className="avatar" aria-hidden>{initials}</span>
              <span className="who"><strong>{user.displayName}</strong><span>{roleName}</span></span>
            </summary>
            <div className="menu card" onClick={() => { if (userMenuRef.current) userMenuRef.current.open = false }}>
              <div className="badges" style={{ padding: '4px 4px 10px' }}>
                {[...user.personas, ...user.platformRoles].map((r) => <span key={r} className="badge">{ROLE_LABEL[r] ?? r}</span>)}
              </div>
              <NavLink to="/app/settings">Settings</NavLink>
              <NavLink to="/app/account">Profile &amp; roles</NavLink>
              <NavLink to="/app/security">Two-step verification</NavLink>
              <button onClick={async () => { const staff = (user?.platformRoles.length ?? 0) > 0; await logout()
                navigate(staff ? '/staff/login' : '/login') }}>Sign out</button>
            </div>
          </details>
        </header>
        <main ref={mainRef} id="main-content" tabIndex={-1} className="main">
          {user.status === 'SUSPENDED' && <div className="alert alert-warn" role="status">Your account is restricted. <NavLink to="/app/safety">Read the notice and submit an appeal</NavLink>.</div>}
          {user.mfaBypass && <div className="alert alert-warn" role="status" style={{ margin: '0 0 12px' }}>Development mode: two-step verification (authenticator codes) is switched off. Never use this setting in production.</div>}
          <DuplicateNotice />
          <StaffSessionNotice />
          <Suspense fallback={<p className="muted page-loading">Loading…</p>}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  )
}
