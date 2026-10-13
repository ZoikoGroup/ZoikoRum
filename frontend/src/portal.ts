/** Which sign-in this web app serves (VITE_PORTAL, set in vite.config.ts):
 *  - 'customer': customers, professionals, firms and enterprise teams (npm run dev, port 5173; app.your-domain.com)
 *  - 'staff':    Zoikorum staff only (npm run dev:staff, port 5174; staff.your-domain.com)
 *  - 'both':     one app with both sign-in pages (plain `vite`, used by the browser tests)
 *  Separate addresses also mean separate browser sessions: signing in on one never signs you in on the other. */
export type Portal = 'customer' | 'staff' | 'both'

const env = import.meta.env as Record<string, string | undefined>
export const PORTAL: Portal = env.VITE_PORTAL === 'customer' || env.VITE_PORTAL === 'staff' ? env.VITE_PORTAL : 'both'
const CUSTOMER_URL = (env.VITE_CUSTOMER_URL ?? '').replace(/\/$/, '')
const STAFF_URL = (env.VITE_STAFF_URL ?? '').replace(/\/$/, '')

/** The other app's address for a path, or null when the path is served here. */
export function elsewhere(path: string): string | null {
  const staffPage = path.startsWith('/staff') || path.startsWith('/app/ops')
  if (PORTAL === 'customer' && STAFF_URL && staffPage) return STAFF_URL + path
  if (PORTAL === 'staff' && CUSTOMER_URL && !staffPage) return CUSTOMER_URL + path
  return null
}

/** The sign-in page for staff or for everyone else: a path here, or a full address on the other app. */
export function signInHref(staff: boolean): string {
  const path = staff ? '/staff/login' : '/login'
  return elsewhere(path) ?? path
}
