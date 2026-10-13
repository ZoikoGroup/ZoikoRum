# Zoikorum Backend — Build Spec (implementation contract)

This file turns the 18 source documents in `docs/product/` (Architecture, Engineering Handbook,
and the wireframes/charters) into buildable contracts. Every domain must follow
it. When in doubt, re-read `src/zoikorum/domains/identity` (reference domain)
and `src/zoikorum/shared` (kernel).

## 0. Non-negotiables (apply to every domain)

1. **Layout**: `models.py`, `schemas.py`, `service.py`, `api.py` (`router`), `handlers.py`, `facade.py`.
2. **Own schema only**: tables use `__table_args__ = {"schema": "<domain>"}`. No cross-schema FKs —
   reference other domains by plain UUID columns. Never query another domain's tables.
3. **Cross-domain reads** go through `zoikorum.domains.<other>.facade` only (enforced by tests/test_architecture.py).
   Facade signatures/DTOs in `domains/*/facade.py` are FIXED contracts — implement your own, do not change others'.
4. **Cross-domain reactions** go through events: `record_event(session, E.X, ...)` in the same transaction as
   the state change; subscribe with `@subscribe(E.X, consumer="<domain>.<purpose>")` in `handlers.py`.
   Handlers MUST be idempotent (they run at-least-once). Use only events in `shared/event_catalog.py`.
5. **State machines**: use `shared.state_machine.StateMachine`; every transition asserted in the service.
6. **Money**: `Money` / `MoneyDTO` (integer minor units + currency). Columns `<x>_minor BIGINT`, `currency CHAR(3)`. Never floats.
7. **Idempotency**: every commercial mutation endpoint takes `idem: IdempotencyKey` and wraps the call with
   `await idem.run(session, actor, lambda: ...)`.
8. **Authorization**: `actor: CurrentActor`; ABAC checks inside services (`actor.require_org(...)`,
   `actor.require_professional(...)`, `actor.require_platform_role(...)`); step-up via `actor.require_step_up()` for:
   contract signing, escrow release/funding approvals above policy threshold, payout-account changes,
   verification decisions, operator enforcement, policy activation.
9. **Errors**: raise `shared.errors.*` (rendered as Problem Details). Never return error dicts.
10. **Audit**: every event is audited automatically. Use `record_audit(...)` for non-event actions
    (e.g. viewing evidence, downloading documents).
11. **Optimistic concurrency**: aggregates edited by multiple actors use the `Versioned` mixin; expose `version`.
12. **Time**: `shared.clock.now()` only. Deadlines/expiries use durable timers (`schedule_timer` / `@on_timer`).
13. **AI never decides**: no AI output may approve, accept, sign, release, resolve, or enforce.
14. **Pagination**: list endpoints use `shared.http.paginate/page_of` (cursor) — never unbounded.
15. **Tests**: `tests/test_<domain>.py` covering happy path + top failure modes (invalid transition, authz,
    idempotent replay, policy block). Use fixtures from tests/conftest.py (`client`, `make_user`, `drain`, `sf`).
    When a test needs another domain's facade that is not built yet, monkeypatch the facade function.
16. **Append-only tables** already registered in `shared/ddl.py`: audit.audit_records, escrow.ledger_entries,
    dispute.evidence_items, verification.evidence_items, contract.signatures, messaging.messages,
    policy.policy_evaluations. Use exactly these table names; never UPDATE/DELETE them.

## 1. Platform spine (end-to-end flow everything must support)

```
Buyer registers org ─► searches ─► POST proposal-request ─► Pro submits proposal ─► Buyer accepts
  └ policy PROPOSAL_ACCEPT (ALLOW | REQUIRE_APPROVAL → approval granted)
PROPOSAL_ACCEPTED ─► contract generated (+milestones) ─► buyer signs (step-up) ─► pro countersigns
CONTRACT_ACTIVATED ─► escrow opened ─► buyer funds (ESCROW_FUNDING_REQUESTED) ─► payments captures
PAYMENT_CAPTURED ─► ESCROW_FUNDED ─► milestone IN_PROGRESS ─► pro submits ─► buyer accepts
MILESTONE_ACCEPTED ─► escrow release decision tree (policy ESCROW_RELEASE) ─► ESCROW_RELEASED
  ─► payments payout (PAYOUT_SETTLED) + invoice ─► all milestones accepted ─► CONTRACT_COMPLETED
  ─► trust signal ─► TRUST_SCORE_RECOMPUTED ─► search reindex
Branch: DISPUTE_INITIATED ─► ESCROW_HOLD_APPLIED (≤5s) ─► evidence ─► direct resolution / mediation
  ─► DISPUTE_RESOLVED(split) ─► ESCROW_RESOLUTION_EXECUTED ─► DISPUTE_ENFORCED ─► DISPUTE_CLOSED
```

## 2. Event payload contracts (camelCase keys; IDs are UUID strings; money = minor ints + currency)

Only the fields below are guaranteed; producers may add more. Consumers must ignore unknown fields.

| Event | Required payload |
|---|---|
| PROFESSIONAL_REGISTERED | professionalId, identityId, firmId?, country |
| PROFILE_PUBLISHED / PROFILE_UPDATED / PROFILE_UNPUBLISHED / PROFILE_SUSPENDED / PROFILE_REINSTATED | professionalId |
| SERVICE_OFFERING_CREATED / _UPDATED / _STATUS_CHANGED | professionalId, offeringId, status |
| AVAILABILITY_UPDATED / CAPACITY_CHANGED | professionalId, availability, activeEngagements, maxConcurrent? |
| JURISDICTIONS_UPDATED | professionalId, served[], licensed[] |
| CREDENTIAL_SUBMITTED | professionalId, credentialClaimId, credentialName, issuingBody, registrationNumber, jurisdiction, issuedOn?, expiresOn?, specialization? |
| BUYER_REGISTERED | identityId, organizationId |
| ORGANIZATION_CREATED | organizationId, name, orgType, country |
| ORG_MEMBER_ADDED / BUYER_ROLE_ASSIGNED | organizationId, identityId, roles[] |
| ORG_MEMBER_REMOVED | organizationId, identityId |
| FIRM_REGISTERED | firmId, identityId (creator) |
| FIRM_MEMBER_JOINED | firmId, identityId, roles[] ; FIRM_MEMBER_REMOVED: firmId, identityId |
| FIRM_VERIFIED | firmId |
| PROPOSAL_REQUESTED | requestId, organizationId, buyerIdentityId, professionalId, offeringId?, engagementType, ndaRequired |
| PROPOSAL_REQUEST_DECLINED | requestId, professionalId, organizationId, reasonCode |
| PROPOSAL_SUBMITTED / PROPOSAL_REVISED | proposalId, requestId, organizationId, professionalId, totalMinor, currency, validUntil |
| PROPOSAL_REVISION_REQUESTED | proposalId, requestId, professionalId, organizationId |
| PROPOSAL_ACCEPTANCE_PENDING_APPROVAL | proposalId, approvalRequestId, organizationId |
| PROPOSAL_ACCEPTED | proposalId, requestId, organizationId, buyerIdentityId, professionalId, engagementType, currency, totalMinor, policyVersionId?, policyVersionLabel, termsHash, **terms**: {objective, scope, deliverables:[{key,title,description,acceptanceCriteria}], milestones:[{sequence,title,description,amountMinor,dueDate?,deliverableKeys[]}], assumptions[], exclusions[], startDate?, endDate?, governingLaw?, clauses[]} |
| PROPOSAL_REJECTED / _WITHDRAWN / _EXPIRED | proposalId, requestId, organizationId, professionalId |
| CONTRACT_GENERATED | contractId, proposalId, organizationId, buyerIdentityId, professionalId, totalMinor, currency, termsHash, signatureDeadline |
| CONTRACT_SIGNED | contractId, signerIdentityId, party (BUYER/PROFESSIONAL), termsHash |
| CONTRACT_ACTIVATED | contractId, organizationId, buyerIdentityId, professionalId, currency, totalMinor, policyVersionId?, milestones:[{milestoneId, sequence, amountMinor, title}] |
| MILESTONE_CREATED | contractId, milestoneId, sequence, amountMinor, currency |
| MILESTONE_STARTED | contractId, milestoneId |
| MILESTONE_SUBMITTED | contractId, milestoneId, organizationId, professionalId, submissionId, acceptanceDueAt |
| MILESTONE_REVISION_REQUESTED | contractId, milestoneId, organizationId, professionalId, reason |
| MILESTONE_ACCEPTED | contractId, milestoneId, organizationId, professionalId, amountMinor, currency, acceptedBy, onTime(bool), auto(bool) |
| CONTRACT_AMENDED | contractId, contractVersion, termsHash, milestones (full new list as in CONTRACT_ACTIVATED) |
| CONTRACT_COMPLETED / CONTRACT_TERMINATED | contractId, organizationId, professionalId, reason? |
| CONTRACT_DISPUTED / CONTRACT_DISPUTE_CLEARED | contractId, disputeId |
| ESCROW_OPENED | escrowAccountId, contractId, organizationId, professionalId, currency, totalMinor |
| ESCROW_FUNDING_REQUESTED | escrowAccountId, fundingId, contractId, organizationId, amountMinor, currency, milestoneIds[], paymentMethodToken |
| PAYMENT_CAPTURED | paymentIntentId, escrowAccountId, fundingId, amountMinor, currency, providerRef |
| PAYMENT_FAILED | paymentIntentId, escrowAccountId, fundingId, amountMinor, currency, failureCode, failureMessage |
| ESCROW_FUNDED | escrowAccountId, contractId, fundingId, organizationId, milestoneIds[], amountMinor, currency |
| ESCROW_HOLD_APPLIED / ESCROW_HOLD_RELEASED | escrowAccountId, contractId, disputeId, milestoneIds[], amountMinor |
| ESCROW_RELEASE_PENDING_APPROVAL | escrowAccountId, contractId, milestoneId, approvalRequestId |
| ESCROW_RELEASED | escrowAccountId, contractId, milestoneId?, disputeId?, organizationId, professionalId, grossMinor, feeMinor, netMinor, currency, releaseId |
| ESCROW_REFUNDED | escrowAccountId, contractId, milestoneId?, disputeId?, organizationId, amountMinor, currency, refundId, fundingIds[] |
| ESCROW_RESOLUTION_EXECUTED | escrowAccountId, contractId, disputeId, releasedMinor, refundedMinor, currency |
| PAYOUT_INITIATED / PAYOUT_SETTLED / PAYOUT_FAILED | payoutId, professionalId, releaseId, amountMinor, currency |
| REFUND_SETTLED | refundId, escrowAccountId, amountMinor, currency |
| INVOICE_ISSUED | invoiceId, invoiceNumber, organizationId, contractId, milestoneId?, totalMinor, currency |
| VERIFICATION_STARTED | caseId, subjectType, subjectId, verificationType |
| VERIFICATION_COMPLETED | caseId, subjectType, subjectId, verificationType, label, jurisdiction?, expiresAt?, credentialClaimId?, specialization? |
| VERIFICATION_FAILED / VERIFICATION_NEEDS_INFO | caseId, subjectType, subjectId, verificationType, reasonCode, publicReason |
| VERIFICATION_EXPIRING | caseId, subjectType, subjectId, verificationType, expiresAt, daysLeft |
| VERIFICATION_EXPIRED / VERIFICATION_REVOKED | caseId, subjectType, subjectId, verificationType, credentialClaimId? |
| TRUST_SCORE_RECOMPUTED | professionalId, score, tier, dimensions{} |
| TRUST_TIER_CHANGED | professionalId, fromTier, toTier, reasons[] |
| TRUST_PROFILE_FLAGGED | professionalId, flag, reasonCode |
| POLICY_EVALUATED | evaluationId, orgId?, action, subjectType, subjectId, decision, policyVersionLabel, reasons[] |
| APPROVAL_REQUIRED | approvalRequestId, orgId, subjectType, subjectId, action, approverRoles[], amountMinor?, currency?, dueAt |
| APPROVAL_GRANTED / APPROVAL_DENIED | approvalRequestId, orgId, subjectType, subjectId, action, decidedBy, reason? |
| EXCEPTION_GRANTED | exceptionId, orgId, subjectType, subjectId, action, expiresAt |
| DISPUTE_INITIATED | disputeId, contractId, organizationId, professionalId, milestoneIds[], category, desiredOutcome, initiatedBy? |
| DISPUTE_RESOLVED | disputeId, contractId, organizationId, professionalId, outcome, decidedBy, decisionPath (DIRECT/MEDIATION/PLATFORM), allocations:[{milestoneId, releaseMinor, refundMinor}], milestoneOutcome (ACCEPT/REWORK/CANCEL/EXTEND), currency |
| DISPUTE_CLOSED | disputeId, contractId |
| ENFORCEMENT_ACTION_APPLIED / _REVERSED | caseId, subjectType (IDENTITY/PROFESSIONAL/ORGANIZATION), subjectId, action, level, reasonCode, notice{whatHappened, why, whatChanged, whatYouCanDo, whatHappensNext, howToGetHelp}, recipientIdentityIds[] |
| RISK_FLAG_RAISED | flagId, subjectType, subjectId, riskScore, reasonCodes[], source |
| MESSAGE_SENT | threadId, messageId, contextType, contextId, senderIdentityId, recipientIdentityIds[] |
| NOTIFICATION_* | notificationId, recipientIdentityId, template |

## 3. Domain specifications

### buyer
Organizations (INDIVIDUAL|BUSINESS|ENTERPRISE), members + org roles (`shared.auth.OrgRole`), business units,
cost centers (quarterly budget), member spend limits (approval authority), procurement profile (business context).
- `POST /v1/buyers/register` → creates INDIVIDUAL org; caller gets all org roles. Events BUYER_REGISTERED, ORGANIZATION_CREATED, ORG_MEMBER_ADDED.
- `POST /v1/organizations` (BUSINESS/ENTERPRISE) → creator ORG_ADMIN+REQUESTER+APPROVER+BUDGET_OWNER.
- `GET /v1/organizations/{id}`, `GET /v1/organizations/mine`.
- `POST /v1/organizations/{id}/members` {email, roles[], spendLimit?} (ORG_ADMIN; identity.facade.find_by_email) ; `PATCH .../members/{identityId}` roles/spend limit ; `DELETE` member (cannot remove last ORG_ADMIN).
- `POST /v1/organizations/{id}/business-units`, `POST /v1/organizations/{id}/cost-centers`.
- Invariant: a member cannot approve spend beyond their spend limit (exposed via facade; policy enforces).

### firm
Firm registration (legal name, trading name, registration number, HQ country, size band), members (invite by email →
accept), roles FIRM_ADMIN/FIRM_MEMBER/AUTHORIZED_REPRESENTATIVE, firm verification (consumes VERIFICATION_COMPLETED with
subjectType FIRM and verificationType FIRM_REGISTRATION → FIRM_VERIFIED). Invariant: firm-level regulated offerings
require ≥1 verified authorized representative + verified firm.
- `POST /v1/firms`, `GET /v1/firms/{id}`, `POST /v1/firms/{id}/invitations` {email, roles}, `POST /v1/firm-invitations/{id}/accept`, `DELETE /v1/firms/{id}/members/{identityId}`.

### professional
Onboarding (wireframe "Professional Onboarding"): profile basics, specializations (1 primary + ≤5 secondary, taxonomy
only — marketplace.facade.validate_specializations), engagement preferences, pricing (indicative, not binding;
"Quote on request" allowed), availability/capacity, jurisdictions (served + licensed; cross-border requires
acknowledgement), credential claims (→ CREDENTIAL_SUBMITTED; verification opens a case), offerings (DRAFT/ACTIVE/PAUSED;
paused ≠ deleted), publishing.
- `POST /v1/professionals` (one per identity; optional firmId if caller is firm member) → PROFESSIONAL_REGISTERED.
- `GET /v1/professionals/me`, `PATCH /v1/professionals/me` (If-Match version), `PUT /v1/professionals/me/specializations`,
  `PUT /v1/professionals/me/jurisdictions`, `PUT /v1/professionals/me/availability` {availability, maxConcurrent, temporarilyUnavailable}.
- `POST /v1/professionals/me/credentials` (claim) → CREDENTIAL_SUBMITTED. `GET /v1/professionals/me/credentials`.
- Offerings: `POST/GET/PATCH /v1/professionals/me/offerings[/{id}]`, `POST .../{id}/activate|pause`.
- `POST /v1/professionals/me/publish` {attestAccurate:true}: requires email confirmed (identity.facade), ≥1 specialization,
  bio passes copy rules (no "best/leading/top/guarantee/#1" superlatives) → PROFILE_PUBLISHED. Tier C may publish (Discovery).
  `POST /v1/professionals/me/unpublish`.
- Public `GET /v1/professionals/{id}`: profile + trust snapshot (trust.facade) + verification checks (verification.facade);
  credentials displayed only if VERIFIED (else labelled "Self-reported"); FAILED claims hidden. Unpublished/suspended → 404 for public.
- Consumes: CONTRACT_ACTIVATED/COMPLETED/TERMINATED → active engagement count → availability AT_CAPACITY when count ≥ max (AVAILABILITY_UPDATED);
  ENFORCEMENT_ACTION_APPLIED/REVERSED (subjectType PROFESSIONAL: VISIBILITY_REDUCTION, ENGAGEMENT_SUSPENSION → PROFILE_SUSPENDED, OFFBOARD);
  VERIFICATION_COMPLETED/FAILED/EXPIRED/REVOKED for credentialClaimId → claim status.

### marketplace
Taxonomy (category → group → specialization; versioned; flags requiresCredential/regulated; deliverable templates;
credential hints). Seed **Finance & Accounting** with the 7 groups and all specializations from the category doc
(seed via `service.seed_default_taxonomy(session)` — idempotent; also callable by `POST /v1/admin/taxonomy/seed`).
- `GET /v1/taxonomy`, `GET /v1/taxonomy/{category}`; admin (PLATFORM_ADMIN) create/update/deprecate specialization → TAXONOMY_UPDATED.
- Saved professionals (`POST/DELETE/GET /v1/saved/professionals`), saved searches with alerts (`/v1/saved/searches`),
  comparison (`GET /v1/compare?ids=a,b,c` max 3: tier, dimensions, credentials, specializations, engagement types,
  delivery modes, availability, pricing model, governance signals — via facades).
- `POST /v1/listings/{professionalId}/view` → LISTING_VIEWED (analytics).

### search
Read-model projection `search.professional_documents` built ONLY from events (PROFILE_*, SERVICE_OFFERING_*,
AVAILABILITY_UPDATED, JURISDICTIONS_UPDATED, TRUST_SCORE_RECOMPUTED, TRUST_TIER_CHANGED, VERIFICATION_* for professionals,
ENFORCEMENT_*). On each event, rebuild the document via professional/trust/verification facades. Postgres full-text
(tsvector, weighted: name/headline A, specializations B, bio/offerings C). Vector retrieval = adapter interface (Wave 6).
- `GET /v1/search/professionals?q=&category=&spec=a,b&specMatch=any|all&tier=A,B&verified=identity,credentials&engagementType=&delivery=&availability=&pricingModel=&credential=&jurisdiction=&sort=best|verified|availability|experience|price_asc|price_desc|recent&limit=&offset=`
  → `{total, items[{professional summary, tier, score, whyThisResult[]}], facets{tier, specialization, delivery, pricingModel, engagementType, availability}}`.
- Ranking (Architecture 9.4): relevance 30, trust 20, contract success 15, reviews 10 (0 until reviews exist), availability 10,
  response 5, pricing fit 5, policy fit 5. Every result explains itself in plain language.
- Safety: never return unpublished/suspended profiles; if caller is in a buyer org apply `policy.facade.search_eligibility`
  (min tier, required dimensions, jurisdictions) — ineligible professionals are excluded.
- Emits SEARCH_PERFORMED, SEARCH_ZERO_RESULT. Implements `search.facade.count_eligible`.
- Admin `POST /v1/admin/search/reindex` rebuilds the projection.

### proposal
RequestForProposal: states DRAFT → OPEN → (PROPOSAL_RECEIVED) → CLOSED | DECLINED | CANCELLED.
Proposal: DRAFT → SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → (REVISED→SUBMITTED) → PENDING_APPROVAL → ACCEPTED | REJECTED | WITHDRAWN | EXPIRED.
- `POST /v1/proposal-requests` (buyer, Idempotency) {organizationId, professionalId, offeringId?, engagementType, objective≤300,
  details≤1200, desiredStartDate (not past), estimatedDuration, budget?, deliveryMode, ndaRequired, attachments[{name, sha256, size}]≤3, draft?}.
  Checks: actor REQUESTER in org; professional PUBLISHED; policy ENGAGEMENT_ELIGIBILITY (tier, jurisdiction) — BLOCK → 403 with reason.
- `GET /v1/proposal-requests?role=buyer|professional`, `GET /v1/proposal-requests/{id}` (NDA: professional sees details only after `POST .../accept-nda`).
- `POST /v1/proposal-requests/{id}/decline` (professional, structured reasonCode).
- `POST /v1/proposal-requests/{id}/proposals` (professional) → DRAFT {summary≤500, scopeAlignment, deliverables[], milestones[] (each maps to deliverables, amounts sum = total),
  pricingModel, total Money, startDate, endDate, assumptions[], exclusions[], validUntil}. `PATCH /v1/proposals/{id}` (DRAFT/REVISION_REQUESTED).
- `POST /v1/proposals/{id}/submit` (Idempotency): needs ≥1 deliverable and price; trust tier ≥ B (Tier C cannot submit);
  policy PROPOSAL_SUBMIT. Expiry timer at validUntil → EXPIRED.
- Buyer: `GET /v1/proposal-requests/{id}/proposals` (comparison with deltas vs request), `POST /v1/proposals/{id}/request-revision`
  {changes[{field, requested}]}, `POST /v1/proposals/{id}/reject` {reasonCode?}, `POST /v1/proposals/{id}/accept` (Idempotency, REQUESTER/APPROVER in org).
  Accept → policy PROPOSAL_ACCEPT with attributes (value, currency, tier, dims, jurisdictions, category, regulated, crossBorder).
  ALLOW → ACCEPTED + PROPOSAL_ACCEPTED (full terms snapshot + termsHash = sha256(canonical terms)).
  REQUIRE_APPROVAL → PENDING_APPROVAL (HTTP 202 with approvalRequestId); consume APPROVAL_GRANTED/DENIED (subjectType "Proposal", action PROPOSAL_ACCEPT).
  Expired proposals cannot be accepted. Accepting one proposal closes the request.

### contract
Contract: GENERATED → PENDING_SIGNATURE → ACTIVE → COMPLETED | TERMINATED; ACTIVE ⇄ DISPUTED.
Milestone: PENDING_FUNDING → IN_PROGRESS → SUBMITTED → (REVISION_REQUESTED → IN_PROGRESS) → ACCEPTANCE_PENDING_APPROVAL → ACCEPTED; any open → DISPUTED; → CANCELLED.
- Consume PROPOSAL_ACCEPTED → generate contract (idempotent per proposalId) from terms + platform template + policy required
  clauses (policy.facade.get_settings_for_org pinned to proposal's policyVersionId); render plain-text/HTML document stored
  with sha256 (Blob in prod). Status PENDING_SIGNATURE; signature deadline timer (settings.signature_deadline_days) →
  SIGNATURE_DEADLINE_ESCALATED.
- `GET /v1/contracts/{id}` (parties only, or operators), `GET /v1/contracts/{id}/document`.
- `POST /v1/contracts/{id}/sign` {termsHash} (Idempotency + **step-up**): buyer (org member REQUESTER/APPROVER) signs first,
  then professional. Signature rows append-only (signer, party, termsHash, authStrength, signedAt, ip). Both signed → ACTIVE
  + CONTRACT_ACTIVATED. termsHash mismatch → 409.
- Consume ESCROW_FUNDED → listed milestones PENDING_FUNDING → IN_PROGRESS (MILESTONE_STARTED). No work without funding.
- `POST /v1/milestones/{id}/submit` (professional) {note, deliverables[{name, sha256, size}]} → SUBMITTED; acceptance timer
  (acceptance_window_days; auto-accept only if auto_accept_after_days set, else reminder + escalation).
- `POST /v1/milestones/{id}/accept` (Idempotency; org REQUESTER/APPROVER; policy MILESTONE_ACCEPT) → ACCEPTED + MILESTONE_ACCEPTED.
  `POST /v1/milestones/{id}/request-revision` {reason}.
- All milestones ACCEPTED → CONTRACT_COMPLETED.
- Change orders: `POST /v1/contracts/{id}/change-orders` {type ADD_DELIVERABLE|MODIFY_DELIVERABLE|EXTEND_TIMELINE|PRICING_CHANGE, delta, impact};
  `POST /v1/change-orders/{id}/approve|reject` by the other party (+ policy CHANGE_ORDER_APPROVE). Approved material change
  (pricing/scope) → contract_version+1, new termsHash, re-signature required (status PENDING_SIGNATURE) then CONTRACT_AMENDED;
  non-material (timeline) → CONTRACT_AMENDED directly.
  Delta contracts: ADD_DELIVERABLE `{milestoneId, deliverable:{key,title,description?,acceptanceCriteria}}`;
  MODIFY_DELIVERABLE `{key, changes:{title?,description?,acceptanceCriteria?}}`;
  EXTEND_TIMELINE `{endDate, milestoneDueDates?:[{milestoneId,dueDate}]}`;
  PRICING_CHANGE `{totalDeltaMinor, milestoneAmounts:[{milestoneId,amountMinor}]}` where the amount deltas sum exactly
  to `totalDeltaMinor`. Only milestones still unfunded and not started may receive scope/price changes; escrow applies
  amended amounts only to UNFUNDED allocations and rejects any schedule that does not reconcile with its account total.
- Consume DISPUTE_INITIATED → milestones DISPUTED, contract DISPUTED (CONTRACT_DISPUTED). Consume DISPUTE_RESOLVED →
  milestoneOutcome ACCEPT → ACCEPTED, CANCEL → CANCELLED, REWORK/EXTEND → IN_PROGRESS; contract back to ACTIVE when no
  open disputes (CONTRACT_DISPUTE_CLEARED). Disputed contracts cannot be terminated unilaterally.
- `POST /v1/contracts/{id}/terminate` {reason, mutual: bool}: unilateral only when no disputes and no funded-unreleased milestones.
- `GET /v1/contracts/{id}/workspace`: overview, milestones, escrow summary (escrow.facade), activity timeline (audit.facade).

### escrow (financial — strictest rules)
EscrowAccount per contract; MilestoneAllocation per milestone; FundingRequest; Hold; Release; Refund;
**LedgerEntry append-only double-entry** (`escrow.ledger_entries`): entry_group_id, entry_type
(BUYER_FUNDING|ESCROW_HOLD|ESCROW_RELEASE|PLATFORM_FEE|REFUND|PAYOUT|CHARGEBACK), account
(BUYER_CLEARING / ESCROW_HELD / PRO_PAYABLE / PLATFORM_REVENUE / BUYER_REFUND_PAYABLE), debit_minor, credit_minor, currency.
Every group balances (Σdebit = Σcredit) — assert before insert. Balances on account are updated in the same transaction.
Row locks (`with_for_update`) on account for every money movement.
- Consume CONTRACT_ACTIVATED → open account (idempotent per contract) → ESCROW_OPENED. Consume CONTRACT_AMENDED → adjust unfunded allocations.
- `POST /v1/escrow/{id}/fund` (buyer org REQUESTER/APPROVER/BUDGET_OWNER; Idempotency) {milestoneIds[] | all, paymentMethodToken}
  → policy ESCROW_FUND → allocations FUNDING → ESCROW_FUNDING_REQUESTED. Over-funding rejected.
- Consume PAYMENT_CAPTURED → ledger BUYER_FUNDING/ESCROW_HOLD → allocations HELD → ESCROW_FUNDED. PAYMENT_FAILED → back to UNFUNDED.
- Consume MILESTONE_ACCEPTED → **release decision tree** (Handbook 15.2): milestone accepted? active dispute hold? already
  released (idempotent → no-op)? policy ESCROW_RELEASE (REQUIRE_APPROVAL → RELEASE_PENDING_APPROVAL + ESCROW_RELEASE_PENDING_APPROVAL,
  finish on APPROVAL_GRANTED)? payout account valid (payments.facade; if not, still release to PRO_PAYABLE and payments queues
  payout)? → ledger ESCROW_RELEASE + PLATFORM_FEE (settings.platform_fee_bps from config) → ESCROW_RELEASED {gross, fee, net}.
- Consume DISPUTE_INITIATED → hold affected allocations (ON_HOLD) → ESCROW_HOLD_APPLIED. While held, NO release path may run.
- Consume DISPUTE_RESOLVED → execute allocations (release part → ESCROW_RELEASED, refund part → ESCROW_REFUNDED),
  lift hold → ESCROW_HOLD_RELEASED, ESCROW_RESOLUTION_EXECUTED. Amount checks: release+refund ≤ held.
- Consume CONTRACT_TERMINATED → refund unreleased funded allocations.
- `GET /v1/escrow/{id}`, `GET /v1/escrow/by-contract/{contractId}`, `GET /v1/escrow/{id}/ledger` (parties; ledger view).
- No HTTP endpoint releases money directly. Operators cannot mutate balances.

### payments (financial)
Provider adapter interface `PaymentProvider` (charge(token, amount) → providerRef | failure; payout(account, amount);
refund(providerRef, amount); verify_webhook(sig, body)). `FakeProvider`: succeeds unless token == "tok_fail" / account "acct_fail".
No raw card data, ever — tokens only.
- Consume ESCROW_FUNDING_REQUESTED → PaymentIntent (CREATED → CAPTURED|FAILED), provider charge, emit PAYMENT_CAPTURED / PAYMENT_FAILED. Idempotent per fundingId.
- Consume ESCROW_RELEASED → Payout (INITIATED → SETTLED|FAILED) using professional's payout account (if none → QUEUED until
  account added); invoice/receipt for buyer (INVOICE_ISSUED; sequential invoice numbers; line items gross/fee/net; tax via
  `TaxCalculator` interface returning 0 by default).
- Consume ESCROW_REFUNDED → provider refund → REFUND_SETTLED.
- `POST /v1/payout-accounts` (professional; **step-up**; requires trust tier ≥ B and restrictions CLEAR = compliance checks),
  `GET /v1/payout-accounts/me`. `GET /v1/payments/payouts/me`, `GET /v1/payments/invoices?organizationId=`, receipts.
- `POST /v1/payments/webhooks/{provider}`: HMAC-SHA256 signature (config.webhook_secret) + dedupe by provider event id.
- Daily reconciliation timer: compare escrow.facade.ledger_totals vs captured/payout/refund totals → RECONCILIATION_COMPLETED or RECONCILIATION_MISMATCH.
- `CHARGEBACK_RECEIVED` via webhook.

### verification
VerificationCase (types IDENTITY|CREDENTIAL|JURISDICTION|RESTRICTIONS|BACKGROUND|INSURANCE|FIRM_REGISTRATION) with states
PENDING → IN_REVIEW → NEEDS_INFO → VERIFIED | FAILED; VERIFIED → EXPIRED | REVOKED. Evidence items append-only (sha256,
type, uploadedBy, storage key — file bytes go to blob storage; store only metadata + hash here). Provider adapter
(`VerificationProvider`, `FakeProvider` returns PASS/REVIEW deterministically). **Verified status requires positive provider
result or approved human review** — AI never approves.
- `POST /v1/verification/cases` {verificationType, subjectType, subjectId, details} (subject owner), `POST /v1/verification/cases/{id}/evidence`.
- Consume CREDENTIAL_SUBMITTED → open CREDENTIAL case. Consume PROFESSIONAL_REGISTERED → open RESTRICTIONS (sanctions screening) case via provider.
- Review queue (COMPLIANCE_OFFICER, **step-up**): `GET /v1/verification/review-queue`, `POST /v1/verification/cases/{id}/decision`
  {decision VERIFIED|FAILED|NEEDS_INFO, reasonCode, publicReason, expiresAt?}; reviewer cannot review their own case. `POST .../revoke`.
- Expiry timers at expiresAt-30/14/7 days → VERIFICATION_EXPIRING; at expiresAt → VERIFICATION_EXPIRED.
- SLA visibility: case shows `estimatedCompletion` (identity 24h, credential 48h median).
- Implements verification.facade.get_checks. Subject view `GET /v1/verification/subjects/{type}/{id}` (owner or operator).

### trust
TrustProfile per professional; TrustSignal (source event, type, weight, decays); TrustScoreSnapshot; TierHistory; RiskFlag.
Deterministic, explainable rules (Trust charter + onboarding doc):
- Tier C: default (Discovery).
- Tier B: identity VERIFIED and restrictions not FLAGGED and no active ENGAGEMENT_SUSPENSION.
- Tier A: Tier B + credentials VALIDATED for every specialization flagged requiresCredential (marketplace.facade) +
  jurisdiction ELIGIBLE (licensed jurisdiction verified) + restrictions CLEAR + insurance VERIFIED if any of their
  specializations is `regulated` and requires it.
- Adverse signals (expiry, revocation, failed check, enforcement, dispute lost) → immediate recompute & downgrade.
  Upgrades need the conditions to hold (hysteresis: score-based demotion only when score < threshold − 5).
- Score 0–100: verification depth 40, completed contracts 25 (recency-weighted), on-time delivery 10, dispute outcomes 15,
  responsiveness 10. Explanation strings for each component.
- Consumes: PROFESSIONAL_REGISTERED, VERIFICATION_COMPLETED/FAILED/EXPIRED/REVOKED, JURISDICTIONS_UPDATED, MILESTONE_ACCEPTED,
  CONTRACT_COMPLETED, DISPUTE_RESOLVED, ENFORCEMENT_ACTION_APPLIED/REVERSED, RISK_FLAG_RAISED (flag only — never tier change by AI).
- Emits TRUST_SIGNAL_ADDED, TRUST_SCORE_RECOMPUTED, TRUST_TIER_CHANGED, TRUST_PROFILE_FLAGGED. Adverse recompute < 5s (synchronous in consumer).
- `GET /v1/trust/professionals/{id}` (public: tier, dimensions, explanation, updatedAt), `GET .../history` (owner/operator).

### policy
PolicyProfile (org-scoped, versioned: PolicyVersion immutable once ACTIVE; DRAFT editable), templates REGULATED,
ENTERPRISE_STANDARD, CROSS_BORDER, GROWTH_ADVISORY (Enterprise Policy doc §4) + platform baseline (always applied).
Structured settings (ProfileSettings) + custom rules JSON:
`{"id","appliesTo":[actions],"condition":{"all"|"any":[...]} | {"field","op":EQ|NEQ|GT|GTE|LT|LTE|IN|NOT_IN|CONTAINS|EXISTS,"value"},
"decision":"BLOCK|REQUIRE_APPROVAL|REQUIRE_EXCEPTION","reasonCode","message","approval":{"type":"SINGLE|SEQUENTIAL|PARALLEL","steps":[{"role":OrgRole,"count":1}],"timeoutHours":48,"escalationRole":OrgRole}}`.
Settings compile into rules (e.g. min tier → BLOCK on ENGAGEMENT_ELIGIBILITY/PROPOSAL_SUBMIT/PROPOSAL_ACCEPT when tier rank lower;
allowed currencies; jurisdictions). Platform baseline: Tier C cannot PROPOSAL_SUBMIT / be accepted; restricted professionals BLOCK.
Most restrictive wins. Every evaluation persisted (`policy.policy_evaluations`, append-only) + POLICY_EVALUATED.
- Approvals: ApprovalRequest + steps + decisions. Approver must hold the step's org role, not be the requester (role separation),
  and have spend limit ≥ amount (buyer.facade). Sequential: steps in order; parallel: all; single: one. Timeout timer → escalate (APPROVAL_ESCALATED).
  `GET /v1/approvals?organizationId=&status=`, `POST /v1/approvals/{id}/decide` {decision GRANT|DENY, reason} (step-up when settings.step_up_for_approvals).
- Exceptions: `POST /v1/policy-exceptions` {orgId, subjectType, subjectId, action, justification, documents[], expiresAt}; decided by EXCEPTION_AUTHORITY;
  auto-expire timer (EXCEPTION_EXPIRED). Granted & unexpired → that subject/action passes REQUIRE_EXCEPTION rules.
- Profiles: `POST /v1/policy-profiles` {orgId, name, template?, settings, rules, businessUnitIds?, riskLevel}, `PATCH` (DRAFT only),
  `POST /v1/policy-profiles/{id}/activate` (ORG_ADMIN + step-up; validates impossible combos) → POLICY_VERSION_ACTIVATED,
  `GET /v1/policy-profiles?orgId=`, `GET /v1/policy-profiles/{id}/impact` (search.facade.count_eligible),
  `POST /v1/policies/evaluate` (dry-run; no approval created).
- Version pinning: evaluate with `pinned_policy_version_id` uses that version (engagements keep their version mid-flight).

### dispute
DisputeCase: INITIATED → EVIDENCE_COLLECTION → DIRECT_RESOLUTION → MEDIATION → (ESCALATED) → DECIDED → ENFORCED → CLOSED; APPEALED.
Categories: SCOPE_DELIVERABLES, QUALITY_ACCEPTANCE, TIMELINE_DELAY, PAYMENT_RELEASE, PROFESSIONAL_CONDUCT, COMPLIANCE_BREACH,
JURISDICTION_LEGAL (immutable after submission; conduct/compliance skip direct resolution). Desired outcomes: REWORK,
PARTIAL_RELEASE, FULL_RELEASE, PARTIAL_REFUND, FULL_REFUND, TIMELINE_EXTENSION, TERMINATION.
- `POST /v1/disputes` (Idempotency; party to contract) {contractId, milestoneIds[], category, summary≤300, desiredOutcome, context≤1000}.
  Guardrails: no duplicate open dispute for the same milestone; accepted milestones only within challenge window.
  → DISPUTE_INITIATED (escrow freezes funds), evidence window timer (dispute_evidence_days) → DIRECT_RESOLUTION.
- Evidence: `POST /v1/disputes/{id}/evidence` {type, description, items[{name, sha256, size}]} (append-only, versioned; deadline enforced);
  import messaging thread via messaging.facade.export_thread.
- Direct resolution: `POST /v1/disputes/{id}/resolution-proposals` {outcome, allocations[{milestoneId, releaseMinor, refundMinor}]},
  `POST /v1/resolution-proposals/{id}/accept` by the other party → DISPUTE_RESOLUTION_AGREED → decision.
  Window timer (business days) → MEDIATION automatically; `POST /v1/disputes/{id}/escalate` once eligible.
- Mediation: MEDIATOR assigned (`POST /v1/disputes/{id}/assign-mediator`, operator); mediator `POST .../recommendation`; parties accept → decision.
  Platform decision (`POST /v1/disputes/{id}/decision`) needs MEDIATOR + a second approver with LEGAL (no single role initiates and finalizes).
  AI may summarise evidence (advisory, logged); never decides.
- Decision package: plainSummary, outcome, evidence references, policy citations, appeal eligibility → DISPUTE_RESOLVED.
- Consume ESCROW_RESOLUTION_EXECUTED → ENFORCED → seal (CLOSED) → DISPUTE_CLOSED. Appeals: `POST /v1/disputes/{id}/appeal` (once, independent reviewer).
- `GET /v1/disputes/{id}` with timeline; `GET /v1/disputes?contractId=`.

### messaging
Threads bound to a context (PROPOSAL_REQUEST | CONTRACT | DISPUTE); participants; messages immutable (append-only, content
sha256); attachments metadata (sha256); system messages for lifecycle events.
- Consume PROPOSAL_REQUESTED → create request thread (buyer requester + professional). CONTRACT_ACTIVATED → engagement thread.
  DISPUTE_INITIATED → lock engagement thread (THREAD_LOCKED; "no direct messaging during disputes") + create dispute thread
  (platform-bound, structured). DISPUTE_CLOSED → unlock.
- `GET /v1/threads?contextType=&contextId=`, `GET /v1/threads/{id}/messages` (cursor), `POST /v1/threads/{id}/messages` {body≤5000, attachments[]}.
- Abuse/off-platform detection (emails/phone numbers/payment links, harassment keywords) → MESSAGE_FLAGGED (message still stored; flagged for T&S).

### notification
In-app notifications + email (provider adapter; `ConsoleEmailProvider`) + enterprise webhooks.
- Consumes the lifecycle events listed in the RFP wireframe §17 (request sent, proposal received, revision requested, agreement
  ready for signature, countersigned, payment funded, milestone submitted/approved/revision, engagement completed, dispute
  opened/updated/closed) plus verification status, credential expiry reminders (VERIFICATION_EXPIRING), approvals required,
  security (AUTHENTICATION_FAILED lockouts, new MFA) and enforcement notices (must render all 6 notice fields).
  Recipient resolution via buyer.facade.list_member_identities / professional.facade.get_professional(...).identity_id / payload ids.
- Preferences per identity (channel opt-in; security + enforcement notices are mandatory).
- `GET /v1/notifications` (cursor), `POST /v1/notifications/{id}/read`, `GET/PUT /v1/notification-preferences`.
- Webhooks: `POST /v1/webhook-endpoints` {organizationId, url, eventTypes[]} (ORG_ADMIN) → secret returned once;
  deliveries HMAC-SHA256 signed (`X-Zoikorum-Signature`), retried with exponential backoff for 24h via timers, delivery log kept
  ≥90 days; `POST /v1/webhook-endpoints/{id}/test`, `POST /v1/webhook-deliveries/{id}/replay`.

### ai
Prompt registry (promptKey, version, owner, targetModel, status DRAFT|APPROVED|RETIRED, approvedBy AI_SAFETY_REVIEWER,
goldenTests JSON), inference log (prompt version, model, input sha256, output, purpose, subject, latency, fallbackUsed).
Provider adapter `LLMProvider` with `OfflineProvider` (deterministic keyword-based) as default and `AnthropicProvider`
(Claude via the official `anthropic` SDK, model from config, used only when ZK_AI_PROVIDER=anthropic and key present).
No production inference with an unregistered/unapproved prompt.
- `extract_match_intent` (facade) — buyer need → taxonomy specializations + engagement type (fallback: keyword match on taxonomy names).
- `POST /v1/ai/proposal-draft` {requestId} (professional on that request) → draft text; professional must still submit.
- `POST /v1/ai/contract-summary` {contractId} (party) → summary + mandatory disclaimer + document hash.
- `POST /v1/ai/dispute-summary` {disputeId} (MEDIATOR) → advisory summary; logged with prompt/model version.
- Risk detection consumer (e.g. many failed logins, rapid disputes, flagged messages) → RISK_FLAG_RAISED with reason codes (never enforcement).
- Prompt admin: `POST /v1/ai/prompts`, `POST /v1/ai/prompts/{id}/approve` (AI_SAFETY_REVIEWER, step-up) → PROMPT_VERSION_ACTIVATED.

### admin (Trust & Safety enforcement + operator tools)
EnforcementCase per Internal Governance Playbook: signal → evidence → level (0–4) → user impact → notice (6 fields) →
action → audit → review window. Levels: 0 informational, 1 warning, 2 temporary restriction (VISIBILITY_REDUCTION), 3
ENGAGEMENT_SUSPENSION / CREDENTIAL_ENFORCEMENT / VERIFICATION_RESET, 4 SUSPEND_ACCOUNT / OFFBOARD (EXECUTIVE + LEGAL approval).
- Roles: TS_ANALYST opens/assesses, RISK_LEAD assigns level, action approved by a different operator than the one who proposed it.
  Step-up for applying actions. Prohibited: silent penalties (notice required), unexplained removals.
- `POST /v1/admin/enforcement-cases` {subjectType, subjectId, signalSource, summary, evidenceRefs[]},
  `POST .../{id}/assess` {level, reasonCode}, `POST .../{id}/propose-action` {action, notice{6 fields}, durationDays?},
  `POST .../{id}/approve-action` → ENFORCEMENT_ACTION_APPLIED, `POST .../{id}/reverse`, appeals
  `POST /v1/enforcement-cases/{id}/appeal` (subject; level ≥2) decided by an independent reviewer → ENFORCEMENT_APPEAL_DECIDED (+ reversal if upheld).
- Consume RISK_FLAG_RAISED, MESSAGE_FLAGGED, TRUST_PROFILE_FLAGGED → open Level-0 triage case.
- Dead-letter ops: `GET /v1/admin/dead-letters`, `POST /v1/admin/dead-letters/{id}/replay` (financial requires FINANCIAL_OPS + step-up) — uses shared.relay.
- Implements admin.facade.active_restrictions (time-bound actions expire via timers).

### analytics
Rebuildable read projections from events only (CQRS, Handbook ch. 5):
- `analytics.buyer_dashboard` per org: activeEngagements, pendingActions (proposals awaiting response, contracts awaiting
  signature, milestones awaiting approval, approvals pending), openProposals, fundsInProtectionMinor (by currency), savedProfessionals.
- `analytics.professional_dashboard` per professional: activeEngagements, newRequests, pendingActions, upcomingMilestones,
  earningsThisMonthMinor, pendingReleaseMinor, lifetimeEarningsMinor, verificationStatus/tier.
- `analytics.marketplace_daily` (operators): searches, zero results, proposal→contract conversion, activations, disputes opened/resolved,
  median release latency, trust tier distribution.
- `GET /v1/dashboards/buyer?organizationId=` (org member), `GET /v1/dashboards/professional` (self),
  `GET /v1/analytics/marketplace-health?from&to` (operators), `POST /v1/admin/analytics/rebuild` (replays audit ledger).
- Each projection row stores `lastEventAt` so UIs can show staleness.
