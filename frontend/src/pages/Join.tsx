import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi, type AccountType } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field, PasswordInput } from '../components/ui'

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

export default function Join() {
  const [params] = useSearchParams()
  const next = params.get('next')
  const safeNext = next && /^\/invite(\?|$)/.test(next) ? next : null
  // Invited to a firm -> you'll work as a Professional; to an organization -> as a Buyer.
  const initial = params.get('type') ?? (safeNext ? (safeNext.includes('kind=firm') ? 'PROFESSIONAL' : 'BUYER') : null)
  const { accept } = useAuth()
  const navigate = useNavigate()

  const [type, setType] = useState<AccountType>(isAccountType(initial) ? initial : 'BUYER')
  const [form, setForm] = useState({ displayName: '', email: '', password: '', country: 'US', organizationName: '' })
  const [terms, setTerms] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const needsOrg = type === 'FIRM' || type === 'ENTERPRISE'

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  function validate(): boolean {
    const errs: Record<string, string> = {}
    if (!form.displayName.trim()) errs.displayName = 'Enter your full name.'
    if (!/^\S+@\S+\.\S+$/.test(form.email)) errs.email = 'Enter a valid email address.'
    if (form.password.length < 12) errs.password = 'Use at least 12 characters.'
    if (needsOrg && !form.organizationName.trim()) errs.organizationName = `Enter your ${type === 'FIRM' ? 'firm' : 'organization'} name.`
    if (!terms) errs.terms = 'Please accept the terms to continue.'
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
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
      accept(result)
      // Dev only: the backend returns the email-confirmation token until an email provider is connected.
      const dest = result.user.mfaRequired ? '/app/security' : safeNext ?? `/app/${result.user.defaultDashboard}`
      navigate(dest, { replace: true, state: { welcome: true, confirmToken: result.emailConfirmationToken } })
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
            <input id="org" className="input" value={form.organizationName} onChange={set('organizationName')}
              aria-invalid={!!fieldErrors.organizationName} />
          </Field>
        )}
        <Field label="Full name" id="name" error={fieldErrors.displayName}>
          <input id="name" className="input" autoComplete="name" value={form.displayName} onChange={set('displayName')}
            aria-invalid={!!fieldErrors.displayName} />
        </Field>
        <Field label="Work email" id="email" error={fieldErrors.email}>
          <input id="email" className="input" type="email" autoComplete="email" value={form.email} onChange={set('email')}
            aria-invalid={!!fieldErrors.email} />
        </Field>
        <Field label="Password" id="password" error={fieldErrors.password} hint="At least 12 characters. A short phrase works well.">
          <PasswordInput id="password" autoComplete="new-password" value={form.password}
            onChange={(v) => setForm({ ...form, password: v })} invalid={!!fieldErrors.password} />
        </Field>
        <Field label={needsOrg ? 'Country of incorporation' : 'Country of residence'} id="country">
          <select id="country" className="input" value={form.country} onChange={set('country')}>
            {COUNTRIES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </Field>
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
