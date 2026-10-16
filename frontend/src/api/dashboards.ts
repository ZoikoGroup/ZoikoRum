import { api } from './client'
import type { Money } from './orgs'

/** Dashboard summaries, rebuilt from events (GET /v1/dashboards/*). Amounts are per currency, in minor units. */
export interface DashboardSummary {
  activeEngagements: number
  pendingActions: number
  fundsInProtectionMinor: Record<string, number>
  pendingReleaseMinor: Record<string, number>
  earningsThisMonthMinor: Record<string, number>
  /** When the newest event behind these figures happened: how fresh the summary is. */
  lastEventAt: string | null
}

export const dashboardApi = {
  buyer: (organizationId: string) => api<DashboardSummary>('/v1/dashboards/buyer', { query: { organizationId } }),
  professional: () => api<DashboardSummary>('/v1/dashboards/professional'),
}

/** {"USD": 12000} -> [{amountMinor: 12000, currency: "USD"}], leaving out zero balances. */
export const moneyOf = (byCurrency: Record<string, number> | undefined): Money[] =>
  Object.entries(byCurrency ?? {}).filter(([, minor]) => minor > 0).map(([currency, amountMinor]) => ({ currency, amountMinor }))
