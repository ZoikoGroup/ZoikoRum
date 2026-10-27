import { trustLight } from '../lib/trustLight'

/** A trust tier shown as a traffic light: a coloured dot plus words, so it never relies on colour alone.
 *  `compact` shows only the light's name ("Green"); the meaning stays in the tooltip and for screen readers. */
export function TrustLight({ tier, compact = false, prefix }: { tier: string | null | undefined; compact?: boolean; prefix?: string }) {
  const l = trustLight(tier)
  return (
    <span className={`badge trust-light ${l.tone}`} title={`${l.name} light: ${l.label}`}>
      <span className="light-dot" style={{ background: l.color }} aria-hidden />
      <span className="sr-only">Trust light: </span>
      {prefix ? `${prefix} ` : ''}{l.name}
      {compact ? <span className="sr-only"> · {l.label}</span> : ` · ${l.label}`}
    </span>
  )
}
