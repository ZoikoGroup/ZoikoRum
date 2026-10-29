// Text rules for names and similar free text. Mirrors backend/src/zoikorum/shared/validation.py: keep the two in step.
// Unicode-friendly (letters and their combining marks by property, not an ASCII range). Errors show on blur or submit,
// never while typing; `keep*` helpers drop characters that can never be valid so they cannot be typed or pasted in.

const L = String.raw`\p{L}\p{M}`
const kinds = {
  person: { allowed: `${L} '’.-`, label: 'letters, spaces, apostrophes, hyphens and periods', min: 1, max: 200 },
  org: { allowed: `${L} '’.,&()-`, label: "letters, spaces and . , & ' - ( )", min: 2, max: 200 },
  role: { allowed: `${L} '’.,&/()-`, label: "letters, spaces and & / , ' - . ( )", min: 1, max: 120 },
  city: { allowed: `${L} '’.-`, label: 'letters, spaces, apostrophes, hyphens and periods', min: 1, max: 100 },
  language: { allowed: `${L} ,-`, label: 'letters, spaces, hyphens and commas', min: 1, max: 60 },
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
