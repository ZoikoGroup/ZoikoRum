import type { ReactNode } from 'react'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import type { Persona, PlatformRole } from '../api/auth'
import { useAuth } from './AuthContext'

/** Signed-in users only. Accounts whose role demands MFA are sent to set it up first. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading" aria-busy="true">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
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

/** Only same-site app/invite paths may be used as a post-login destination (no open redirects). */
// eslint-disable-next-line react-refresh/only-export-components
export function safeNextPath(next: string | null | undefined): string | null {
  return next && /^\/(app|invite)(\/|\?|$)/.test(next) ? next : null
}

/** Pages like /login: bounce signed-in users to ?next (e.g. an invite link) or their dashboard. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const [params] = useSearchParams()
  if (loading) return null
  if (user) {
    const dest = user.status === 'SUSPENDED' ? '/app/safety' : user.mfaRequired ? '/app/security' : safeNextPath(params.get('next')) ?? `/app/${user.defaultDashboard}`
    return <Navigate to={dest} replace />
  }
  return <>{children}</>
}
