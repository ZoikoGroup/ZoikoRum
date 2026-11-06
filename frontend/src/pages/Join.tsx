import { useState, type FormEvent } from 'react'
import { WELCOME_KEY } from '../lib/welcome'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { authApi, type AccountType } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AuthLayout, ErrorAlert, Field, PasswordInput } from '../components/ui'
import { Icon } from '../components/AuthIcons'
import { SocialSignUpOptions } from '../components/SingleSignOn'
import { ISO_CURRENCIES } from '../lib/currencies'
import { passwordProblem } from '../lib/password'
import { dashboardPath } from '../staffRoutes'
import { safeNextPath } from '../auth/guards'
import { growthApi } from '../api/professional'

const TYPES: { value: AccountType; title: string; desc: string; use: [string, string] }[] = [
  { value: 'BUYER', title: 'Buyer', desc: 'Hire and manage verified professionals for your business.',
    use: ['Hire professionals', 'Post requirements, compare verified professionals and run governed engagements.'] },
  { value: 'PROFESSIONAL', title: 'Professional', desc: 'Offer services as an independent, verified professional.',
    use: ['Offer services', 'Build a verified profile, receive requests and deliver under contract and escrow.'] },
  { value: 'FIRM', title: 'Firm', desc: 'List a firm and manage multiple professionals under one account.',
    use: ['Offer services as a firm', 'List your firm, manage your professionals and win engagements together.'] },
  { value: 'ENTERPRISE', title: 'Enterprise', desc: 'Procurement with policy profiles, approval chains and audit exports.',
    use: ['Govern professional services', 'Set policy, approval chains and audit exports across your organisation.'] },
]

export const COUNTRIES: [string, string][] = [
  ['US', 'United States'], ['GB', 'United Kingdom'], ['IN', 'India'], ['CA', 'Canada'], ['AU', 'Australia'],
  ['IE', 'Ireland'], ['DE', 'Germany'], ['FR', 'France'], ['NL', 'Netherlands'], ['SG', 'Singapore'],
  ['AE', 'United Arab Emirates'], ['ZA', 'South Africa'],
]

const COMPANY_TYPES = ['Private Limited', 'Public Limited', 'LLP', 'Partnership', 'Sole proprietorship', 'Non-profit', 'Government', 'Other']
const INDUSTRIES = ['Retail & e-commerce', 'Technology & software', 'Financial services', 'Healthcare & life sciences', 'Manufacturing',
  'Telecommunications', 'Energy & utilities', 'Education', 'Media & entertainment', 'Professional services', 'Other']
const SIZES = ['1–10 employees', '11–50 employees', '51–200 employees', '201–500 employees', '501–1,000 employees', '1,000+ employees']
const TIMEZONES = ['UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'Europe/London', 'Europe/Dublin',
  'Europe/Paris', 'Europe/Berlin', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Singapore', 'Australia/Sydney', 'Africa/Johannesburg']

const JOB_TITLES = ['Owner / Founder', 'CEO / Managing Director', 'CFO / Finance Director', 'COO / Operations Director', 'Head of Procurement',
  'Procurement Manager', 'Legal Counsel', 'Operations Manager', 'Project Manager', 'Consultant', 'Other']
const DIAL_CODES: [string, string][] = [['+1', 'US/CA'], ['+44', 'UK'], ['+91', 'IN'], ['+61', 'AU'], ['+353', 'IE'], ['+49', 'DE'], ['+33', 'FR'],
  ['+31', 'NL'], ['+65', 'SG'], ['+971', 'AE'], ['+27', 'ZA']]

/** The four segments and the checklist under the password fields: all four are required (the server checks them too). */
function PasswordChecklist({ value }: { value: string }) {
  const checks: [string, boolean][] = [['12+ characters', value.length >= 12], ['Upper & lower case', /[a-z]/.test(value) && /[A-Z]/.test(value)],
    ['A number', /\d/.test(value)], ['A symbol', /[^A-Za-z0-9]/.test(value)]]
  const met = checks.filter(([, ok]) => ok).length
  return (
    <div className="pw-check" aria-live="polite">
      <div className="pw-segs" aria-hidden>{checks.map(([k], i) => <span key={k} className={i < met ? 'on' : ''} />)}</div>
      <ul>{checks.map(([k, ok]) => <li key={k} className={ok ? 'ok' : ''}><span aria-hidden>{ok ? '●' : '○'}</span> {k}</li>)}</ul>
    </div>
  )
}

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
const REQUIRED_ORG = ['organizationName', 'companyType', 'industry', 'companySize', 'country', 'address'] as const
const LABEL: Record<string, string> = { organizationName: 'the organization name', companyType: 'a company type', industry: 'an industry',
  companySize: 'a company size', country: 'a country', address: 'the registered address', firstName: 'your first name', lastName: 'your last name', jobTitle: 'your job title', phone: 'your phone number' }

type Form = {
  organizationName: string; companyType: string; industry: string; companySize: string; country: string; state: string; city: string
  address: string; taxId: string; firstName: string; lastName: string; email: string; jobTitle: string; phoneCode: string; phone: string
  password: string; confirm: string
  timezone: string; currency: string; referralCode: string
}

/** One field's problem, or '' when it is fine: used on blur (as soon as someone leaves a field) and on Continue. */
function fieldError(k: string, v: string): string {
  switch (k) {
    case 'email': return /^\S+@\S+\.\S+$/.test(v) ? '' : 'Enter a valid email address.'
    case 'password': return passwordProblem(v)
    case 'phone': return /^[0-9][0-9 ()-]{5,18}$/.test(v.trim()) ? '' : 'Enter a valid phone number.'
    case 'referralCode': return !v.trim() || CODE.test(v.trim()) ? '' : 'Codes use letters, numbers and dashes (3–40 characters).'
    case 'timezone': case 'currency': return v ? '' : 'Choose one.'
    default: return LABEL[k] ? (v.trim() ? '' : `Enter ${LABEL[k]}.`) : ''
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
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [form, setForm] = useState<Form>({ organizationName: '', companyType: '', industry: '', companySize: '', country: '', state: '', city: '',
    address: '', taxId: '', firstName: '', lastName: '', email: '', jobTitle: '', phoneCode: '+1', phone: '', password: '', confirm: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
    currency: 'USD', referralCode: (params.get('ref') ?? params.get('code') ?? '').slice(0, 40) })
  const [showCode, setShowCode] = useState(!!(params.get('ref') ?? params.get('code')))
  const [terms, setTerms] = useState(false)
  const [marketing, setMarketing] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const needsOrg = type === 'FIRM' || type === 'ENTERPRISE' || type === 'BUYER'
  // A Buyer can be a person or a company; only Firm and Enterprise must name an organization.
  const orgRequired = type === 'FIRM' || type === 'ENTERPRISE'
  const current = TYPES.find((t) => t.value === type)!
  const orgLabel = type === 'FIRM' ? 'Firm legal name' : 'Organization name'

  const set = (k: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  const stepKeys = (s: 1 | 2 | 3): string[] => s === 1
    ? ['country', ...(orgRequired ? REQUIRED_ORG.filter((k) => k !== 'country') : [])]
    : s === 2 ? ['firstName', 'lastName', 'email', 'jobTitle', 'phone', 'password', 'referralCode'] : ['timezone', 'currency']
  function validateStep(s: 1 | 2 | 3): boolean {
    const errs: Record<string, string> = {}
    for (const k of stepKeys(s)) { const e = fieldError(k, form[k as keyof Form]); if (e) errs[k] = e }
    if (s === 2 && form.confirm !== form.password) errs.confirm = 'Passwords do not match.'
    if (s === 3 && !terms) errs.terms = 'Please accept the terms to continue.'
    setFieldErrors((prev) => ({ ...prev, ...errs }))
    return Object.keys(errs).length === 0
  }
  /** On blur: check the field just left (empty untouched fields are not flagged until Continue). */
  const blur = (k: keyof Form) => () => {
    if (!form[k] && k !== 'email') return
    setFieldErrors((prev) => ({ ...prev, [k]: fieldError(k, form[k]) }))
  }
  const go = (s: 1 | 2 | 3) => { setError(null); setStep(s) }
  const advance = () => { if (validateStep(step)) go((step + 1) as 2 | 3) }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (step < 3) { advance(); return }
    if (!validateStep(3)) return
    // Re-check the earlier steps so a value cleared after leaving them cannot slip through.
    if (!validateStep(1)) { go(1); return }
    if (!validateStep(2)) { go(2); return }
    setBusy(true)
    setError(null)
    try {
      const result = await authApi.register({
        email: form.email,
        password: form.password,
        displayName: `${form.firstName.trim()} ${form.lastName.trim()}`.trim(),
        country: form.country,
        accountType: type,
        organizationName: orgRequired ? form.organizationName.trim() : undefined,
        jobTitle: form.jobTitle || undefined,
        phone: `${form.phoneCode} ${form.phone.trim()}`,
        timezone: form.timezone || undefined,
        currency: form.currency || undefined,
        companyType: needsOrg ? form.companyType || undefined : undefined,
        industry: needsOrg ? form.industry || undefined : undefined,
        companySize: needsOrg ? form.companySize || undefined : undefined,
        state: form.state.trim() || undefined,
        city: form.city.trim() || undefined,
        registeredAddress: needsOrg ? form.address.trim() || undefined : undefined,
        taxId: needsOrg ? form.taxId.trim() || undefined : undefined,
        marketingOptIn: marketing,
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
      if (err instanceof ApiError && err.code === 'EMAIL_TAKEN') { setFieldErrors({ email: err.message }); go(2) }
      else setError(err)
    } finally {
      setBusy(false)
    }
  }

  const stepNames = [needsOrg ? 'Organization' : 'Location', 'Your details', 'Review & confirm']
  const countryName = COUNTRIES.find(([c]) => c === form.country)?.[1] ?? form.country
  const req = <span className="req" aria-hidden>*</span>
  const text = (k: keyof Form, label: string, icon: Parameters<typeof Icon>[0]['name'], opts: { placeholder?: string } = {}) => (
    <Field label={label} id={k} error={fieldErrors[k]}>
      <span className="with-icon"><span className="ico"><Icon name={icon} /></span>
        <input id={k} className="input" value={form[k]} onChange={set(k)} onBlur={blur(k)} placeholder={opts.placeholder}
          aria-invalid={!!fieldErrors[k]} /></span>
    </Field>
  )
  const select = (k: keyof Form, title: string, icon: Parameters<typeof Icon>[0]['name'], placeholder: string, options: [string, string][]) => (
    <Field label={title} id={k} error={fieldErrors[k]}>
      <span className="with-icon"><span className="ico"><Icon name={icon} /></span>
        <select id={k} className="input" value={form[k]} onChange={set(k)} onBlur={blur(k)} aria-invalid={!!fieldErrors[k]}>
          <option value="">{placeholder}</option>
          {options.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
        </select></span>
    </Field>
  )

  return (
    <AuthLayout>
      <div className="reg-head">
        <span className="badge-ico"><Icon name="building" size={30} /></span>
        <div>
          <h1>Create your Zoikorum account</h1>
          <p>Set up your account to start hiring, offering or governing professional services.</p>
        </div>
      </div>
      <ErrorAlert error={error} />
      {step === 1 && type === 'BUYER' && <SocialSignUpOptions />}
      <div className="field-title" style={{ fontWeight: 600, marginBottom: 8 }}>I’m joining as {req}</div>
      <div className="seg" role="radiogroup" aria-label="Account type">
        {TYPES.map((t) => (
          <button type="button" key={t.value} role="radio" aria-checked={type === t.value}
            onClick={() => { setType(t.value); setFieldErrors({}) }}>{t.title}</button>
        ))}
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>{current.desc}</p>

      <ol className="stepper" aria-label="Progress" style={{ listStyle: 'none', padding: 0 }}>
        {stepNames.map((n, i) => {
          const s = i + 1
          return (
            <li key={n} style={{ display: 'contents' }}>
              <span className={`item ${s === step ? 'on' : s < step ? 'done' : ''}`} aria-current={s === step ? 'step' : undefined}>
                <span className="dot">{s < step ? '✓' : s}</span>{n}
              </span>
              {i < 2 && <span className="line" aria-hidden />}
            </li>
          )
        })}
      </ol>

      <form onSubmit={submit} noValidate>
        {step === 1 && (
          <div className="reg-card">
            <div className="reg-card-head">
              <span className="badge-ico"><Icon name="building" /></span>
              <div><h3>{needsOrg ? 'Organization details' : 'Where you are based'}</h3>
                <p>{needsOrg ? 'Tell us about the company hiring or governing professional services.' : 'Tell us where you work from.'}</p></div>
            </div>
            {needsOrg && (
              <div className="grid-2">
                {text('organizationName', orgLabel + (orgRequired ? ' *' : ''), 'building', { placeholder: 'e.g. Zoiko Telecom' })}
                {select('companyType', 'Company type' + (orgRequired ? ' *' : ''), 'doc', 'Select company type', COMPANY_TYPES.map((c) => [c, c]))}
                {select('industry', 'Industry' + (orgRequired ? ' *' : ''), 'briefcase', 'Select industry', INDUSTRIES.map((c) => [c, c]))}
                {select('companySize', 'Company size' + (orgRequired ? ' *' : ''), 'users', 'Select company size', SIZES.map((c) => [c, c]))}
              </div>
            )}
            <div className="grid-2">
              {select('country', (needsOrg ? 'Country of incorporation' : 'Country of residence') + ' *', 'globe', 'Select a country', COUNTRIES)}
              {text('state', 'State / Province (optional)', 'pin', { placeholder: 'e.g. California' })}
              {needsOrg && text('address', 'Registered address' + (orgRequired ? ' *' : ' (optional)'), 'pin', { placeholder: 'e.g. 123 Main St, Suite 100' })}
              {text('city', 'City (optional)', 'building', { placeholder: 'e.g. Austin' })}
            </div>
            {needsOrg && <>
              {text('taxId', 'Tax / company registration number (optional)', 'doc', { placeholder: 'e.g. EIN, VAT, GSTIN, Company No.' })}
              <p className="small muted" style={{ marginTop: -6 }}>Used for invoicing and enterprise verification. You can add it later.</p>
            </>}
          </div>
        )}

        {step === 2 && (
          <div className="reg-card">
            <div className="reg-card-head">
              <span className="badge-ico"><Icon name="user" /></span>
              <div><h3>Your details</h3><p>This person becomes the account holder{type === 'ENTERPRISE' ? ' and Enterprise Admin' : ''}.</p></div>
            </div>
            <div className="grid-2">
              {text('firstName', 'First name *', 'user', { placeholder: 'e.g. Lennox' })}
              {text('lastName', 'Last name *', 'user', { placeholder: 'e.g. Green' })}
              <Field label="Work email *" id="email" error={fieldErrors.email}>
                <span className="with-icon"><span className="ico"><Icon name="mail" /></span>
                  <input id="email" className="input" type="email" autoComplete="email" value={form.email} onChange={set('email')}
                    onBlur={blur('email')} placeholder="name@company.com" aria-invalid={!!fieldErrors.email} /></span>
              </Field>
              {select('jobTitle', 'Job title *', 'briefcase', 'Select job title', JOB_TITLES.map((c) => [c, c]))}
            </div>
            <Field label="Phone number *" id="phone" error={fieldErrors.phone}>
              <div className="phone-row">
                <span className="with-icon"><span className="ico"><Icon name="globe" /></span>
                  <select aria-label="Country code" className="input" value={form.phoneCode} onChange={set('phoneCode')}>
                    {DIAL_CODES.map(([c, n]) => <option key={c + n} value={c}>{c} {n}</option>)}
                  </select></span>
                <span className="with-icon"><span className="ico"><Icon name="phone" /></span>
                  <input id="phone" className="input" type="tel" autoComplete="tel-national" value={form.phone} onChange={set('phone')}
                    onBlur={blur('phone')} placeholder="e.g. 212 555 0123" aria-invalid={!!fieldErrors.phone} /></span>
              </div>
            </Field>
            <div className="grid-2">
              <Field label="Password *" id="password" error={fieldErrors.password}>
                <span className="with-icon" onBlur={blur('password')}><span className="ico"><Icon name="lock" /></span>
                  <PasswordInput id="password" autoComplete="new-password" value={form.password}
                    onChange={(v) => setForm({ ...form, password: v })} invalid={!!fieldErrors.password} /></span>
              </Field>
              <Field label="Confirm password *" id="confirm" error={fieldErrors.confirm}>
                <span className="with-icon"><span className="ico"><Icon name="lock" /></span>
                  <PasswordInput id="confirm" autoComplete="new-password" value={form.confirm}
                    onChange={(v) => setForm({ ...form, confirm: v })} invalid={!!fieldErrors.confirm} /></span>
              </Field>
            </div>
            <PasswordChecklist value={form.password} />
            {showCode ? (
              <Field label="Referral or invite code (optional)" id="referralCode" error={fieldErrors.referralCode}
                hint="If someone referred you or gave you an invite code. It is stored with your account.">
                <input id="referralCode" className="input" autoComplete="off" maxLength={40} value={form.referralCode}
                  onChange={set('referralCode')} onBlur={blur('referralCode')} aria-invalid={!!fieldErrors.referralCode} />
              </Field>
            ) : (
              <button type="button" className="link-btn small" style={{ display: 'inline', padding: 0 }}
                onClick={() => setShowCode(true)}>Have a referral or invite code?</button>
            )}
          </div>
        )}

        {step === 3 && (<>
          <div className="reg-card">
            <div className="reg-card-head">
              <span className="badge-ico"><Icon name="clock" /></span>
              <div><h3>Setup preferences</h3><p>Tailor your account to how you’ll use Zoikorum.</p></div>
            </div>
            <div className="grid-2">
              <Field label="Timezone *" id="timezone" error={fieldErrors.timezone}>
                <span className="with-icon"><span className="ico"><Icon name="clock" /></span>
                  <select id="timezone" className="input" value={form.timezone} onChange={set('timezone')} aria-invalid={!!fieldErrors.timezone}>
                    <option value="">Select a timezone</option>
                    {[...new Set([form.timezone, ...TIMEZONES].filter(Boolean))].map((z) => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}
                  </select></span>
              </Field>
              <Field label="Preferred currency *" id="currency" error={fieldErrors.currency}>
                <span className="with-icon"><span className="ico"><Icon name="money" /></span>
                  <select id="currency" className="input" value={form.currency} onChange={set('currency')} aria-invalid={!!fieldErrors.currency}>
                    <option value="">Select a currency</option>
                    {ISO_CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select></span>
              </Field>
            </div>
            <div className="field-title" style={{ fontWeight: 600, margin: '4px 0 8px' }}>How you’ll use Zoikorum</div>
            <div className="choice"><span className="radio" aria-hidden /><div><strong>{current.use[0]}</strong><span>{current.use[1]}</span></div></div>
          </div>

          <div className="reg-card">
            <div className="reg-card-head">
              <span className="badge-ico"><Icon name="doc" /></span>
              <div><h3>Review &amp; confirm</h3><p>Check your details before creating the account.</p></div>
            </div>
            {[
              ['Account', current.title, 1],
              ...(needsOrg ? [
                ['Organization', [form.organizationName, form.companyType].filter(Boolean).join(' · ') || '—', 1],
                ['Industry', [form.industry, form.companySize].filter(Boolean).join(' · ') || '—', 1],
              ] : []),
              ['Location', [form.city, form.state, countryName].filter(Boolean).join(', '), 1],
              ['Account holder', `${form.firstName} ${form.lastName}`.trim() + (form.jobTitle ? ` · ${form.jobTitle}` : ''), 2],
              ['Contact', [form.email, `${form.phoneCode} ${form.phone}`.trim()].filter(Boolean).join(' · '), 2],
            ].map(([k, v, to]) => (
              <div className="review-row" key={k as string}>
                <span className="k">{k}</span><span className="v">{v}</span>
                <button type="button" className="link-btn small" onClick={() => go(to as 1 | 2)}>Edit</button>
              </div>
            ))}
            <label className="checkbox" style={{ marginTop: 14 }}>
              <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
              <span>I agree to the <Link to="/legal/terms" target="_blank">Terms of Service</Link> and acknowledge the{' '}
                <Link to="/legal/privacy" target="_blank">Privacy Policy</Link>. {req} I understand Zoikorum facilitates engagements
                but does not provide professional services.</span>
            </label>
            {fieldErrors.terms && <p className="small" style={{ color: 'var(--zk-danger)', marginTop: -10 }}>{fieldErrors.terms}</p>}
            <label className="checkbox" style={{ marginBottom: 0 }}>
              <input type="checkbox" checked={marketing} onChange={(e) => setMarketing(e.target.checked)} />
              <span>Send me product updates and tips (optional — unsubscribe anytime).</span>
            </label>
          </div>
        </>)}

        <div className="wizard-actions">
          {step > 1 && <button type="button" className="btn btn-secondary" onClick={() => go((step - 1) as 1 | 2)}>Back</button>}
          <button className="btn btn-primary btn-block" disabled={busy}>
            {step < 3 ? 'Continue' : busy ? 'Creating account…' : 'Create account & continue'} <Icon name="arrow" size={18} />
          </button>
        </div>
        <p className="reg-note"><Icon name="lock" size={16} /> Your information is encrypted and handled under our Privacy Policy. Progress is kept while you switch steps.</p>
      </form>
      <p className="auth-foot">Already have an account? <Link to={safeNext ? `/login?next=${encodeURIComponent(safeNext)}` : '/login'}>Log in</Link></p>
    </AuthLayout>
  )
}
