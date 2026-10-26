import type { ReactNode } from 'react'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import type { Persona, PlatformRole } from '../api/auth'
import { useAuth } from './AuthContext'
import { dashboardPath, isStaffPath } from '../staffRoutes'

/** Signed-in users only. Accounts whose role demands MFA are sent to set it up first. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading" aria-busy="true">Loading…</div>
  if (!user) {
    const staffArea = isStaffPath(location.pathname)
    // Keep the whole destination (query and hash too, e.g. /app/requests/new?pro=...) so sign-in, or sign-up from the
    // sign-in page, lands exactly there. It travels in navigation state, not the address, so signing out on purpose
    // (which navigates to a plain /login afterwards) does not send the next person back to the last page.
    const from = location.pathname + location.search + location.hash
    return <Navigate to={staffArea ? '/staff/login' : '/login'} replace state={{ from: safeNextPath(from) ?? undefined }} />
  }
  if (user.status === 'SUSPENDED' && location.pathname !== '/app/safety') return <Navigate to="/app/safety" replace />
  if (user.status !== 'SUSPENDED' && user.mfaRequired && location.pathname !== '/app/security') {
    return <Navigate to="/app/security" replace state={{ required: true }} />
  }
  return <>{children}</>
}

/**
 * Role gate for a page. The backend enforces the same rule on every API call -
 * this only keeps people from landing on screens they cannot use.
 */
export function RequireRole({ any, children }: { any: (Persona | PlatformRole)[]; children: ReactNode }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  const held = new Set<string>([...user.personas, ...user.platformRoles])
  if (!any.some((r) => held.has(r))) return <Navigate to="/app/forbidden" replace state={{ needed: any }} />
  return <>{children}</>
}

/** Only same-site relative paths into the app, invitations, staff console or public profiles may be used as a
    post-login destination (no open redirects): never another origin ("//host", "https:", "/\host") or odd characters. */
// eslint-disable-next-line react-refresh/only-export-components
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next || next.length > 2000 || /[\\\s]/.test(next) || next.startsWith('//')) return null
  return /^\/(app|invite|platform-admin|professionals|categories)(\/|\?|#|$)/.test(next) ? next : null
}

/** Pages like /login: bounce signed-in users to ?next (e.g. an invite link) or their dashboard. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const [params] = useSearchParams()
  if (loading) return null
  if (user) {
    const dest = user.status === 'SUSPENDED' ? '/app/safety' : user.mfaRequired ? '/app/security' : safeNextPath(params.get('next')) ?? dashboardPath(user)
    return <Navigate to={dest} replace />
  }
  return <>{children}</>
}
