import type { Action } from '../components/dashboard'
import { OPEN_PHASES, type Dispute } from '../api/disputes'
import type { Charge, Payout, Refund } from '../api/escrow'
import { formatMoney } from '../api/orgs'
import type { ProposalRequest } from '../api/proposals'

/* Pending-action items for the problems both dashboards must surface (Buyer Dashboard s.16, Professional Dashboard
   s.18): open disputes, failed payments and payouts, jurisdiction conflicts and the other side going quiet. Each says
   what happened, what to do next and where. */

const PHASE: Record<string, string> = {
  EVIDENCE_COLLECTION: 'collecting evidence', DIRECT_RESOLUTION: 'resolving directly', MEDIATION: 'in mediation',
}

/** One High item per open dispute; funds stay held until it is resolved. */
export function disputeActions(disputes: Dispute[]): Action[] {
  return disputes.filter((d) => OPEN_PHASES.includes(d.status)).map((d) => ({
    title: `Dispute ${d.reference} is ${PHASE[d.status] ?? 'open'}`,
    detail: d.nextStep || `${formatMoney(d.disputed)} held until it is resolved`,
    priority: 'High', to: `/app/disputes/${d.id}`, icon: 'help',
  }))
}

/** Buyer: an engagement whose latest charge failed or was charged back, and refunds that did not go through. */
export function buyerPaymentActions(charges: Charge[], refunds: Refund[]): Action[] {
  const latest = new Map<string, Charge>()
  for (const c of charges) {
    const seen = latest.get(c.contractId)
    if (!seen || c.createdAt > seen.createdAt) latest.set(c.contractId, c)
  }
  const actions: Action[] = []
  for (const c of latest.values()) {
    if (c.status === 'FAILED') actions.push({ title: `Payment of ${formatMoney(c.amount)} failed`,
      detail: `${c.failureMessage ?? 'The payment was declined'} · fund the milestone again with another method`,
      priority: 'High', to: `/app/engagements/${c.contractId}`, icon: 'wallet' })
    if (c.status === 'CHARGED_BACK') actions.push({ title: `Payment of ${formatMoney(c.amount)} was charged back`,
      detail: 'Work on the engagement may pause until it is settled · contact support if this is a mistake',
      priority: 'High', to: `/app/engagements/${c.contractId}`, icon: 'wallet' })
  }
  for (const r of refunds.filter((r) => r.status === 'FAILED')) {
    actions.push({ title: `Refund of ${formatMoney(r.amount)} is delayed`,
      detail: `${r.failureMessage ?? 'The refund did not go through'} · our payments team is retrying it`,
      priority: 'Medium', to: '/app/payments', icon: 'wallet' })
  }
  return actions
}

/** Professional: failed payouts, and payouts the provider has delayed. */
export function payoutActions(payouts: Payout[]): Action[] {
  const actions: Action[] = []
  for (const p of payouts) {
    if (p.status === 'FAILED') actions.push({ title: `Payout of ${formatMoney(p.net)} failed`,
      detail: `${p.failureMessage ?? 'The payout did not go through'} · check your payout account`,
      priority: 'High', to: '/app/professional/earnings', icon: 'wallet' })
    else if (p.delayReason && (p.status === 'QUEUED' || p.status === 'INITIATED')) actions.push({
      title: `Payout of ${formatMoney(p.net)} is delayed`, detail: p.delayReason,
      priority: 'Medium', to: '/app/professional/earnings', icon: 'clock' })
  }
  return actions
}

const DAY = 86400_000

/** Buyer: requests stopped by a jurisdiction conflict, and professionals who did not answer by the date asked. */
export function buyerRequestActions(requests: ProposalRequest[], now: number): Action[] {
  const actions: Action[] = []
  for (const r of requests.filter((r) => r.status === 'OPEN' || r.status === 'PROPOSAL_RECEIVED')) {
    if (r.jurisdictionConflict) actions.push({ title: `Jurisdiction conflict: ${r.service}`,
      detail: `${r.professional.displayName} cannot take this work where it is needed · choose another professional or ask support`,
      priority: 'High', to: `/app/requests/${r.id}`, icon: 'globe' })
    else if (r.status === 'OPEN' && !r.proposal && r.respondBy && new Date(r.respondBy).getTime() < now) actions.push({
      title: `No answer yet from ${r.professional.displayName}`,
      detail: `${r.service} · the answer was due ${new Date(r.respondBy).toLocaleDateString()}: send a message, or cancel and invite someone else`,
      priority: 'Medium', to: `/app/requests/${r.id}`, icon: 'clock' })
  }
  return actions
}

/** Professional: requests outside the jurisdictions you may serve, and proposals the buyer has left unanswered a week. */
export function professionalRequestActions(requests: ProposalRequest[], now: number): Action[] {
  const actions: Action[] = []
  for (const r of requests) {
    const buyer = r.organizationName ?? 'The buyer'
    if (r.status === 'OPEN' && r.jurisdictionConflict) actions.push({ title: `Jurisdiction restriction: ${r.service}`,
      detail: `${buyer} needs this where you are not set up to serve · decline it, or add the jurisdiction to your profile`,
      priority: 'High', to: `/app/professional/requests/${r.id}`, icon: 'globe' })
    const sent = r.proposal?.submittedAt
    if (sent && ['SUBMITTED', 'UNDER_REVIEW'].includes(r.proposal!.status) && now - new Date(sent).getTime() > 7 * DAY) actions.push({
      title: `${buyer} has not responded yet`,
      detail: `${r.service} · proposal sent ${new Date(sent).toLocaleDateString()}: a short message often helps`,
      priority: 'Low', to: `/app/messages?contextType=PROPOSAL_REQUEST&contextId=${r.id}`, icon: 'message' })
  }
  return actions
}

/** The count a "Pending Actions" card shows: things that need acting on, not recommendations. */
export const urgentCount = (actions: Action[]) => actions.filter((a) => a.priority !== 'Low').length
