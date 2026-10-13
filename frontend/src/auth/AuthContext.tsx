import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi, type AuthResult, type User } from '../api/auth'
import { refreshSession, tokens } from '../api/client'

interface AuthState {
  user: User | null
  loading: boolean
  /** Store tokens + user after login/register/role change. */
  accept: (result: AuthResult) => void
  reloadUser: () => Promise<User | null>
  logout: () => Promise<void>
  /** Re-authenticate with the authenticator code for sensitive actions (step-up MFA). */
  stepUp: (code: string) => Promise<void>
  /**
   * Re-issue the token so new roles appear (memberships are applied by the background
   * worker, usually within a second). Polls until `ready(user)` is true or ~8s pass.
   */
  refreshClaims: (ready?: (u: User) => boolean) => Promise<User | null>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const reloadUser = useCallback(async () => {
    try {
      const me = await authApi.me()
      setUser(me)
      return me
    } catch {
      setUser(null)
      return null
    }
  }, [])

  // Restore the session on page load from the stored refresh token.
  useEffect(() => {
    tokens.onSessionLost(() => setUser(null))
    ;(async () => {
      if (tokens.hasRefresh() && (await refreshSession())) await reloadUser()
      setLoading(false)
    })()
  }, [reloadUser])

  const accept = useCallback((result: AuthResult) => {
    tokens.set(result.tokens)
    setUser(result.user)
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      tokens.clear()
      setUser(null)
    }
  }, [])

  const stepUp = useCallback(async (code: string) => {
    tokens.set(await authApi.stepUp(code))
  }, [])

  const refreshClaims = useCallback(async (ready?: (u: User) => boolean) => {
    let me: User | null = null
    for (let i = 0; i < 16; i++) {
      if (await refreshSession()) me = await reloadUser()
      if (!ready) return me
      if (me && ready(me)) {
        await refreshSession() // token minted after the change is visible, so it carries the new roles
        return me
      }
      await new Promise((r) => setTimeout(r, 500))
    }
    return me
  }, [reloadUser])

  const value = useMemo(
    () => ({ user, loading, accept, reloadUser, logout, stepUp, refreshClaims }),
    [user, loading, accept, reloadUser, logout, stepUp, refreshClaims],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
