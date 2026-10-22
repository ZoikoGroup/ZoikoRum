import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import contract from './contract.json'

/* Contract test between the web app and the API. contract.json is generated from the backend's models
   (python -m zoikorum.cli api-contract; a backend test keeps it current). Every field a TypeScript response type
   declares must exist on the backend model it mirrors, so a renamed or removed backend field fails here instead of
   showing as "undefined" on a page. */

const MIRRORS: Record<string, string | string[]> = {
  Contract: 'ContractOut', ContractRevision: 'ContractRevisionOut', ChangeOrder: 'ChangeOrderOut', TerminationRequest: 'TerminationRequestOut',
  Dispute: 'DisputeOut', Escrow: 'EscrowOut', LedgerLine: 'LedgerLineOut', Payout: 'PayoutOut', Earnings: 'EarningsOut',
  Invoice: 'InvoiceOut', Charge: 'ChargeOut', Refund: 'RefundOut', Reconciliation: 'ReconciliationOut',
  MessageThread: 'ThreadOut', ConversationMessage: 'MessageOut', MessageHit: 'MessageHitOut',
  Organization: 'OrganizationOut', BillingContact: 'BillingContactOut', OrgMember: 'MemberOut', Invitation: ['InvitationOut', 'FirmInvitationOut'],
  BusinessUnit: 'BusinessUnitOut', CostCenter: 'CostCenterOut', LegalEntity: 'LegalEntityOut', Firm: 'FirmOut', FirmMember: 'FirmMemberOut',
  FirmOverview: 'FirmOverviewOut', FirmProfessionalWork: 'FirmProfessionalWork', FirmMoney: 'MoneyTotal', PublicFirm: 'FirmPageOut',
  Profile: 'ProfileOut', Readiness: 'ReadinessOut', Credential: 'CredentialOut', Offering: 'OfferingOut', PublicProfile: 'PublicProfileOut',
  SavedBuyer: 'SavedBuyerOut', BuyerCandidate: 'BuyerCandidateOut', ProposalRequest: 'RequestOut', RequestSummary: 'RequestSummaryOut',
  SavedSearch: 'SavedSearchOut', SearchResult: 'ResultItem', SearchResponse: 'SearchOut', IntentResponse: 'IntentOut',
  SupportMessage: 'SupportMessageOut', SupportRequest: 'SupportRequestOut', VerificationCase: 'CaseOut', Appeal: 'AppealOut',
  AppealQueueItem: 'AppealQueueItemOut', QueueItem: 'QueueItemOut', Trust: 'TrustOut', TrustHistory: 'TrustHistoryOut',
  StoredFile: 'StoredFileOut', DeviceSession: 'SessionOut', Passkey: 'PasskeyOut', StaffMember: 'StaffMemberOut',
  ApprovalRequest: 'ApprovalRequestOut', ApprovalSummary: 'ApprovalSummaryOut',
}

const here = dirname(fileURLToPath(import.meta.url))

/** Top-level field names of every `export interface` in the API client files (nested object types are skipped). */
function interfaces(): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const file of readdirSync(here).filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts'))) {
    const text = readFileSync(join(here, file), 'utf8')
    for (const m of text.matchAll(/^export interface (\w+)(?:<[^>]*>)?(?: extends [^{]+)? \{/gm)) {
      let depth = 1
      let segment = ''
      const fields: string[] = []
      const take = () => { const f = /^\s*(\w+)\??\s*:/.exec(segment); if (f) fields.push(f[1]); segment = '' }
      for (let i = m.index + m[0].length; i < text.length && depth > 0; i++) {
        const ch = text[i]
        if ('{[('.includes(ch)) depth++
        else if ('}])'.includes(ch)) depth--
        if (depth === 1 && (ch === ';' || ch === '\n' ||ch === ',')) take()
        else if (depth >= 1) segment += ch
      }
      take()
      out[m[1]] = fields
    }
  }
  return out
}

describe('API contract', () => {
  const types = interfaces()
  const models = contract as Record<string, string[]>

  it('mirrors real backend models', () => {
    for (const [ts, model] of Object.entries(MIRRORS)) {
      expect(types[ts], `TypeScript type ${ts}`).toBeDefined()
      for (const m of [model].flat()) expect(models[m], `backend model ${m}`).toBeDefined()
    }
  })

  it.each(Object.entries(MIRRORS))('%s only reads fields the backend sends', (ts, model) => {
    const missing = (types[ts] ?? []).filter((f) => ![model].flat().some((m) => models[m]?.includes(f)))
    expect(missing, `${ts} declares fields ${model} does not have`).toEqual([])
  })
})
