import { describe, expect, it } from 'vitest'
import { dashboardPath, isStaffPath, legacyOpsPath, STAFF_HOME } from './staffRoutes'

describe('staff console routes', () => {
  it('sends every old /app/ops page to its registry address', () => {
    expect(legacyOpsPath('/app/ops')).toBe('/platform-admin/command-center')
    expect(legacyOpsPath('/app/ops/')).toBe('/platform-admin/command-center')
    expect(legacyOpsPath('/app/ops/queue')).toBe('/platform-admin/my-work-queue')
    expect(legacyOpsPath('/app/ops/users')).toBe('/platform-admin/accounts-organizations')
    expect(legacyOpsPath('/app/ops/money')).toBe('/platform-admin/financial-exceptions')
    expect(legacyOpsPath('/app/ops/dead-letters')).toBe('/platform-admin/failed-event-deliveries')
    expect(legacyOpsPath('/app/ops/config')).toBe('/platform-admin/platform-configuration')
    expect(legacyOpsPath('/app/ops/approvals')).toBe('/platform-admin/approvals')
    expect(legacyOpsPath('/app/ops/ai')).toBe('/platform-admin/ai-governance')
    expect(legacyOpsPath('/app/ops/no-such-page')).toBe(STAFF_HOME)
  })

  it('knows staff paths and the signed-in home', () => {
    expect(isStaffPath('/platform-admin/trust-safety')).toBe(true)
    expect(isStaffPath('/app/ops/safety')).toBe(true)
    expect(isStaffPath('/app/opsx')).toBe(false)
    expect(isStaffPath('/app/disputes/1')).toBe(false)
    expect(dashboardPath({ defaultDashboard: 'ops' })).toBe(STAFF_HOME)
    expect(dashboardPath({ defaultDashboard: 'buyer' })).toBe('/app/buyer')
  })
})
