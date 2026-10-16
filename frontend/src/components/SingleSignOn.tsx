import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AuthResult } from '../api/auth'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, useStepUp } from './ui'

/* Single sign-on: an organisation's own identity provider (OpenID Connect: Okta, Entra ID, Google Workspace...), and
   Google or Microsoft sign-in where the platform offers them. */

async function go(body: { email?: string; provider?: string }) {
  const { url } = await api<{ url: string }>('/v1/auth/sso/start', { method: 'POST', body, auth: false })
  window.location.assign(url)
}

/** On the sign-in page: "Sign in with SSO" (by work email) and the Google / Microsoft buttons. */
export function SsoSignInOptions({ email }: { email: string }) {
  const [providers, setProviders] = useState<{ google: boolean; microsoft: boolean }>({ google: false, microsoft: false })
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { api<{ google: boolean; microsoft: boolean }>('/v1/auth/sso/providers', { auth: false }).then(setProviders).catch(() => {}) }, [])
  return (
    <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
      <ErrorAlert error={error} />
      <button type="button" className="btn btn-secondary btn-block" onClick={() => {
        if (!email.includes('@')) { setError(new Error('Enter your work email first, then choose Sign in with SSO.')); return }
        go({ email }).catch(setError)
      }}>Sign in with SSO</button>
      {providers.google && <button type="button" className="btn btn-secondary btn-block" onClick={() => go({ provider: 'google' }).catch(setError)}>Continue with Google</button>}
      {providers.microsoft && <button type="button" className="btn btn-secondary btn-block" onClick={() => go({ provider: 'microsoft' }).catch(setError)}>Continue with Microsoft</button>}
    </div>
  )
}

/** /sso/callback: the identity provider sends the browser back here with a code to exchange. */
export function SsoCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { accept } = useAuth()
  const [failed, setError] = useState<unknown>(null)
  const code = params.get('code'), state = params.get('state')
  const error = failed ?? (!code || !state ? new Error(params.get('error_description') || 'The sign-in was cancelled.') : null)
  const sent = useRef(false)
  useEffect(() => {
    if (sent.current || !code || !state) return
    sent.current = true
    api<AuthResult>('/v1/auth/sso/callback', { method: 'POST', body: { code, state }, auth: false })
      .then((r) => { accept(r); navigate(r.user.mfaRequired ? '/app/security' : `/app/${r.user.defaultDashboard}`, { replace: true }) })
      .catch(setError)
  }, [code, state, accept, navigate])
  return (
    <AuthLayout>
      <h1>Signing you in</h1>
      {!error && <p className="muted">Finishing single sign-on…</p>}
      <ErrorAlert error={error} />
      {!!error && <a className="btn btn-secondary btn-block" href="/login">Back to sign-in</a>}
    </AuthLayout>
  )
}

interface Connection { configured: boolean; issuer?: string; clientId?: string; emailDomains?: string[]; enforce?: boolean; justInTime?: boolean
  defaultRoles?: string[]; enabled?: boolean; scimEnabled?: boolean; redirectUri?: string; scimBaseUrl?: string }

/** Organisation Admins: connect the organisation's identity provider and turn on SCIM provisioning. */
export function SsoSettings({ orgId }: { orgId: string }) {
  const [c, setC] = useState<Connection | null>(null)
  const [f, setF] = useState({ issuer: '', clientId: '', clientSecret: '', domains: '', enforce: false, jit: true, enabled: true })
  const [scim, setScim] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const { run, modal } = useStepUp(setError)
  useEffect(() => {
    api<Connection>(`/v1/organizations/${orgId}/sso`).then((x) => {
      setC(x)
      if (x.configured) setF({ issuer: x.issuer ?? '', clientId: x.clientId ?? '', clientSecret: '', domains: (x.emailDomains ?? []).join(', '),
        enforce: !!x.enforce, jit: x.justInTime ?? true, enabled: x.enabled ?? true })
    }).catch(setError)
  }, [orgId])
  const save = () => run(async () => {
    setC(await api<Connection>(`/v1/organizations/${orgId}/sso`, { method: 'PUT', body: { issuer: f.issuer.trim(), clientId: f.clientId.trim(),
      clientSecret: f.clientSecret || null, emailDomains: f.domains.split(',').map((d) => d.trim()).filter(Boolean), enforce: f.enforce,
      justInTime: f.jit, enabled: f.enabled } }))
    setSaved(true); setF({ ...f, clientSecret: '' })
  })
  if (!c) return error ? <ErrorAlert error={error} /> : null
  return (
    <section className="card panel">
      {modal}
      <div className="panel-head"><h2>Single sign-on</h2><span className={`badge ${c.configured && c.enabled ? 'green' : ''}`}>{c.configured ? (c.enabled ? 'On' : 'Off') : 'Not set up'}</span></div>
      <p className="small muted">Connect your identity provider with OpenID Connect (Okta, Microsoft Entra ID, Google Workspace and others).
        Register Zoikorum as a web application there with the redirect address below.</p>
      <ErrorAlert error={error} />
      {saved && <div className="alert alert-success" role="status">Saved. People with these email domains can now sign in with SSO.</div>}
      {c.redirectUri && <p className="small">Redirect address: <code>{c.redirectUri}</code></p>}
      <label>Issuer address<input className="input" placeholder="https://your-company.okta.com" value={f.issuer} onChange={(e) => setF({ ...f, issuer: e.target.value })} /></label>
      <div className="row">
        <label style={{ flex: 1 }}>Client ID<input className="input" value={f.clientId} onChange={(e) => setF({ ...f, clientId: e.target.value })} /></label>
        <label style={{ flex: 1 }}>Client secret<input className="input" type="password" autoComplete="off" placeholder={c.configured ? 'Leave empty to keep the current one' : ''}
          value={f.clientSecret} onChange={(e) => setF({ ...f, clientSecret: e.target.value })} /></label>
      </div>
      <label>Email domains (comma-separated)<input className="input" placeholder="example.com" value={f.domains} onChange={(e) => setF({ ...f, domains: e.target.value })} /></label>
      <label className="checkbox small"><input type="checkbox" checked={f.jit} onChange={(e) => setF({ ...f, jit: e.target.checked })} />
        <span>Create an account at first sign-in for people the provider lets in (as Requester)</span></label>
      <label className="checkbox small"><input type="checkbox" checked={f.enforce} onChange={(e) => setF({ ...f, enforce: e.target.checked })} />
        <span>Require single sign-on: members with these domains cannot use a password</span></label>
      <label className="checkbox small"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /><span>Single sign-on on</span></label>
      <button className="btn btn-primary btn-sm" disabled={!f.issuer || !f.clientId || !f.domains || (!c.configured && !f.clientSecret)} onClick={save}>Save</button>

      {c.configured && <div style={{ marginTop: 16 }}>
        <h3>Automatic provisioning (SCIM 2.0)</h3>
        <p className="small muted">Your identity provider adds, updates and removes members. It never makes anyone an Organisation Admin.
          Base address: <code>{window.location.origin}/v1/scim/v2</code></p>
        {scim && <div className="alert alert-success" role="status"><strong>Copy this token now; it is not shown again:</strong>
          <div><code style={{ wordBreak: 'break-all' }}>{scim}</code></div></div>}
        <button className="btn btn-secondary btn-sm" onClick={() => run(async () => {
          setScim((await api<{ token: string }>(`/v1/organizations/${orgId}/sso/scim-token`, { method: 'POST' })).token)
        })}>{c.scimEnabled ? 'Replace SCIM token' : 'Create SCIM token'}</button>
      </div>}
    </section>
  )
}
