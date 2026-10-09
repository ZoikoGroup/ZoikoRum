import { expect, request, type APIRequestContext } from '@playwright/test'

/* Test data through the API (the same calls the app makes), so each browser test starts from a known state.
   The stack runs with dev settings: no two-step codes, simulated identity partner, test payment provider. */

export const API_URL = 'http://127.0.0.1:8100'
export const PASSWORD = 'browser-test-password-1'
const PHOTO_PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(64, 0x30)]).toString('base64')

export interface Account { email: string; name: string; token: string; confirmToken: string | null; api: APIRequestContext }

const unique = (name: string) => `${name.toLowerCase().replace(/\W+/g, '-')}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@example.com`
const day = (n: number) => new Date(Date.now() + n * 86400_000).toISOString().slice(0, 10)

export async function call(a: Account, method: string, url: string, data?: unknown, idempotent = false) {
  const r = await a.api.fetch(url, {
    method, data: data as never,
    headers: { Authorization: `Bearer ${a.token}`, ...(idempotent ? { 'Idempotency-Key': crypto.randomUUID() } : {}) },
  })
  expect(r.status(), `${method} ${url}: ${await r.text()}`).toBeLessThan(300)
  return r.status() === 204 ? null : r.json()
}

export async function signUp(name: string, accountType: 'BUYER' | 'PROFESSIONAL', country = 'GB'): Promise<Account> {
  const api = await request.newContext({ baseURL: API_URL })
  const email = unique(name)
  const r = await api.post('/v1/auth/register', {
    data: { email, password: PASSWORD, displayName: name, country, accountType, acceptTerms: true },
  })
  expect(r.status(), await r.text()).toBe(201)
  const body = await r.json()
  return { email, name, token: body.tokens.accessToken, confirmToken: body.emailConfirmationToken, api }
}

async function refresh(a: Account) {
  const r = await a.api.post('/v1/auth/login', { data: { email: a.email, password: PASSWORD } })
  a.token = (await r.json()).tokens.accessToken
}

/** Waits for the worker: retries `check` until it returns a value. */
export async function eventually<T>(check: () => Promise<T | null | undefined | false>, what: string, ms = 20_000): Promise<T> {
  const end = Date.now() + ms
  for (;;) {
    const value = await check()
    if (value) return value
    if (Date.now() > end) throw new Error(`Timed out waiting for ${what}`)
    await new Promise((r) => setTimeout(r, 250))
  }
}

/** A published professional with a verified identity (Tier B), ready to answer requests. */
export async function verifiedProfessional(name: string) {
  const a = await signUp(name, 'PROFESSIONAL', 'IN')
  const pro = await call(a, 'POST', '/v1/professionals', {})
  await a.api.post('/v1/auth/confirm-email', { data: { token: a.confirmToken } })
  await call(a, 'PUT', '/v1/professionals/me/photo', { contentType: 'image/png', dataBase64: PHOTO_PNG })
  await call(a, 'PATCH', '/v1/professionals/me', {
    headline: 'AI/ML engineer for startups', engagementTypes: ['PROJECT'], deliveryModes: ['REMOTE'], pricingModels: ['FIXED'],
    yearsExperienceBand: '3-5', legalName: `${name} Example`,
    bio: 'I build machine-learning features for startups: data pipelines, model training and evaluation, and the APIs that serve them in production.',
  })
  await call(a, 'PUT', '/v1/professionals/me/specializations', { primary: 'ai-machine-learning-engineering', secondary: [] })
  await call(a, 'PUT', '/v1/professionals/me/jurisdictions', { served: ['IN', 'GB', 'US'], licensed: [], crossBorderAcknowledged: true })
  await call(a, 'POST', '/v1/professionals/me/publish', { attestAccurate: true })
  // Identity through the (simulated) identity partner: start the hosted check and give the partner's answer.
  const kase = await call(a, 'POST', '/v1/verification/cases', { verificationType: 'IDENTITY', subjectType: 'PROFESSIONAL', subjectId: pro.id })
  await call(a, 'POST', `/v1/verification/cases/${kase.id}/hosted-session`)
  await call(a, 'POST', `/v1/verification/cases/${kase.id}/hosted-simulate`, { status: 'approved' })
  await eventually(async () => {
    const trust = await a.api.get(`/v1/trust/professionals/${pro.id}`, { headers: { Authorization: `Bearer ${a.token}` } })
    return trust.ok() && (await trust.json()).tier === 'B'
  }, 'Tier B')
  return { account: a, pro }
}

/** A buyer with their organisation (created by the worker after sign-up). */
export async function buyerWithOrganisation(name: string) {
  const a = await signUp(name, 'BUYER')
  const org = await eventually(async () => {
    await refresh(a)
    const r = await a.api.get('/v1/organizations/mine', { headers: { Authorization: `Bearer ${a.token}` } })
    const orgs = r.ok() ? await r.json() : []
    return orgs[0]
  }, 'the buyer organisation')
  return { account: a, org }
}

/** Request -> proposal -> accepted -> contract signed by both -> first milestone funded -> work submitted. */
export async function engagementAwaitingAcceptance(buyer: Account, org: { id: string }, pro: Account, proId: string) {
  const [req] = await call(buyer, 'POST', '/v1/proposal-requests', {
    organizationId: org.id, professionalIds: [proId], service: 'Churn prediction model', engagementType: 'PROJECT',
    objective: 'Predict customer churn from product usage', details: 'Two years of usage events in Postgres.',
    desiredStartDate: day(10), estimatedDuration: 'THREE_SIX_WEEKS', budget: { maxMinor: 2_000_000, currency: 'USD' }, acknowledged: true,
  }, true)
  const proposal = await call(pro, 'POST', `/v1/proposal-requests/${req.id}/proposals`, {
    summary: 'I will build and validate a churn model and ship it as an API.', scopeAlignment: 'CONFIRMED',
    deliverables: [{ key: 'model', title: 'Trained model', acceptanceCriteria: 'AUC above 0.80 on the hold-out set' },
      { key: 'api', title: 'Scoring API', acceptanceCriteria: 'Documented endpoint returning a churn score' }],
    milestones: [{ title: 'Model', amountMinor: 1_000_000, deliverableKeys: ['model'] }, { title: 'API', amountMinor: 500_000, deliverableKeys: ['api'] }],
    pricingModel: 'FIXED', currency: 'USD', startDate: day(10), endDate: day(40), validUntil: day(14),
    assumptions: ['Read access to the usage database'], exclusions: ['Front-end work'],
  })
  await call(pro, 'POST', `/v1/proposals/${proposal.id}/submit`, undefined, true)
  await call(buyer, 'POST', `/v1/proposals/${proposal.id}/accept`, undefined, true)
  const contract = await eventually(async () => {
    const r = await call(buyer, 'GET', '/v1/contracts?role=buyer')
    return r.items.find((c: { proposalId: string }) => c.proposalId === proposal.id)
  }, 'the contract')
  await call(buyer, 'POST', `/v1/contracts/${contract.id}/sign`, { termsHash: contract.termsHash }, true)
  await call(pro, 'POST', `/v1/contracts/${contract.id}/sign`, { termsHash: contract.termsHash }, true)
  const escrow = await eventually(async () => (await buyer.api.get(`/v1/escrow/by-contract/${contract.id}`, {
    headers: { Authorization: `Bearer ${buyer.token}` } })).ok() && call(buyer, 'GET', `/v1/escrow/by-contract/${contract.id}`), 'escrow')
  const first = contract.milestones[0]
  await call(buyer, 'POST', `/v1/escrow/${escrow.id}/fund`, { milestoneIds: [first.id], paymentMethodToken: 'tok_visa' }, true)
  await eventually(async () => {
    const c = await call(pro, 'GET', `/v1/contracts/${contract.id}`)
    return c.milestones[0].status === 'IN_PROGRESS'
  }, 'the funded milestone')
  await call(pro, 'POST', `/v1/milestones/${first.id}/submit`, { note: 'Model trained; AUC 0.84 on hold-out.' })
  return { contract, milestone: first }
}
