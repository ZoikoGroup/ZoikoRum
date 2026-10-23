import { describe, expect, it } from 'vitest'
import { cropRect, nextTier, readability, specDescription } from './onboarding'
import { safeNextPath } from '../auth/guards'

describe('photo crop', () => {
  it('keeps the largest centred square at zoom 1', () => {
    expect(cropRect(400, 200, 1, 50, 50)).toEqual({ sx: 100, sy: 0, side: 200 })
  })
  it('zooming narrows the square and the position moves it within bounds', () => {
    expect(cropRect(400, 400, 2, 0, 100)).toEqual({ sx: 0, sy: 200, side: 200 })
    expect(cropRect(400, 400, 2, 150, -20)).toEqual({ sx: 200, sy: 0, side: 200 })
  })
})

describe('bio readability', () => {
  it('rates short plain sentences as easy', () => {
    const r = readability('I run month-end close for SaaS companies. I build cash forecasts. Founders get board packs on time.')
    expect(r.level).toBe('easy')
    expect(r.sentences).toBe(3)
  })
  it('flags one very long sentence as hard to scan', () => {
    const r = readability(Array.from({ length: 40 }, () => 'finance').join(' '))
    expect(r.level).toBe('hard')
    expect(r.message).toMatch(/split/)
  })
  it('says nothing for an empty bio', () => {
    expect(readability('  ').level).toBe('empty')
  })
})

describe('specialization preview and tiers', () => {
  it('describes regulated and credential-led specializations', () => {
    const text = specDescription({ name: 'Statutory Audit', regulated: true, requiresCredential: true }, 'Audit & Assurance', 'Finance & Accounting')
    expect(text).toMatch(/Tier A/)
    expect(text).toMatch(/credential/)
  })
  it('points to the next tier', () => {
    expect(nextTier('C', {})?.tier).toBe('B')
    expect(nextTier('B', { identity: 'VERIFIED' })?.tier).toBe('A')
    expect(nextTier('A', {})).toBeNull()
  })
})

describe('post-login destination (next)', () => {
  it('keeps same-site app and profile paths with their query and hash', () => {
    expect(safeNextPath('/app/requests/new?pro=123&offering=9')).toBe('/app/requests/new?pro=123&offering=9')
    expect(safeNextPath('/professionals/abc#offering-1')).toBe('/professionals/abc#offering-1')
    expect(safeNextPath('/invite?token=x&kind=firm')).toBe('/invite?token=x&kind=firm')
  })
  it('refuses other origins and odd paths (no open redirect)', () => {
    for (const bad of ['//evil.example', 'https://evil.example/app', '/\\evil.example', '/app\\..', 'javascript:alert(1)',
      '/login', '/app evil', '', null, undefined]) {
      expect(safeNextPath(bad as string | null | undefined)).toBeNull()
    }
  })
})
