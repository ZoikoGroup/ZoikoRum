import { useState, type FormEvent } from 'react'
import { WELCOME_KEY } from '../lib/welcome'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi, type AccountType } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field, PasswordInput, PasswordStrength } from '../components/ui'
import { dashboardPath } from '../staffRoutes'
import { safeNextPath } from '../auth/guards'
import { growthApi } from '../api/professional'

const TYPES: { value: AccountType; title: string; desc: string }[] = [
  { value: 'BUYER', title: 'Buyer', desc: 'Find verified professionals and engage them under contract and escrow.' },
  { value: 'PROFESSIONAL', title: 'Professional', desc: 'Offer services as an independent, verified professional.' },
  { value: 'FIRM', title: 'Firm', desc: 'List a firm and manage multiple professionals under one account.' },
  { value: 'ENTERPRISE', title: 'Enterprise', desc: 'Procurement with policy profiles, approval chains and audit exports.' },
]

export const COUNTRIES: [string, string][] = [
  ['US', 'United States'], ['GB', 'United Kingdom'], ['IN', 'India'], ['CA', 'Canada'], ['AU', 'Australia'],
  ['IE', 'Ireland'], ['DE', 'Germany'], ['FR', 'France'], ['NL', 'Netherlands'], ['SG', 'Singapore'],
  ['AE', 'United Arab Emirates'], ['ZA', 'South Africa'],
]

function isAccountType(v: string | null): v is AccountType {
  return !!v && TYPES.some((t) => t.value === v)
}

/** The account type a destination needs: an invitation to a firm or the professional workspace means Professional;
    a request to a professional, an organisation invitation or anything else means Buyer. */
function typeFor(next: string): AccountType {
  if (next.startsWith('/invite')) return next.includes('kind=firm') ? 'PROFESSIONAL' : 'BUYER'
  return /^\/app\/professional(\/|\?|$)/.test(next) ? 'PROFESSIONAL' : 'BUYER'
}

const CODE = /^[A-Za-z0-9][A-Za-z0-9_-]{1,38}[A-Za-z0-9]$/

/** One field's problem, or '' when it is fine: used on blur (as soon as someone leaves a field) and on submit. */
function fieldError(k: string, v: string, type: AccountType): string {
  switch (k) {
    case 'displayName': return v.trim() ? '' : 'Enter your full name.'
    case 'email': return /^\S+@\S+\.\S+$/.test(v) ? '' : 'Enter a valid email address.'
    case 'password': return v.length >= 12 ? '' : 'Use at least 12 characters.'
    case 'organizationName': return v.trim() ? '' : `Enter your ${type === 'FIRM' ? 'firm' : 'organization'} name.`
    case 'referralCode': return !v.trim() || CODE.test(v.trim()) ? '' : 'Codes use letters, numbers and dashes (3–40 characters).'
    default: return ''
  }
}

export default function Join() {
  const [params] = useSearchParams()
  const next = params.get('next')
  // Same rule as sign-in: only same-site app, invitation and profile paths (no open redirects).
  const safeNext = safeNextPath(next)
  const initial = params.get('type') ?? (safeNext ? typeFor(safeNext) : null)
  const { accept } = useAuth()
  const navigate = useNavigate()

  const [type, setType] = useState<AccountType>(isAccountType(initial) ? initial : 'BUYER')
  const [form, setForm] = useState({ displayName: '', email: '', password: '', country: 'US', organizationName: '',
    referralCode: (params.get('ref') ?? params.get('code') ?? '').slice(0, 40) })
  const [showCode, setShowCode] = useState(!!(params.get('ref') ?? params.get('code')))
  const [terms, setTerms] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const needsOrg = type === 'FIRM' || type === 'ENTERPRISE'

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  type Key = 'displayName' | 'email' | 'password' | 'referralCode' | 'organizationName'
  const keys: Key[] = ['displayName', 'email', 'password', 'referralCode', ...(needsOrg ? ['organizationName' as const] : [])]
  function validate(): boolean {
    const errs: Record<string, string> = {}
    for (const k of keys) { const e = fieldError(k, form[k], type); if (e) errs[k] = e }
    if (!terms) errs.terms = 'Please accept the terms to continue.'
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }
  /** On blur: check the field just left (empty untouched fields are not flagged until submit). */
  const blur = (k: Key) => () => {
    if (!form[k] && k !== 'email') return
    setFieldErrors((prev) => ({ ...prev, [k]: fieldError(k, form[k], type) }))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!validate()) return
    setBusy(true)
    setError(null)
    try {
      const result = await authApi.register({
        email: form.email,
        password: form.password,
        displayName: form.displayName.trim(),
        country: form.country,
        accountType: type,
        organizationName: needsOrg ? form.organizationName.trim() : undefined,
        acceptTerms: true,
      })
      // Handed to the dashboard through this tab's session storage: signing in makes the guest-only guard redirect
      // at once, which would drop navigation state. The token is only returned in local development.
      try { sessionStorage.setItem(WELCOME_KEY, JSON.stringify({ confirmToken: result.emailConfirmationToken })) } catch { /* private mode */ }
      accept(result)
      // Optional referral or invite code: recorded against the new account. A failure never blocks signing up.
      if (form.referralCode.trim()) await growthApi.recordReferral(form.referralCode.trim()).catch(() => {})
      const dest = result.user.mfaRequired ? '/app/security' : safeNext ?? dashboardPath(result.user)
      navigate(dest, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'EMAIL_TAKEN') setFieldErrors({ email: err.message })
      else setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <h1>Create your Zoikorum account</h1>
      <p className="sub">Choose how you'll use Zoikorum. You can add the Buyer or Professional role later.</p>
      <ErrorAlert error={error} />
      <form onSubmit={submit} noValidate>
        <div className="type-grid" role="radiogroup" aria-label="Account type">
          {TYPES.map((t) => (
            <button type="button" key={t.value} role="radio" aria-checked={type === t.value}
              className="type-card" onClick={() => setType(t.value)}>
              <span className="t">{t.title}{type === t.value && <span aria-hidden>✓</span>}</span>
              <span className="d">{t.desc}</span>
            </button>
          ))}
        </div>

        {needsOrg && (
          <Field label={type === 'FIRM' ? 'Firm legal name' : 'Organization name'} id="org" error={fieldErrors.organizationName}
            hint={type === 'FIRM' ? 'As registered. Firm verification happens after sign-up.' : 'You will be the Enterprise Admin and can invite your team.'}>
            <input id="org" onBlur={blur('organizationName')} className="input" value={form.organizationName} onChange={set('organizationName')}
              aria-invalid={!!fieldErrors.organizationName} />
          </Field>
        )}
        <Field label="Full name" id="name" error={fieldErrors.displayName}>
          <input id="name" onBlur={blur('displayName')} className="input" autoComplete="name" value={form.displayName} onChange={set('displayName')}
            aria-invalid={!!fieldErrors.displayName} />
        </Field>
        <Field label="Work email" id="email" error={fieldErrors.email}>
          <input id="email" onBlur={blur('email')} className="input" type="email" autoComplete="email" value={form.email} onChange={set('email')}
            aria-invalid={!!fieldErrors.email} />
        </Field>
        <Field label="Password" id="password" error={fieldErrors.password} hint="At least 12 characters. A short phrase works well.">
          <span onBlur={blur('password')}><PasswordInput id="password" autoComplete="new-password" value={form.password}
            onChange={(v) => setForm({ ...form, password: v })} invalid={!!fieldErrors.password} /></span>
          <PasswordStrength value={form.password} />
        </Field>
        <Field label={needsOrg ? 'Country of incorporation' : 'Country of residence'} id="country">
          <select id="country" className="input" value={form.country} onChange={set('country')}>
            {COUNTRIES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </Field>
        {showCode ? (
          <Field label="Referral or invite code (optional)" id="ref" error={fieldErrors.referralCode}
            hint="If someone referred you or gave you an invite code. It is stored with your account.">
            <input id="ref" className="input" autoComplete="off" maxLength={40} value={form.referralCode}
              onChange={set('referralCode')} onBlur={blur('referralCode')} aria-invalid={!!fieldErrors.referralCode} />
          </Field>
        ) : (
          <button type="button" className="link-btn small" style={{ display: 'inline', padding: 0, marginBottom: 12 }}
            onClick={() => setShowCode(true)}>Have a referral or invite code?</button>
        )}
        <label className="checkbox">
          <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
          <span>
            I agree to the <Link to="/legal/terms" target="_blank">Terms</Link> and{' '}
            <Link to="/legal/privacy" target="_blank">Privacy Policy</Link>. I understand Zoikorum
            facilitates engagements but does not provide professional services.
          </span>
        </label>
        {fieldErrors.terms && <p className="small" style={{ color: 'var(--zk-danger)', marginTop: -10 }}>{fieldErrors.terms}</p>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Creating account…' : 'Create account'}</button>
      </form>
      <p className="auth-foot">Already have an account? <Link to={safeNext ? `/login?next=${encodeURIComponent(safeNext)}` : '/login'}>Sign in</Link></p>
    </AuthLayout>
  )
}
