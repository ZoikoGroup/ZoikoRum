import { useEffect, useState } from 'react'
import { authApi } from '../api/auth'
import { useAuth } from './AuthContext'

/** Can this person confirm a sensitive action (sign a contract, add a payout account)? An authenticator app or a passkey
    both count (the server accepts either for step-up); in development the codes may be switched off. */
export function useTwoStepReady(): boolean {
  const { user } = useAuth()
  const [hasPasskey, setHasPasskey] = useState(false)
  const needsLookup = !!user && !user.mfaEnabled && !user.mfaBypass
  useEffect(() => {
    if (!needsLookup) return
    let live = true
    authApi.passkeys().then((list) => { if (live) setHasPasskey(list.length > 0) }).catch(() => {})
    return () => { live = false }
  }, [needsLookup])
  return !!user && (user.mfaEnabled || !!user.mfaBypass || hasPasskey)
}
