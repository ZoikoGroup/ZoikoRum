/** Password strength (Onboarding s.6): length matters most; variety helps. 0 = too short, 3 = strong. */
export function passwordScore(value: string): 0 | 1 | 2 | 3 {
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(value)).length
  if (value.length < 12) return 0
  if (value.length >= 16 && variety >= 2) return 3
  return variety >= 3 || value.length >= 16 ? 2 : 1
}

export const PASSWORD_LABEL = ['Too short (at least 12 characters)', 'Fair', 'Good', 'Strong'] as const

/** The sign-up and reset rule (the server checks the same): 12+ characters, upper and lower case, a number and a symbol.
    Returns the first thing missing, or '' when the password is fine. */
export function passwordProblem(value: string): string {
  if (value.length < 12) return 'Use at least 12 characters.'
  if (!(/[a-z]/.test(value) && /[A-Z]/.test(value))) return 'Use both upper and lower case letters.'
  if (!/\d/.test(value)) return 'Add a number.'
  if (!/[^A-Za-z0-9]/.test(value)) return 'Add a symbol, such as ! or -.'
  return ''
}
