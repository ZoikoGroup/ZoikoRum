// Text rules for names and similar free text. Mirrors backend/src/zoikorum/shared/validation.py: keep the two in step.
// Unicode-friendly (letters and their combining marks by property, not an ASCII range). Errors show on blur or submit,
// never while typing; `keep*` helpers drop characters that can never be valid so they cannot be typed or pasted in.

import { ISO_3166 } from './countries'
import { ISO_4217 } from './currencies'

const L = String.raw`\p{L}\p{M}`
const kinds = {
  person: { allowed: `${L} '’.-`, label: 'letters, spaces, apostrophes, hyphens and periods', min: 1, max: 200 },
  org: { allowed: `${L} '’.,&()-`, label: "letters, spaces and . , & ' - ( )", min: 2, max: 200 },
  role: { allowed: `${L} '’.,&/()-`, label: "letters, spaces and & / , ' - . ( )", min: 1, max: 120 },
  city: { allowed: `${L} '’.-`, label: 'letters, spaces, apostrophes, hyphens and periods', min: 1, max: 100 },
  language: { allowed: `${L} ,-`, label: 'letters, spaces, hyphens and commas', min: 1, max: 60 },
  policy: { allowed: `${L} '’.,&()-`, label: "letters, spaces and . , & ' - ( )", min: 2, max: 80 },
  variant: { allowed: `${L} '’.-`, label: "letters, spaces and . ' -", min: 2, max: 80 },
  law: { allowed: `${L} '’.,()-`, label: "letters, spaces and . , ' - ( )", min: 2, max: 200 },
} as const
export type TextKind = keyof typeof kinds

const notAllowed = (k: TextKind) => new RegExp(`[^${kinds[k].allowed.replace(/-/g, String.raw`\-`)}]`, 'gu')

/** Drops characters the rule never allows (digits, symbols); use in onChange. */
export const keepText = (kind: TextKind, v: string) => v.replace(notAllowed(kind), '')

/** Error message for a name-like value, or '' when fine. Empty is fine unless `required`. */
export function textError(kind: TextKind, value: string, required = true): string {
  const v = value.replace(/\s+/g, ' ').trim()
  const k = kinds[kind]
  if (!v) return required ? 'This field is required.' : ''
  if (notAllowed(kind).test(v)) return `Use only ${k.label}.`
  if (!/\p{L}/u.test(v)) return 'Include at least one letter.'
  if (v.length < k.min || v.length > k.max) return `Must be ${k.min}-${k.max} characters.`
  return ''
}

/** Registration numbers: letters, digits, hyphen and slash only, 4-30 characters (e.g. SC123456, U12345MH2020PTC123456). */
export const keepRegistration = (v: string) => v.replace(/[^A-Za-z0-9/-]/g, '').toUpperCase()
export function registrationError(value: string, required = false): string {
  const v = value.trim()
  if (!v) return required ? 'This field is required.' : ''
  return /^[A-Za-z0-9/-]{4,30}$/.test(v) ? '' : 'Use 4-30 characters: letters, digits, hyphen and slash only.'
}

/** An http(s) web address whose host contains a dot, no spaces. Empty is fine (optional). */
export function websiteError(value: string): string {
  const v = value.trim()
  if (!v) return ''
  const msg = 'Enter a valid web address such as https://example.com'
  if (/\s/.test(v) || !/^https?:\/\//i.test(v)) return msg
  try {
    const host = new URL(v).hostname
    if (!host.includes('.') || host.startsWith('.') || host.endsWith('.') || host.includes('..')) return msg
  } catch {
    return msg
  }
  return ''
}

/** Collection names: letters, digits, spaces and - ' & (max 40), at least one letter. Mirrors shared/validation.py. */
export const keepCollectionName = (v: string) => v.replace(/[^\p{L}\p{M}\p{N} '’&-]/gu, '').slice(0, 40)
export function collectionNameError(value: string): string {
  const v = value.replace(/\s+/g, ' ').trim()
  if (!v) return 'Enter a collection name.'
  if (!/\p{L}/u.test(v)) return 'Include at least one letter.'
  return ''
}

/** The free-text "what do you need" box: letters, digits, spaces and - ' . , & / only. */
export const keepNeedText = (v: string) => v.replace(/[^\p{L}\p{M}\p{N} '’.,&/-]/gu, '')
export function needTextError(value: string): string {
  const v = value.trim()
  return v && !/\p{L}/u.test(v) ? 'Describe what you need in words.' : ''
}

/** Whole numbers only: drops every non-digit (e E . , + - and letters) so nothing else can be typed or pasted in. */
export const keepDigits = (v: string) => v.replace(/\D/g, '')

/** onKeyDown guard for whole-number boxes: blocks the keys that make a number input accept decimals or exponents. */
export const blockNonIntegerKey = (e: { key: string; preventDefault: () => void }) => {
  if (['e', 'E', '.', ',', '+', '-'].includes(e.key)) e.preventDefault()
}

/** Error for a whole number within [min, max]; empty is fine (use the default). */
export function integerError(value: string, min: number, max?: number): string {
  const v = value.trim()
  if (!v) return ''
  if (!/^\d+$/.test(v)) return 'Enter a whole number.'
  const n = Number(v)
  if (n < min || (max !== undefined && n > max)) return max === undefined ? `Enter a whole number of ${min} or more.` : `Enter a whole number from ${min} to ${max}.`
  return ''
}

export type CodeKind = 'country' | 'currency'
const codeSets = { country: ISO_3166, currency: ISO_4217 } as const
const codeNames = { country: 'ISO 3166-1 country', currency: 'ISO 4217 currency' } as const

/** Splits a comma separated list into upper-case codes, dropping blanks and duplicates. */
export const parseCodes = (v: string) => [...new Set(v.split(',').map((x) => x.trim().toUpperCase()).filter(Boolean))]

/** Drops characters a code list never contains (digits, symbols); use in onChange. Upper-cases. */
export const keepCodes = (v: string) => v.replace(/[^A-Za-z, ]/g, '').toUpperCase()

/** Error for a comma separated list of country or currency codes, or '' when every code is real. Empty is fine unless `required`. */
export function codesError(kind: CodeKind, value: string, required = false): string {
  const codes = parseCodes(value)
  if (!codes.length) return required ? 'Enter at least one code.' : ''
  const bad = codes.filter((c) => !codeSets[kind].has(c))
  return bad.length ? `Not a valid ${codeNames[kind]} code: ${bad.join(', ')}.` : ''
}
