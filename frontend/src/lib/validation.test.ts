import { describe, expect, it, vi } from 'vitest'
import { collectionNameError, keepCollectionName, keepNeedText, needTextError, blockNonIntegerKey, codesError, integerError, keepCodes, keepDigits, keepRegistration, keepText, parseCodes, registrationError, textError, websiteError } from './validation'
import { ISO_3166 } from './countries'

describe('text rules', () => {
  it('person names', () => {
    expect(textError('person', "José O'Brien-Smith Jr.")).toBe('')
    expect(textError('person', 'Bob 2')).not.toBe('')
    expect(textError('person', '')).not.toBe('')
    expect(keepText('person', 'Bob 2@x')).toBe('Bob x')
  })
  it('org, role, city, language', () => {
    expect(textError('org', 'Smith & Sons (UK), Ltd.')).toBe('')
    expect(textError('org', 'Acme 2')).not.toBe('')
    expect(textError('org', 'A')).not.toBe('')
    expect(textError('org', '', false)).toBe('')
    expect(textError('role', 'VAT / Indirect Tax Specialist')).toBe('')
    expect(textError('role', 'CFO 2')).not.toBe('')
    expect(textError('city', 'Paris 75')).not.toBe('')
    expect(textError('language', 'Hindi-Urdu')).toBe('')
  })
  it('registration number', () => {
    expect(keepRegistration('sc 12#3456')).toBe('SC123456')
    expect(registrationError('SC123456')).toBe('')
    expect(registrationError('AB 12')).not.toBe('')
    expect(registrationError('abc')).not.toBe('')
  })
  it('website', () => {
    expect(websiteError('https://example.com')).toBe('')
    expect(websiteError('')).toBe('')
    for (const bad of ['javascript:alert(1)', 'example.com', 'https://localhost', 'https://a b.com', 'data:text/html,x']) expect(websiteError(bad)).not.toBe('')
  })
})

describe('collection and need text', () => {
  it('collection names', () => {
    expect(keepCollectionName("Tax & Audit-1 's#$")).toBe("Tax & Audit-1 's")
    expect(collectionNameError('123')).not.toBe('')
    expect(collectionNameError('  ')).not.toBe('')
    expect(collectionNameError('Q4 Audit')).toBe('')
  })
  it('need text', () => {
    expect(keepNeedText('tax, GST/VAT #1 @x')).toBe('tax, GST/VAT 1 x')
    expect(needTextError('123 -')).toBe('Describe what you need in words.')
    expect(needTextError('')).toBe('')
    expect(needTextError('tax 2')).toBe('')
  })
})

describe('policy and variant rules', () => {
  it('profile name has no digits', () => {
    expect(textError('policy', "Acme & Co. (UK), Ltd - Legal's")).toBe('')
    expect(textError('policy', 'Policy 2')).not.toBe('')
    expect(textError('policy', 'A/B')).not.toBe('')
    expect(keepText('policy', 'Pol1icy #2!')).toBe('Policy ')
  })
  it('variant name and governing law', () => {
    expect(textError('variant', "St. John's-Land")).toBe('')
    expect(textError('variant', 'UK & Ireland')).not.toBe('')
    expect(textError('variant', 'UK 1')).not.toBe('')
    expect(textError('law', 'England and Wales (English law), Rev. 1', false)).not.toBe('')
    expect(textError('law', "England and Wales (the Crown's law), c.", false)).toBe('')
    expect(textError('law', '', false)).toBe('')
    expect(keepText('law', 'Law 4 & x')).toBe('Law   x')
  })
  it('whole numbers only', () => {
    expect(keepDigits('1e5.2,-+3')).toBe('1523')
    const e = { key: 'e', preventDefault: vi.fn() }
    for (const key of ['e', 'E', '.', ',', '+', '-']) { const ev = { key, preventDefault: vi.fn() }; blockNonIntegerKey(ev); expect(ev.preventDefault).toHaveBeenCalled() }
    blockNonIntegerKey({ key: '5', preventDefault: e.preventDefault }); expect(e.preventDefault).not.toHaveBeenCalled()
    expect(integerError('12', 1, 90)).toBe('')
    expect(integerError('0', 1, 90)).not.toBe('')
    expect(integerError('91', 1, 90)).not.toBe('')
    expect(integerError('1.5', 1, 90)).not.toBe('')
    expect(integerError('', 1, 90)).toBe('')
  })
  it('currency and country codes', () => {
    expect(codesError('currency', 'usd, EUR, inr')).toBe('')
    expect(codesError('currency', 'USD, ABC')).toContain('ABC')
    expect(codesError('currency', 'US')).not.toBe('')
    expect(codesError('country', 'GB, ie, DE')).toBe('')
    expect(codesError('country', 'GB, ZZ, XX')).toContain('ZZ')
    expect(codesError('country', '', true)).not.toBe('')
    expect(codesError('country', '')).toBe('')
    expect(parseCodes('gb, GB, ie,')).toEqual(['GB', 'IE'])
    expect(keepCodes('gb1, i-e')).toBe('GB, IE')
    expect(ISO_3166.size).toBe(249)
  })
})
