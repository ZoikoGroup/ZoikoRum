import type { User } from './api/auth'

/* Staff console routes (Admin Navigation Registry ZKR-ADMIN-ENG-001): /platform-admin/<slug>. The old /app/ops paths
   still work: they redirect here, so bookmarks and links in older emails keep opening the right page. */

export const STAFF_PREFIX = '/platform-admin'
export const STAFF_HOME = `${STAFF_PREFIX}/command-center`

/** Old /app/ops/<segment> -> registry slug. */
const LEGACY_OPS: Record<string, string> = {
  '': 'command-center', queue: 'my-work-queue', analytics: 'analytics-insights', users: 'accounts-organizations',
  professionals: 'professional-directory', enterprise: 'enterprise-readiness', duplicates: 'duplicate-identity-cases',
  verification: 'verification-center', safety: 'trust-safety', disputes: 'dispute-resolution', audit: 'audit-evidence',
  engagements: 'engagement-oversight', contracts: 'contracts-milestones', taxonomy: 'taxonomy-standards',
  payments: 'protected-payments', reconciliation: 'reconciliation', money: 'financial-exceptions',
  incidents: 'incident-command', health: 'service-health-workers', switches: 'feature-controls',
  'dead-letters': 'failed-event-deliveries', staff: 'staff-access-control', support: 'support-cases',
  config: 'platform-configuration', approvals: 'approvals', ai: 'ai-governance',
}

export const isStaffPath = (path: string) =>
  path === STAFF_PREFIX || path.startsWith(`${STAFF_PREFIX}/`) || path === '/app/ops' || path.startsWith('/app/ops/')

/** Where an old /app/ops path (pathname only) lives now; unknown pages go to the Command Center. */
export function legacyOpsPath(pathname: string): string {
  const segment = pathname.replace(/^\/app\/ops\/?/, '').split('/')[0] ?? ''
  return `${STAFF_PREFIX}/${LEGACY_OPS[segment] ?? LEGACY_OPS['']}`
}

/** The signed-in home: the Command Center for staff, otherwise the persona dashboard. */
export function dashboardPath(user: Pick<User, 'defaultDashboard'>): string {
  return user.defaultDashboard === 'ops' ? STAFF_HOME : `/app/${user.defaultDashboard}`
}
