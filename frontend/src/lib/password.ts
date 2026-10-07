/** Password strength (Onboarding s.6): length matters most; variety helps. 0 = too short, 3 = strong. */
export function passwordScore(value: string): 0 | 1 | 2 | 3 {
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(value)).length
  if (value.length < 12) return 0
  if (value.length >= 16 && variety >= 2) return 3
  return variety >= 3 || value.length >= 16 ? 2 : 1
}

export const PASSWORD_LABEL = ['Too short (at least 12 characters)', 'Fair', 'Good', 'Strong'] as const
