import { describe, expect, it } from 'vitest'
import { currencyError, isIsoCurrency, keepCurrency } from './currencies'

describe('currencies', () => {
  it('accepts ISO codes only', () => {
    expect(isIsoCurrency('USD')).toBe(true)
    expect(currencyError('INR')).toBe('')
    expect(currencyError('ABC')).not.toBe('')
    expect(currencyError('')).not.toBe('')
  })
  it('keeps letters, upper case, three characters', () => {
    expect(keepCurrency('u1s$dx')).toBe('USD')
  })
})
