import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useStepUp } from '../components/ui'
import { useAuth } from './AuthContext'

/* Staff capabilities (backend shared/capabilities.py): fetched once per staff sign-in from GET /v1/admin/me/capabilities
   and used for the staff sidebar, the staff route guards and row actions, instead of role lists. Default deny: while
   loading nothing staff-only shows, and on an error nothing does. The API checks every call itself. */

export interface StaffDestination { id: string; slug: string; route: string; title: string; group: string }
export interface MyCapabilities { capabilities: string[]; destinations: StaffDestination[] }
type Status = 'loading' | 'ready' | 'error' | 'step-up' | 'none'
interface CapabilityState { status: Status; caps: ReadonlySet<string>; destinations: StaffDestination[]; has: (...caps: string[]) => boolean
  reload: () => void }

const EMPTY: ReadonlySet<string> = new Set()
const none = () => false
const noop = () => {}
const CapabilityContext = createContext<CapabilityState>({ status: 'none', caps: EMPTY, destinations: [], has: none, reload: noop })

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const key = user && user.platformRoles.length ? `${user.id}:${[...user.platformRoles].sort().join(',')}` : null
  const [loaded, setLoaded] = useState<{ key: string; data: MyCapabilities | null; stepUp?: boolean } | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!key) return
    let live = true
    api<MyCapabilities>('/v1/admin/me/capabilities')
      .then((data) => { if (live) setLoaded({ key, data }) })
      // A session signed in before two-step was set up is not strong enough for staff work: ask for the code, don't fail.
      .catch((err) => { if (live) setLoaded({ key, data: null, stepUp: err instanceof ApiError && err.code === 'STEP_UP_REQUIRED' }) })
    return () => { live = false }
  }, [key, attempt])
  useEffect(() => {  // a step-up or a just-enabled two-step makes the session strong enough: load again
    const again = () => setAttempt((n) => n + 1)
    window.addEventListener('zk:session-upgraded', again)
    return () => window.removeEventListener('zk:session-upgraded', again)
  }, [])
  const value = useMemo<CapabilityState>(() => {
    const reload = () => setAttempt((n) => n + 1)
    if (!key) return { status: 'none', caps: EMPTY, destinations: [], has: none, reload }
    if (!loaded || loaded.key !== key) return { status: 'loading', caps: EMPTY, destinations: [], has: none, reload }
    if (!loaded.data) return { status: loaded.stepUp ? 'step-up' : 'error', caps: EMPTY, destinations: [], has: none, reload }
    const caps = new Set(loaded.data.capabilities)
    return { status: 'ready', caps, destinations: loaded.data.destinations, has: (...wanted) => wanted.some((c) => caps.has(c)), reload }
  }, [key, loaded])
  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCapabilities(): CapabilityState {
  return useContext(CapabilityContext)
}

/** Shown in the signed-in shell when a staff member's session needs their two-step code before the console opens. */
export function StaffSessionNotice() {
  const { status, reload } = useCapabilities()
  const [error, setError] = useState<string | null>(null)
  const { run, modal } = useStepUp((err) => setError(err instanceof Error ? err.message : 'Could not confirm the code.'))
  if (status !== 'step-up') return null
  return (
    <div className="alert alert-warn" role="status" style={{ margin: '0 0 12px' }}>
      Staff pages need a two-step session. Confirm with the 6-digit code from your authenticator to open the admin console.{' '}
      <button type="button" className="btn btn-primary btn-sm" onClick={() => { setError(null); run(async () => {
        await api('/v1/admin/me/capabilities')  // asks for the code (step-up) when the session is not strong enough
        reload()
      }) }}>Enter code</button>
      {error && <span className="small"> {error}</span>}
      {modal}
    </div>
  )
}

/** Staff page gate: renders nothing while capabilities load; without the capability (or on an error) -> Forbidden. */
export function RequireCapability({ cap, children }: { cap: string; children: ReactNode }) {
  const { status, has } = useCapabilities()
  if (status === 'loading' || status === 'step-up') return null
  if (!has(cap)) return <Navigate to="/app/forbidden" replace />
  return <>{children}</>
}
