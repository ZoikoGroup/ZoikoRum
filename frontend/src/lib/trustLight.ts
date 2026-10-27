/** Trust lights: how a trust tier is shown to people. The codes A/B/C stay in the API, URLs and filters;
 *  people only ever see the light (colour plus words, never colour alone). */
export type LightTone = 'green' | 'amber' | 'red'
export type TrustLightInfo = { name: 'Green' | 'Amber' | 'Red'; label: string; tone: LightTone; color: string }

export const TRUST_LIGHT: Record<'A' | 'B' | 'C', TrustLightInfo> = {
  A: { name: 'Green', label: 'Fully verified', tone: 'green', color: '#12b76a' },
  B: { name: 'Amber', label: 'Identity verified', tone: 'amber', color: '#f79009' },
  C: { name: 'Red', label: 'Not verified yet', tone: 'red', color: '#f04438' },
}

/** The light for a tier code; anything unknown or missing reads as Red. */
export function trustLight(tier: string | null | undefined): TrustLightInfo {
  return TRUST_LIGHT[(tier ?? 'C') as 'A' | 'B' | 'C'] ?? TRUST_LIGHT.C
}

/** "Green" */
export const lightName = (tier: string | null | undefined) => trustLight(tier).name
/** "Green · Fully verified" */
export const lightText = (tier: string | null | undefined) => `${trustLight(tier).name} · ${trustLight(tier).label}`
/** Chart colour for a tier code. */
export const lightColor = (tier: string | null | undefined) => trustLight(tier).color
