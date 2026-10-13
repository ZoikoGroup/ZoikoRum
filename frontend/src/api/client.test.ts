import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('service errors', () => {
  it('preserves actionable backend error codes and support references', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 'DATABASE_SCHEMA_OUTDATED', detail: 'A database update is required.', correlationId: 'support-reference',
    }), { status: 503, headers: { 'Content-Type': 'application/problem+json' } })))
    await expect(api('/v1/threads', { auth: false })).rejects.toMatchObject({
      status: 503, code: 'DATABASE_SCHEMA_OUTDATED', message: 'A database update is required.', correlationId: 'support-reference',
    })
  })
  it('keeps gateway errors understandable when no backend response exists', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Bad Gateway', { status: 502 })))
    await expect(api('/v1/threads', { auth: false })).rejects.toMatchObject({ status: 502, code: 'SERVER_UNREACHABLE' })
  })
})
