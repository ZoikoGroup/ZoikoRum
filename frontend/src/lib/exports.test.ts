import { describe, expect, it } from 'vitest'
import { csv } from './exports'

describe('csv', () => {
  it('joins plain values with commas and rows with newlines', () => {
    expect(csv([['Type', 'Amount'], ['Payment', 100]])).toBe('Type,Amount\nPayment,100')
  })

  it('quotes values containing commas, quotes or newlines', () => {
    expect(csv([['M1, master file', 'He said "done"', 'line1\nline2']])).toBe('"M1, master file","He said ""done""","line1\nline2"')
  })

  it('writes empty cells for null and undefined', () => {
    expect(csv([['a', null, undefined, 0]])).toBe('a,,,0')
  })
})
