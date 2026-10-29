import { describe, expect, it } from 'vitest'
import { keepRegistration, keepText, registrationError, textError, websiteError } from './validation'

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
