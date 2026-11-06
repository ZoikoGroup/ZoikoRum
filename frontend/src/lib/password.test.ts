import { describe, expect, it } from 'vitest'
import { PASSWORD_LABEL, passwordScore } from './password'

describe('passwordScore', () => {
  it('rejects anything under 12 characters, however varied', () => {
    expect(passwordScore('Ab1!Ab1!Ab1')).toBe(0)
    expect(PASSWORD_LABEL[0]).toMatch(/at least 12/)
  })

  it('rates 12+ characters of one kind as fair', () => {
    expect(passwordScore('abcdefghijkl')).toBe(1)
  })

  it('rates variety or extra length as good', () => {
    expect(passwordScore('Abcdefghijk1')).toBe(2) // 3 kinds
    expect(passwordScore('abcdefghijklmnop')).toBe(2) // 16 chars, one kind
  })

  it('rates a long, varied passphrase as strong', () => {
    expect(passwordScore('correct horse battery')).toBe(3)
    expect(PASSWORD_LABEL[3]).toBe('Strong')
  })
})

import { passwordProblem } from './password'

describe('passwordProblem', () => {
  it('asks for the first thing that is missing', () => {
    expect(passwordProblem('Short1!')).toMatch(/12 characters/)
    expect(passwordProblem('alllowercase-and-long')).toMatch(/upper and lower/)
    expect(passwordProblem('No-Digits-Here-At-All')).toMatch(/number/)
    expect(passwordProblem('NoSymbolsHere1234')).toMatch(/symbol/)
  })
  it('accepts a password with all four', () => {
    expect(passwordProblem('Strong-Enough-Pass-1!')).toBe('')
  })
})
