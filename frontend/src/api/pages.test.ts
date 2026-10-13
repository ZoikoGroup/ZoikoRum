import { afterEach, describe, expect, it, vi } from 'vitest'
import { allPages } from './client'

afterEach(() => vi.unstubAllGlobals())
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

describe('paged lists', () => {
  it('follows nextCursor until the last page, keeping the order', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json({ items: [1, 2], nextCursor: 'next+page' }))
      .mockResolvedValueOnce(json({ items: [3], nextCursor: null }))
    vi.stubGlobal('fetch', fetch)
    expect(await allPages<number>('/v1/payments/invoices', { organizationId: 'org-1' })).toEqual([1, 2, 3])
    expect(fetch).toHaveBeenCalledTimes(2)
    const second = String(fetch.mock.calls[1][0])
    expect(second).toContain('organizationId=org-1')
    expect(second).toContain('limit=100')
    expect(second).toContain('cursor=next%2Bpage')
  })
  it('stops at the page limit', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => json({ items: [1], nextCursor: 'more' })))
    expect(await allPages<number>('/v1/disputes', {}, 3)).toEqual([1, 1, 1])
  })
})
