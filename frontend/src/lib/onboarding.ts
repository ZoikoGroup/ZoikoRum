/* Pure helpers for professional onboarding: photo crop maths, a bio readability hint, specialization previews and the
   verification checklist's timings. No React, so they are unit-tested directly (onboarding.test.ts). */

/** The square of the source image to keep: `zoom` >= 1 narrows it, `x`/`y` (0-100) move it across the spare room. */
export function cropRect(width: number, height: number, zoom: number, x: number, y: number) {
  const side = Math.max(1, Math.min(width, height) / Math.max(1, zoom))
  const clamp = (v: number) => Math.min(100, Math.max(0, v)) / 100
  return { sx: (width - side) * clamp(x), sy: (height - side) * clamp(y), side }
}

export interface Readability { words: number; sentences: number; avgSentence: number; longWordShare: number; level: 'empty' | 'easy' | 'ok' | 'hard'; message: string }

/** A simple, explainable readability hint (sentence length and long words), not a score to chase. */
export function readability(text: string): Readability {
  const words = text.trim() ? text.trim().split(/\s+/) : []
  const sentences = Math.max(1, text.split(/[.!?]+(\s|$)/).filter((s) => s && s.trim().length > 1).length)
  const avgSentence = words.length ? words.length / sentences : 0
  const long = words.filter((w) => w.replace(/[^A-Za-z]/g, '').length >= 13).length
  const longWordShare = words.length ? long / words.length : 0
  if (!words.length) return { words: 0, sentences: 0, avgSentence: 0, longWordShare: 0, level: 'empty', message: '' }
  const rounded = Math.round(avgSentence)
  if (avgSentence > 28 || longWordShare > 0.15) {
    return { words: words.length, sentences, avgSentence, longWordShare, level: 'hard',
      message: `Hard to scan: about ${rounded} words a sentence. Try splitting long sentences and using plainer words.` }
  }
  if (avgSentence > 20) {
    return { words: words.length, sentences, avgSentence, longWordShare, level: 'ok',
      message: `Readable: about ${rounded} words a sentence. A few shorter sentences would help buyers skim.` }
  }
  return { words: words.length, sentences, avgSentence, longWordShare, level: 'easy', message: `Easy to read: about ${rounded} words a sentence.` }
}

/** One plain sentence describing a specialization from its place in the taxonomy and its flags. */
export function specDescription(s: { name: string; requiresCredential: boolean; regulated: boolean }, group: string, category: string): string {
  const parts = [`${s.name} work within ${group} (${category}).`]
  if (s.regulated) parts.push('Regulated work: enterprise buyers usually require Tier A and indemnity insurance.')
  if (s.requiresCredential) parts.push('Shown as verified once a matching credential is validated.')
  if (!s.regulated && !s.requiresCredential) parts.push('No licence is needed; your experience and offerings carry the most weight.')
  return parts.join(' ')
}

/** Verification checklist rows: how long each check usually takes and why it is asked for. */
export const CHECK_INFO: Record<string, { eta: string; why: string }> = {
  email: { eta: 'Instant, from the link we emailed you', why: 'Requests, contracts and payment notices are sent to this address.' },
  identity: { eta: 'Minutes online; about 24 hours if a person reviews it', why: 'Proves you are who your profile says. Needed for Tier B and to send proposals.' },
  credentials: { eta: '2–5 business days', why: 'Checked with the issuing body so buyers can rely on it. Needed for Tier A in credential-led specializations.' },
  jurisdiction: { eta: '2–5 business days', why: 'Confirms you may practise where you take regulated work.' },
  insurance: { eta: '1–2 business days', why: 'Professional indemnity insurance protects your clients; regulated work and many enterprises require it.' },
  restrictions: { eta: 'Usually within 24 hours', why: 'Sanctions and restrictions screening keeps the marketplace safe. Results are never shown publicly.' },
}

/** The tier a professional reaches next, and what gets them there. */
export function nextTier(tier: string, dimensions: Record<string, string>): { tier: string; needs: string } | null {
  if (tier === 'A') return null
  if (tier === 'C' || dimensions.identity !== 'VERIFIED') return { tier: 'B', needs: 'Verify your identity (screening runs alongside).' }
  return { tier: 'A', needs: 'Validate required credentials, a jurisdiction and insurance where your work needs it.' }
}
