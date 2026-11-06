import type { ReactNode } from 'react'

/* Small line icons for the sign-in, register and reset pages (24px grid, stroke follows the text colour). */
const PATHS: Record<string, ReactNode> = {
  mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6.5 6.5 0 0 1 3.5 6" /></>,
  shield: <><path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z" /><path d="m9 12 2 2 4-4" /></>,
  doc: <><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M10 12h5M10 16h5" /></>,
  chart: <><path d="M5 20V10M12 20V4M19 20v-7" /></>,
  building: <><rect x="5" y="3" width="10" height="18" rx="1" /><path d="M15 9h4v12h-4M8 7h4M8 11h4M8 15h4" /></>,
  pin: <><path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  money: <><rect x="3" y="6" width="18" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /></>,
  phone: <><rect x="7" y="2.5" width="10" height="19" rx="2" /><path d="M11 18.5h2" /></>,
  chevron: <path d="m9 6 6 6-6 6" />,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  briefcase: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18" /></>,
}

export function Icon({ name, size = 20 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">{PATHS[name]}</svg>
  )
}

/** Brand marks for the "continue with" buttons. */
export function BrandIcon({ name }: { name: 'microsoft' | 'google' | 'apple' | 'company' }) {
  if (name === 'microsoft') return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden><path fill="#f25022" d="M2 2h10v10H2z" /><path fill="#7fba00" d="M12 2h10v10H12z" />
      <path fill="#00a4ef" d="M2 12h10v10H2z" /><path fill="#ffb900" d="M12 12h10v10H12z" /></svg>)
  if (name === 'google') return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden>
      <path fill="#4285f4" d="M21.6 12.2c0-.7-.1-1.3-.2-1.9H12v3.7h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.300 3-7.300z" />
      <path fill="#34a853" d="M12 22c2.700 0 4.900-.9 6.600-2.400l-3.200-2.500c-.9.600-2 1-3.400 1-2.600 0-4.800-1.800-5.600-4.100H3.100v2.600A10 10 0 0 0 12 22z" />
      <path fill="#fbbc05" d="M6.400 14c-.2-.6-.3-1.300-.3-2s.1-1.400.3-2V7.400H3.100a10 10 0 0 0 0 9.200z" />
      <path fill="#ea4335" d="M12 5.900c1.500 0 2.800.5 3.800 1.500l2.900-2.900A10 10 0 0 0 3.100 7.400L6.400 10C7.200 7.700 9.400 5.900 12 5.900z" /></svg>)
  if (name === 'apple') return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden><path fill="currentColor" d="M16.400 12.600c0-2.300 1.900-3.400 2-3.500a4.300 4.300 0 0 0-3.400-1.800c-1.400-.1-2.800.9-3.500.9s-1.800-.8-3-.8a4.500 4.500 0 0 0-3.800 2.300c-1.600 2.800-.4 7 1.200 9.300.8 1.100 1.700 2.400 2.900 2.300 1.200 0 1.600-.7 3-.7s1.800.7 3 .7 2.100-1.100 2.800-2.200a9.500 9.500 0 0 0 1.300-2.700 4 4 0 0 1-2.500-3.800zM14.200 5.800a4 4 0 0 0 .9-2.900 4.100 4.100 0 0 0-2.700 1.400 3.800 3.800 0 0 0-1 2.800 3.400 3.400 0 0 0 2.800-1.300z" /></svg>)
  return <Icon name="building" />
}
