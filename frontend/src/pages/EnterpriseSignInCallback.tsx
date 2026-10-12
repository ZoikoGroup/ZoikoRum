import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AuthResult } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert } from '../components/ui'

export default function EnterpriseSignInCallback() {
  const [params] = useSearchParams()
  const { accept } = useAuth()
  const navigate = useNavigate()
  const started = useRef(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    if (started.current) return
    started.current = true
    const isSaml = window.location.pathname === '/sso/saml-callback'
    const state = params.get('state'), code = params.get('code')
    const handoff = params.get('handoff')
    const browserToken = state ? sessionStorage.getItem(`zk-sso-${state}`) : null
    async function complete() {
      if (!state || (isSaml ? !handoff : !code) || !browserToken || params.has('error')) throw new Error('Enterprise sign-in was cancelled or does not belong to this browser')
      sessionStorage.removeItem(`zk-sso-${state}`)
      return api<AuthResult>(isSaml ? '/v1/auth/saml/complete' : '/v1/auth/enterprise/complete', { method: 'POST', auth: false, body: isSaml ? { state, handoff, browserToken } : { state, code, browserToken } })
    }
    complete()
      .then(result => {
        accept(result)
        const elevated = result.user.platformRoles.length > 0 || result.user.personas.some(p => p === 'ENTERPRISE_ADMIN' || p === 'FIRM_ADMIN')
        navigate(result.user.mfaRequired || elevated ? '/app/security' : `/app/${result.user.defaultDashboard}`, { replace: true, state: { verifySession: elevated && !result.user.mfaRequired } })
      })
      .catch(setError)
  }, [params, accept, navigate])
  return <AuthLayout><h1>Enterprise sign-in</h1><ErrorAlert error={error} />{!error && <p role="status">Verifying your organisation’s sign-in…</p>}</AuthLayout>
}
