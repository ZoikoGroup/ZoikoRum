import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from './AuthContext'

/* Staff capabilities (backend shared/capabilities.py): fetched once per staff sign-in from GET /v1/admin/me/capabilities
   and used for the staff sidebar, the staff route guards and row actions, instead of role lists. Default deny: while
   loading nothing staff-only shows, and on an error nothing does. The API checks every call itself. */

export interface StaffDestination { id: string; slug: string; route: string; title: string; group: string }
export interface MyCapabilities { capabilities: string[]; destinations: StaffDestination[] }
type Status = 'loading' | 'ready' | 'error' | 'none'
interface CapabilityState { status: Status; caps: ReadonlySet<string>; destinations: StaffDestination[]; has: (...caps: string[]) => boolean }

const EMPTY: ReadonlySet<string> = new Set()
const CapabilityContext = createContext<CapabilityState>({ status: 'none', caps: EMPTY, destinations: [], has: () => false })

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const key = user && user.platformRoles.length ? `${user.id}:${[...user.platformRoles].sort().join(',')}` : null
  const [loaded, setLoaded] = useState<{ key: string; data: MyCapabilities | null } | null>(null)
  useEffect(() => {
    if (!key) return
    let live = true
    api<MyCapabilities>('/v1/admin/me/capabilities')
      .then((data) => { if (live) setLoaded({ key, data }) })
      .catch(() => { if (live) setLoaded({ key, data: null }) })
    return () => { live = false }
  }, [key])
  const value = useMemo<CapabilityState>(() => {
    if (!key) return { status: 'none', caps: EMPTY, destinations: [], has: () => false }
    if (!loaded || loaded.key !== key) return { status: 'loading', caps: EMPTY, destinations: [], has: () => false }
    if (!loaded.data) return { status: 'error', caps: EMPTY, destinations: [], has: () => false }
    const caps = new Set(loaded.data.capabilities)
    return { status: 'ready', caps, destinations: loaded.data.destinations, has: (...wanted) => wanted.some((c) => caps.has(c)) }
  }, [key, loaded])
  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCapabilities(): CapabilityState {
  return useContext(CapabilityContext)
}

/** Staff page gate: renders nothing while capabilities load; without the capability (or on an error) -> Forbidden. */
export function RequireCapability({ cap, children }: { cap: string; children: ReactNode }) {
  const { status, has } = useCapabilities()
  if (status === 'loading') return null
  if (!has(cap)) return <Navigate to="/app/forbidden" replace />
  return <>{children}</>
}
