import { afterEach, describe, expect, it, vi } from 'vitest'
import { notificationApi } from './notifications'

afterEach(() => vi.unstubAllGlobals())
describe('notification transport', () => {
  it('encodes pagination cursors and uses the recipient-scoped read endpoint', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ items: [], nextCursor: null }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    await notificationApi.inbox('opaque+/=')
    expect(String(fetch.mock.calls[0][0])).toContain('cursor=opaque%2B%2F%3D')
    await notificationApi.read('notification-123')
    expect(String(fetch.mock.calls[1][0])).toContain('/v1/notifications/notification-123/read')
    expect(fetch.mock.calls[1][1].method).toBe('POST')
  })
  it('sends explicit webhook subscriptions without forwarding a signing secret', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 201, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    await notificationApi.createEndpoint('org-1', 'https://public.example/events', ['event.v1'])
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ organizationId: 'org-1', url: 'https://public.example/events', eventTypes: ['event.v1'] })
  })
})
