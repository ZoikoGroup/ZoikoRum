import { afterEach, describe, expect, it, vi } from 'vitest'
import { verifyAuditChain } from './audit'
import { dashboardApi, moneyOf } from './dashboards'
import { firmApi } from './orgs'
import { taxonomyApi } from './professional'

afterEach(() => vi.unstubAllGlobals())

function stubFetch(body: unknown = {}) {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  return (i: number) => ({ url: String(fetch.mock.calls[i][0]), method: fetch.mock.calls[i][1]?.method ?? 'GET',
    body: fetch.mock.calls[i][1]?.body ? JSON.parse(fetch.mock.calls[i][1].body) : undefined })
}

describe('taxonomy administration', () => {
  it('creates, edits only what changed, retires and loads the default list', async () => {
    const call = stubFetch()
    await taxonomyApi.createSpecialization({ groupSlug: 'tax', name: 'VAT advisory', requiresCredential: true, regulated: false, requiresInsurance: false })
    await taxonomyApi.updateSpecialization('vat-advisory', { regulated: true })
    await taxonomyApi.retireSpecialization('vat-advisory')
    await taxonomyApi.seedDefaults()
    expect(call(0)).toMatchObject({ method: 'POST', body: { groupSlug: 'tax', name: 'VAT advisory', requiresCredential: true } })
    expect(call(0).url).toContain('/v1/admin/taxonomy/specializations')
    expect(call(1)).toMatchObject({ method: 'PATCH', body: { regulated: true } })
    expect(call(1).url).toContain('/v1/admin/taxonomy/specializations/vat-advisory')
    expect(call(2).url).toContain('/v1/admin/taxonomy/specializations/vat-advisory/deprecate')
    expect(call(2).method).toBe('POST')
    expect(call(3)).toMatchObject({ method: 'POST' })
    expect(call(3).url).toContain('/v1/admin/taxonomy/seed')
  })
})

describe('audit ledger', () => {
  it('verifies the hash chain with a POST', async () => {
    const call = stubFetch({ valid: true, checked: 3, headHash: 'abc' })
    expect(await verifyAuditChain()).toEqual({ valid: true, checked: 3, headHash: 'abc' })
    expect(call(0)).toMatchObject({ method: 'POST' })
    expect(call(0).url).toContain('/v1/audit/chain/verify')
  })
})

describe('dashboard summaries', () => {
  it('asks for the buyer summary of one organisation and the professional summary of the caller', async () => {
    const call = stubFetch({ lastEventAt: null })
    await dashboardApi.buyer('org-1')
    await dashboardApi.professional()
    expect(call(0).url).toContain('/v1/dashboards/buyer?organizationId=org-1')
    expect(call(1).url).toContain('/v1/dashboards/professional')
  })
  it('turns per-currency minor amounts into money, leaving out empty balances', () => {
    expect(moneyOf({ USD: 12000, EUR: 0, GBP: 500 })).toEqual([{ currency: 'USD', amountMinor: 12000 }, { currency: 'GBP', amountMinor: 500 }])
    expect(moneyOf(undefined)).toEqual([])
  })
})

describe('firm pages', () => {
  it('reads the overview for admins and the public page without signing in', async () => {
    const call = stubFetch({})
    await firmApi.overview('firm-1')
    await firmApi.publicFirm('firm-1')
    expect(call(0).url).toContain('/v1/firms/firm-1/overview')
    expect(call(1).url).toContain('/v1/firms/firm-1/public')
  })
})
