import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { accountApi, deviceName, type DataRequest, type DeviceSession, type NotificationPreferences, type ProfileDetails } from '../../api/account'
import { authApi } from '../../api/auth'
import { useAuth } from '../../auth/AuthContext'
import { Icon } from '../../components/dashboard'
import { PortalHeader, SidePanel, Tabs } from '../../components/portal'
import { ErrorAlert, Field } from '../../components/ui'
import { countryName } from '../ProfessionalPages'

type Tab = 'account' | 'security' | 'notifications' | 'privacy' | 'payments' | 'platform' | 'linked'
const LANGUAGES: [string, string][] = [['en', 'English'], ['en-GB', 'English (UK)'], ['fr', 'Français'], ['de', 'Deutsch'], ['es', 'Español'], ['hi', 'हिन्दी']]
const TIME_ZONES = ['UTC', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles',
  'Asia/Kolkata', 'Asia/Singapore', 'Asia/Dubai', 'Australia/Sydney', 'Africa/Johannesburg']

/** Settings (management design 12): account, security, notifications, privacy and platform preferences — for every role. */
export default function SettingsPage() {
  const { reloadUser } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'account'
  const [me, setMe] = useState<ProfileDetails | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { accountApi.me().then(setMe).catch(setError) }, [])

  const saved = (p: ProfileDetails, msg: string) => { setMe(p); setNotice(msg); setError(null); reloadUser().catch(() => {}) }
  if (!me) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>

  return (
    <>
      <PortalHeader eyebrow="Account" title="Settings" subtitle="Manage your account, security, notifications and privacy." />
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <ErrorAlert error={error} />
      <Tabs<Tab> tabs={[{ key: 'account', label: 'Account' }, { key: 'security', label: 'Security' }, { key: 'notifications', label: 'Notifications' },
        { key: 'privacy', label: 'Privacy & data' }, { key: 'payments', label: 'Payment preferences' }, { key: 'platform', label: 'Platform preferences' },
        { key: 'linked', label: 'Linked accounts' }]} value={tab} onChange={(t) => { setNotice(null); setParams(t === 'account' ? {} : { tab: t }, { replace: true }) }} />

      <div className="home-grid wide">
        <div>
          {tab === 'account' && <AccountForm me={me} onSaved={(p) => saved(p, 'Account details saved.')} />}
          {tab === 'security' && <SecurityTab me={me} />}
          {tab === 'notifications' && <NotificationsTab onSaved={() => setNotice('Notification preferences saved.')} />}
          {tab === 'privacy' && <PrivacyTab onNotice={setNotice} />}
          {tab === 'payments' && (
            <section className="card panel"><div className="panel-head"><h2>Payment preferences</h2></div>
              <div className="empty-row" style={{ padding: 24 }}><strong>No payment methods yet.</strong> Payment methods are added when protected payments
                launch. Zoikorum never stores card details — only a token from the payment partner.</div></section>
          )}
          {tab === 'platform' && <PlatformTab me={me} onSaved={(p) => saved(p, 'Platform preferences saved.')} />}
          {tab === 'linked' && (
            <section className="card panel"><div className="panel-head"><h2>Linked accounts</h2></div>
              <div className="empty-row" style={{ padding: 24 }}><strong>No linked accounts.</strong> Single sign-on (SAML/OIDC) for enterprise
                organisations and passkeys are planned. You sign in with your email and password plus two-step verification.</div></section>
          )}
        </div>
        <aside>
          <SidePanel title="Your account">
            <dl className="facts">
              <dt>Email</dt><dd>{me.email}</dd>
              <dt>Country</dt><dd>{countryName(me.country)}</dd>
              <dt>Two-step verification</dt><dd>{me.mfaEnabled ? 'On' : 'Off'}</dd>
              <dt>Member since</dt><dd>{new Date(me.createdAt).toLocaleDateString()}</dd>
            </dl>
          </SidePanel>
          <SidePanel title="Roles">
            <p className="muted small" style={{ margin: 0 }}>Add another role (for example, offer your own services) on <Link to="/app/account">Profile &amp; roles</Link>.</p>
          </SidePanel>
        </aside>
      </div>
    </>
  )
}

function AccountForm({ me, onSaved }: { me: ProfileDetails; onSaved: (p: ProfileDetails) => void }) {
  const [f, setF] = useState({ displayName: me.displayName, phone: me.phone ?? '' })
  const [error, setError] = useState<unknown>(null)
  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try { onSaved(await accountApi.update({ displayName: f.displayName.trim(), ...(f.phone.trim() ? { phone: f.phone.trim() } : {}) })) } catch (err) { setError(err) }
  }
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Account details</h2></div>
      <form onSubmit={save}>
        <ErrorAlert error={error} />
        <Field label="Full name" id="s-name"><input id="s-name" className="input" value={f.displayName} onChange={(e) => setF({ ...f, displayName: e.target.value })} required /></Field>
        <Field label="Email" id="s-email" hint="Contact support to change the email you sign in with.">
          <input id="s-email" className="input" value={me.email} disabled /></Field>
        <Field label="Phone (optional)" id="s-phone" hint="International format, e.g. +44 20 7946 0958. Stored encrypted.">
          <input id="s-phone" className="input" type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="+44…" /></Field>
        <button className="btn btn-primary">Save changes</button>
      </form>
    </section>
  )
}

function SecurityTab({ me }: { me: ProfileDetails }) {
  const [sessions, setSessions] = useState<DeviceSession[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [resetSent, setResetSent] = useState(false)
  const load = useCallback(() => accountApi.sessions().then(setSessions).catch(setError), [])
  useEffect(() => { load() }, [load])
  return (
    <>
      <section className="card panel">
        <div className="panel-head"><h2>Sign-in &amp; two-step verification</h2></div>
        <ErrorAlert error={error} />
        <ul className="settings-list">
          <li><Icon name="lock" /><span><strong>Password</strong><br /><span className="muted small">We'll email you a secure link to set a new password.</span></span>
            {resetSent ? <span className="badge green">Link sent</span> : (
              <button className="btn btn-secondary btn-sm" onClick={() => authApi.forgotPassword(me.email).then(() => setResetSent(true)).catch(setError)}>Change password</button>)}</li>
          <li><Icon name="shield" /><span><strong>Two-step verification</strong><br /><span className="muted small">{me.mfaEnabled ? 'On — an authenticator app code is asked at sign-in.' : 'Off — protect your account with an authenticator app.'}</span></span>
            <Link className="btn btn-secondary btn-sm" to="/app/security">{me.mfaEnabled ? 'Manage' : 'Turn on'}</Link></li>
        </ul>
      </section>
      <section className="card panel">
        <div className="panel-head"><h2>Signed-in devices</h2></div>
        {!sessions ? <p className="muted">Loading…</p> : (
          <table className="data"><thead><tr><th>Device</th><th>Signed in</th><th>Strength</th><th /></tr></thead>
            <tbody>{sessions.map((s) => (
              <tr key={s.id}><td>{deviceName(s.device)} {s.current && <span className="badge green">This device</span>}</td>
                <td className="small">{new Date(s.signedInAt).toLocaleString()}</td>
                <td className="small">{({ MFA: 'Two-step', PASSKEY: 'Passkey', OAUTH: 'Single sign-on' } as Record<string, string>)[s.authStrength] ?? 'Password'}</td>
                <td>{!s.current && <button className="btn btn-ghost btn-sm" onClick={() => accountApi.signOutDevice(s.id).then(load).catch(setError)}>Sign out</button>}</td></tr>
            ))}</tbody></table>
        )}
      </section>
    </>
  )
}

function NotificationsTab({ onSaved }: { onSaved: () => void }) {
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => { accountApi.notifications().then(setPrefs).catch(setError) }, [])
  if (!prefs) return error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>
  const rows: [keyof NotificationPreferences, string, string][] = [
    ['email', 'Email', 'Proposals, approvals, deliverables and payment updates.'],
    ['inApp', 'In-app', 'Notifications in the bell menu.'],
    ['sms', 'SMS', 'Time-critical alerts only. Needs a phone number on your account.'],
    ['marketing', 'Product news', 'Occasional updates about new features.'],
  ]
  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try { const { email, inApp, sms, marketing } = prefs!; setPrefs(await accountApi.setNotifications({ email, inApp, sms, marketing })); onSaved() } catch (err) { setError(err) }
  }
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Notifications</h2></div>
      <form onSubmit={save}>
        <ErrorAlert error={error} />
        <ul className="settings-list">{rows.map(([k, label, desc]) => (
          <li key={k}><span><strong>{label}</strong><br /><span className="muted small">{desc}</span></span>
            <label className="switch"><input type="checkbox" checked={Boolean(prefs[k])} onChange={(e) => setPrefs({ ...prefs, [k]: e.target.checked })} /><span aria-hidden /></label></li>
        ))}</ul>
        {prefs.mandatoryNotice && <p className="muted small">{prefs.mandatoryNotice}</p>}
        <button className="btn btn-primary">Save preferences</button>
      </form>
    </section>
  )
}

function PrivacyTab({ onNotice }: { onNotice: (m: string) => void }) {
  const [requests, setRequests] = useState<DataRequest[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => accountApi.dataRequests().then(setRequests).catch(setError), [])
  useEffect(() => { load() }, [load])
  async function ask(type: 'ACCESS' | 'ERASURE') {
    if (type === 'ERASURE' && !confirm('Request deletion of your personal data? Records we must keep by law (contracts, payments, audit) are retained and anonymised where possible.')) return
    setError(null)
    try { await accountApi.requestData(type); await load(); onNotice(type === 'ACCESS' ? 'Data copy requested. We will email you when it is ready.' : 'Deletion requested. Our privacy team will contact you.') } catch (err) { setError(err) }
  }
  const open = (t: string) => requests?.some((r) => r.requestType === t && !r.completedAt)
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Privacy &amp; data</h2></div>
      <ErrorAlert error={error} />
      <ul className="settings-list">
        <li><Icon name="download" /><span><strong>Get a copy of your data</strong><br /><span className="muted small">Everything we hold about you, in a portable format.</span></span>
          <button className="btn btn-secondary btn-sm" disabled={open('ACCESS')} onClick={() => ask('ACCESS')}>{open('ACCESS') ? 'Requested' : 'Request copy'}</button></li>
        <li><Icon name="trash" /><span><strong>Delete your data</strong><br /><span className="muted small">Legally required records are kept; the rest is erased.</span></span>
          <button className="btn btn-danger btn-sm" disabled={open('ERASURE')} onClick={() => ask('ERASURE')}>{open('ERASURE') ? 'Requested' : 'Request deletion'}</button></li>
      </ul>
      {requests && requests.length > 0 && (
        <table className="data"><thead><tr><th>Request</th><th>Status</th><th>Requested</th></tr></thead>
          <tbody>{requests.map((r) => <tr key={r.id}><td>{r.requestType === 'ACCESS' ? 'Data copy' : 'Deletion'}</td>
            <td><span className="badge">{r.status.replace(/_/g, ' ').toLowerCase()}</span></td><td className="small">{new Date(r.createdAt).toLocaleDateString()}</td></tr>)}</tbody></table>
      )}
      <p className="muted small" style={{ marginBottom: 0 }}>See the <Link to="/legal/privacy">privacy notice</Link> for how we use your data.</p>
    </section>
  )
}

function PlatformTab({ me, onSaved }: { me: ProfileDetails; onSaved: (p: ProfileDetails) => void }) {
  const [f, setF] = useState({ language: me.language ?? 'en', timeZone: me.timeZone ?? '' })
  const [error, setError] = useState<unknown>(null)
  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try { onSaved(await accountApi.update({ language: f.language, ...(f.timeZone ? { timeZone: f.timeZone } : {}) })) } catch (err) { setError(err) }
  }
  return (
    <section className="card panel">
      <div className="panel-head"><h2>Platform preferences</h2></div>
      <form onSubmit={save}>
        <ErrorAlert error={error} />
        <div className="row">
          <Field label="Language" id="p-lang"><select id="p-lang" className="input" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}>
            {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <Field label="Time zone" id="p-tz"><select id="p-tz" className="input" value={f.timeZone} onChange={(e) => setF({ ...f, timeZone: e.target.value })}>
            <option value="">Use my browser's time zone</option>{TIME_ZONES.map((t) => <option key={t}>{t}</option>)}</select></Field>
        </div>
        <p className="muted small">The interface is in English for now; your language choice is used for emails as translations arrive. Amounts are shown in each engagement's contract currency.</p>
        <button className="btn btn-primary">Save preferences</button>
      </form>
    </section>
  )
}
