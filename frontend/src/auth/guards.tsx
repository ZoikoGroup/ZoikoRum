import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import type { Persona, PlatformRole } from '../api/auth'
import { useAuth } from './AuthContext'

/** Signed-in users only. Accounts whose role demands MFA are sent to set it up first. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading" aria-busy="true">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (user.mfaRequired && location.pathname !== '/app/security') {
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

/** Pages like /login: bounce signed-in users to their dashboard. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (user) return <Navigate to={`/app/${user.defaultDashboard}`} replace />
  return <>{children}</>
}
