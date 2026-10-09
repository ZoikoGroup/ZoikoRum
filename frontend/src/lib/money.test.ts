import { describe, expect, it } from 'vitest'
import { formatCurrencies, sumByCurrency } from './money'

describe('currency summaries', () => {
  it('keeps unlike currencies separate and adds integer minor units', () => {
    expect(sumByCurrency([{ currency: 'USD', amountMinor: 100 }, { currency: 'EUR', amountMinor: 500 },
      { currency: 'USD', amountMinor: 250 }])).toEqual([{ currency: 'EUR', amountMinor: 500 }, { currency: 'USD', amountMinor: 350 }])
  })
  it('labels each currency and handles an empty summary', () => {
    const text = formatCurrencies([{ currency: 'USD', amountMinor: 100 }, { currency: 'EUR', amountMinor: 500 }])
    expect(text).toContain('USD'); expect(text).toContain('EUR'); expect(text).toContain(' · ')
    expect(formatCurrencies([])).toBe('—')
  })
})
