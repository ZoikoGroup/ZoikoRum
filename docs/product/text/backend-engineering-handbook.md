<!-- Generated from backend-engineering-handbook.docx — edit the .docx, not this file. -->

# Backend Engineering Handbook

# ZOIKORUM™ Backend Engineering Handbook

A Practical Build Tutorial for a Young Tactile Engineering Team

Office of the CTO

2026

Table of Contents

# 1 ZOIKORUM™ Backend Engineering Handbook

## 1.1 A Practical Build Tutorial for a Young Tactile Engineering Team

Document Classification: Internal - Engineering Tutorial
Standard: Tier-0 Marketplace Engineering · Fortune 10 Quality
Audience: Young engineers, technical leads, QA engineers, TPMs, business analysts, solution architects
Prerequisite: Basic knowledge of REST APIs, databases, Git, and at least one backend language
Purpose: Teach the team what to build, why it exists, how the pieces connect, how to test it, and which engineering mistakes must never happen.

Read this before writing code.
Every Zoikorum engineer must be able to answer five questions about any feature:
1. Which domain owns this?
2. What command causes it?
3. What state machine does it advance?
4. What event does it publish when successful?
5. What audit record proves it happened?

If the answer is unclear, stop. Do not build unclear governance.

# 2 How to Use This Handbook

This is not a blog post. It is a practical engineering tutorial.

It is written for a tactile team - engineers who learn by seeing the shape of the system, reading examples, building vertical slices, testing failures, and repeating patterns.

Use it in four ways:

- Before build: read the relevant chapter before starting a feature.

- During build: copy the patterns - state machines, event envelopes, idempotency, policy evaluation, and tests.

- During review: use the checklists to reject incomplete work.

- During onboarding: make every new engineer walk through the platform spine.

The handbook is organized from mindset to build execution:

- Part I - What Zoikorum actually is

- Part II - Domain architecture and DDD

- Part III - Events, state machines, workflows, policy, and audit

- Part IV - Search, AI, payments, disputes, and enterprise marketplace systems

- Part V - Security, databases, APIs, distributed systems, cloud, reliability, and production

- Part VI - Build order, testing, code structure, quality standards, and engineering culture

# 3 Part I - The Engineering Mindset

# 4 Chapter 1 - What Zoikorum Actually Is

## 4.1 1.1 Not a Website. Not a Gig App. Trust Infrastructure.

Zoikorum is a global marketplace for governed professional services.

That means:

- buyers find professionals and firms;

- professionals and firms publish structured service offerings;

- proposals become contracts;

- contracts have milestones and acceptance criteria;

- funds are protected and released only when conditions are met;

- disputes are handled with structured evidence;

- trust is based on verification, not popularity alone;

- every important action is auditable.

The backend is not merely storing users, profiles, and messages.

The backend is enforcing trust.

That is the central mindset.

## 4.2 1.2 Why Zoikorum Is Different

| Dimension | Consumer Freelance Platform | Zoikorum |
|---|---|---|
| Primary buyer | Individual or small business | Individuals, businesses, firms, and enterprise procurement teams |
| Service type | Gigs, tasks, simple projects | Professional engagements, advisory, retainers, fractional, SOWs |
| Trust model | Reviews and self-reported credentials | Identity verification, credential validation, jurisdiction eligibility, trust tiers |
| Contract model | Basic terms or platform template | Contract-first engagement with scope, milestones, acceptance, amendments |
| Payment model | Basic escrow or direct payout | Governed payment protection, milestone release conditions, holds, reconciliation |
| Dispute model | Support ticket or platform arbitration | Structured evidence, mediation, escalation, enforceable outcomes |
| Enterprise readiness | Often bolted on later | Native: SSO, SCIM, policy profiles, approval chains, audit exports |
| Governance | Reactive | Preventive, configurable, explainable, auditable |

Every line in this table creates backend requirements.

## 4.3 1.3 The Platform Spine

The most important end-to-end flow is:

Buyer finds professional
  -> Buyer initiates proposal request
    -> Professional submits proposal
      -> Buyer accepts proposal
        -> Policy evaluation happens
          -> Contract is generated
            -> Both parties sign contract
              -> Escrow is funded
                -> Professional delivers milestone
                  -> Buyer accepts milestone
                    -> Funds are released
                      -> Audit records are written
                        -> Trust score is updated
                          -> Professional is re-indexed in search

If the team can build this correctly, the team understands Zoikorum.

Everything else is a variation: enterprise approval, cross-border rules, retainer cycles, disputes, credential expiry, offboarding, and reporting.

## 4.4 1.4 Build Doctrine

The team’s job is not to build screens.

The team’s job is to build trust infrastructure disguised as a world-class marketplace.

Zoikorum must be:

- searched like Google;

- governed like enterprise procurement;

- protected like financial infrastructure;

- audited like a regulated system;

- experienced like a modern marketplace.

# 5 Chapter 2 - The Ten Questions Before Code

Before writing code for any feature, answer these questions.

| # | Question | Why It Matters |
|---|---|---|
| 1 | Which domain owns this data? | Determines where the code lives and who may write to the data |
| 2 | Which command causes it? | Defines actor, authority, validation, and failure conditions |
| 3 | What state machine does it advance? | Prevents invalid lifecycle transitions |
| 4 | What event is published on success? | Enables downstream systems to react without coupling |
| 5 | Who consumes that event? | Reveals downstream consequences and required tests |
| 6 | What policy applies? | Ensures enterprise and jurisdiction rules are enforced |
| 7 | What audit record is written? | Makes the action defensible to Legal, Finance, and Compliance |
| 8 | What happens if it fails halfway through? | Forces rollback, compensation, retry, or workflow design |
| 9 | Can it run twice safely? | Determines idempotency requirements |
| 10 | Can you explain it to a buyer, CFO, and General Counsel? | If not, the design is probably unclear or unsafe |

If one answer is missing, do not build yet.

# 6 Part II - Domain Architecture and DDD

# 7 Chapter 3 - Think in Domains, Not Pages

## 7.1 3.1 The Common Beginner Mistake

A beginner thinks:

We need a profile page.
We need a proposal page.
We need a payment page.

A Zoikorum engineer thinks:

Which domain owns this action?
What aggregate changes state?
Which event is published?
Which policies are evaluated?
What audit record is written?

Pages are user interface surfaces. Domains are business ownership boundaries.

## 7.2 3.2 Core Domains

| Domain | Owns | Never Owns |
|---|---|---|
| Identity | Users, login, MFA, sessions, SSO | Professional profile content, payments |
| Professional | Professional profiles, service offerings, availability, pricing | Contracts, escrow, payments |
| Buyer | Buyer organizations, teams, procurement context | Professional credentials, escrow |
| Firm | Firm profiles, members, firm offerings | Individual identity verification decisions |
| Marketplace | Discovery, listings, matching, ranking | Payment processing |
| Proposal | Request, proposal, negotiation, acceptance, expiry | Contract PDFs, escrow releases |
| Contract | Contracts, milestones, deliverables, amendments, signatures | Payment provider calls |
| Escrow | Holds, release conditions, refunds, escrow ledger | Contract generation |
| Payments | Charges, payouts, invoices, tax, provider webhooks | Contract legal terms |
| Verification | Identity, credential, license, insurance, background cases | Trust score computation |
| Trust | Trust signals, score, tiers, risk flags | Source verification evidence |
| Policy | Rules, approvals, exceptions, restrictions | Money movement |
| Dispute | Evidence, mediation, escalation, resolution | Escrow mechanics |
| Audit | Immutable records and exports | Business decision ownership |
| Search | Indexes, facets, ranking output | Source-of-truth profile data |
| Messaging | Engagement-bound communication | Contract terms |
| Notification | Email, in-app, push, webhooks | Business logic |
| AI | Assistance, summaries, risk suggestions | Final decisions |
| Security | Threat detection, fraud, access anomalies | Marketplace ranking decisions |

## 7.3 3.3 Domain Rules

Rule 1: A domain owns its data exclusively.

Forbidden:

-- Proposal service reading Contract database directly
SELECT * FROM contract_db.contracts WHERE buyer_id = $1;

Correct:

Proposal service calls Contract API for authoritative data;
or subscribes to ContractActivated events and maintains a local projection.

Rule 2: Domains publish events, not side effects.

When something important happens, the domain publishes a fact. Other domains subscribe and react.

Rule 3: Domain boundaries are business boundaries.

Do not merge domains because it feels simpler this month. Proposal and Contract are separate because they have different lifecycles, authority rules, audit needs, and future teams.

# 8 Chapter 4 - Domain-Driven Design for Zoikorum

## 8.1 4.1 The DDD Building Blocks

| DDD Term | Plain Meaning | Zoikorum Example |
|---|---|---|
| Bounded Context | A business boundary with its own language and model | Proposal, Contract, Escrow |
| Aggregate Root | The main object through which changes happen | Proposal, Contract, EscrowAccount |
| Entity | Object with identity and lifecycle | Milestone, Deliverable, VerificationCase |
| Value Object | Object defined by its values, not identity | Money, EmailAddress, TrustScore |
| Domain Event | Fact that happened in the domain | ProposalAccepted, EscrowFunded |
| Repository | Persistence interface for aggregates | ProposalRepository |
| Domain Service | Domain logic not naturally owned by one entity | TrustScoreCalculator |
| Factory | Creates valid domain objects | ContractFactory |
| Specification | Encapsulates a business rule | ProfessionalEligibleForEngagementSpec |
| Anti-Corruption Layer | Protects your domain from external models | PaymentProviderAdapter |

## 8.2 4.2 Aggregate Example: Proposal

A Proposal is not just a database row. It is an aggregate root that protects its lifecycle.

class Proposal {
  constructor(
    private id: ProposalId,
    private status: ProposalStatus,
    private terms: ProposalTerm[],
    private expiresAt: Date,
    private domainEvents: DomainEvent[] = []
  ) {}

  accept(actor: Actor, policyDecision: PolicyDecision): void {
    if (!actor.canAcceptProposal(this.id)) {
      throw new AuthorizationError('Actor cannot accept this proposal');
    }

    if (this.isExpired()) {
      throw new ProposalExpiredError(this.id);
    }

    if (!['SUBMITTED', 'UNDER_REVIEW', 'NEGOTIATING'].includes(this.status)) {
      throw new InvalidStateTransitionError(this.status, 'ACCEPTED');
    }

    if (policyDecision.type === 'BLOCK') {
      throw new PolicyBlockedError(policyDecision.reasonCode);
    }

    if (policyDecision.type === 'REQUIRE_APPROVAL') {
      throw new ApprovalRequiredError(policyDecision.approvalRouteId);
    }

    this.status = 'ACCEPTED';
    this.domainEvents.push(new ProposalAccepted({
      proposalId: this.id.value,
      acceptedBy: actor.identityId,
      acceptedAt: new Date().toISOString()
    }));
  }
}

The aggregate owns the invariant. The controller does not.

## 8.3 4.3 Value Object Example: Money

Never represent money as a floating point number.

Wrong:

const amount = 99.99;

Correct:

class Money {
  constructor(
    public readonly minorUnits: bigint, // cents, pence, etc.
    public readonly currency: Currency
  ) {
    if (minorUnits < 0n) throw new Error('Money cannot be negative');
  }

  add(other: Money): Money {
    if (this.currency !== other.currency) {
      throw new Error('Cannot add different currencies');
    }
    return new Money(this.minorUnits + other.minorUnits, this.currency);
  }
}

Money errors become financial incidents. Treat money as a first-class value object.

## 8.4 4.4 Specification Example

Use specifications for reusable business rules.

class ProfessionalEligibleForEngagementSpec {
  constructor(private policy: PolicyProfile) {}

  isSatisfiedBy(professional: Professional): boolean {
    return professional.trustTier >= this.policy.minimumTrustTier
      && professional.hasRequiredCredentials(this.policy.requiredCredentials)
      && professional.isEligibleIn(this.policy.jurisdiction)
      && !professional.hasActiveRestriction();
  }
}

This keeps business rules understandable and testable.

# 9 Chapter 5 - CQRS and Read Models

## 9.1 5.1 Why CQRS Matters

Commands and queries have different needs.

Commands protect correctness:

AcceptProposal
FundEscrow
OpenDispute

Queries optimize reading:

Show buyer dashboard
Show search results
Show contract timeline

Trying to use the same model for both creates slow queries and fragile business logic.

## 9.2 5.2 Command Model vs Query Model

| Model | Purpose | Optimized For |
|---|---|---|
| Command Model | Change state safely | Correctness, invariants, transactions |
| Query Model | Read state quickly | Speed, shape of UI, aggregation |

Example: Buyer Dashboard needs one screen showing active engagements, pending proposals, funds held, milestones waiting for review, and disputes. That information lives in several domains. Do not make the dashboard query every service live on each page load. Build a projection.

## 9.3 5.3 Projection Example

Events:
ProposalSubmitted
ProposalAccepted
ContractActivated
EscrowFunded
MilestoneDelivered
DisputeInitiated

Projection:
buyer_dashboard_summary
- buyer_id
- active_contracts_count
- pending_reviews_count
- funds_held_minor_units
- open_disputes_count
- last_updated_at

The projection is not the source of truth. It is a read-optimized view that can be rebuilt from events.

## 9.4 5.4 Projection Rules

- Projections may be eventually consistent.

- Projections must be rebuildable.

- Projection lag must be observable.

- Projection failures go to DLQ.

- UI should show staleness where it matters.

# 10 Chapter 6 - Event Sourcing: When and When Not to Use It

## 10.1 6.1 What Event Sourcing Means

Event sourcing stores the sequence of events as the source of truth, then rebuilds current state by replaying them.

Example:

ProposalDrafted
ProposalSubmitted
ProposalRevised
ProposalAccepted

Current status = Accepted, but the event history explains how it got there.

## 10.2 6.2 Where Zoikorum Should Use Event Sourcing Strongly

Use event sourcing or event-log reconstruction for:

- Audit ledger;

- policy evaluations;

- payment and escrow ledger;

- dispute lifecycle;

- contract amendments;

- trust signal history.

## 10.3 6.3 Where Not to Use Event Sourcing Initially

Do not force event sourcing everywhere at MVP stage.

For professional profile editing, standard relational persistence plus domain events is enough.

Bad over-engineering:

ProfileNameChanged
ProfileBioChanged
ProfilePhotoChanged
ProfileHeadlineChanged

This adds complexity without sufficient benefit early on.

## 10.4 6.4 Snapshotting

Long event streams need snapshots.

Replay 15,000 escrow ledger events every time? Bad.
Store periodic balance snapshot + replay events after snapshot. Good.

Snapshot rule:

- Use snapshots for high-volume aggregates.

- Snapshots are derived, not authoritative.

- Snapshot creation must be auditable for financial aggregates.

# 11 Part III - Events, Workflows, Policy and Audit

# 12 Chapter 7 - Events: The Communication Fabric

## 12.1 7.1 Why Events

When a buyer accepts a proposal, five things must happen:

- Contract generation.

- Policy evaluation.

- Workflow orchestration.

- Notifications.

- Audit record creation.

Do not call all of these directly from Proposal Service.

Bad:

await contractService.generate(proposalId);
await policyService.evaluate(proposalId);
await notificationService.notify(proposalId);
await auditService.write(proposalId);

Good:

await eventBus.publish(new ProposalAccepted({ proposalId }));

Subscribers react independently.

## 12.2 7.2 Command vs Event

| Type | Meaning | Can Fail? | Naming |
|---|---|---|---|
| Command | Request to do something | Yes | SubmitProposal, AcceptProposal |
| Event | Fact that already happened | No | ProposalSubmitted, ProposalAccepted |

Wrong event name:

AcceptProposalEvent

Correct:

ProposalAccepted

## 12.3 7.3 Event Envelope Standard

{
  "eventId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "eventType": "zoikorum.proposal.proposal.accepted.v1",
  "occurredAt": "2026-01-22T10:44:00.000Z",
  "producedBy": "proposal-service",
  "correlationId": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "causationId": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "aggregateType": "Proposal",
  "aggregateId": "proposal_abc123",
  "schemaVersion": "1",
  "tenantId": "org_acme",
  "payload": {
    "proposalId": "proposal_abc123",
    "buyerId": "buyer_xyz",
    "professionalId": "pro_456",
    "acceptedAt": "2026-01-22T10:44:00.000Z"
  }
}

## 12.4 7.4 Six Critical Event Flows

### 12.4.1 Flow 1 - Proposal to Contract

ProposalAccepted
  -> Contract Service generates contract
  -> Policy Service evaluates rules
  -> Workflow Engine starts contract execution
  -> Notification Service alerts parties
  -> Audit Service records acceptance

ContractGenerated
  -> Signature workflow starts

ContractSigned by both parties
  -> ContractActivated
  -> Escrow Service opens escrow account
  -> Payments Service requests funding
  -> Audit Service records activation

### 12.4.2 Flow 2 - Milestone Delivery and Payment

MilestoneDelivered
  -> Buyer notified for review
  -> Audit record written

MilestoneAccepted
  -> Escrow Service evaluates release conditions
  -> EscrowReleased
  -> Payments Service disburses funds
  -> Trust Service records successful delivery
  -> Audit records payment completion

### 12.4.3 Flow 3 - Dispute

DisputeInitiated
  -> EscrowHoldApplied immediately
  -> EvidenceWindowOpened
  -> Parties notified
  -> Audit record written

DisputeResolved
  -> Escrow hold lifted or adjusted
  -> Payments executed according to resolution
  -> Trust signal applied
  -> Dispute record sealed

### 12.4.4 Flow 4 - Trust Score Update

ContractCompleted / ReviewSubmitted / VerificationCompleted / DisputeResolved / CredentialRevoked
  -> Trust Service recomputes score
  -> TrustTierChanged if threshold confirmed
  -> Professional profile updated
  -> Search index refreshed
  -> Audit record written

### 12.4.5 Flow 5 - Verification

CredentialSubmitted
  -> VerificationCaseCreated
  -> ProviderRequestSent
  -> VerificationCompleted or VerificationFailed
  -> Professional status updated
  -> Trust signal added or risk flag applied
  -> Search re-indexed

### 12.4.6 Flow 6 - Policy Evaluation

ProposalSubmitted or ContractGenerated or EscrowReleaseRequested
  -> Policy Service loads active policy profile
  -> Rules evaluated
  -> ALLOW / REQUIRE_APPROVAL / BLOCK returned
  -> Workflow continues, pauses, or blocks
  -> Audit record written

# 13 Chapter 8 - State Machines

## 13.1 8.1 Why State Machines Matter

Many Zoikorum objects must move through strict lifecycles. Invalid transitions are not bugs; they are governance failures.

## 13.2 8.2 Core State Machines

### 13.2.1 Proposal

Draft -> Submitted -> UnderReview -> Negotiating -> Accepted | Rejected | Withdrawn | Expired

Rules:

- Draft cannot jump to Accepted.

- Expired cannot be accepted.

- Accepted is terminal.

- Acceptance requires policy evaluation.

### 13.2.2 Contract

Generated -> PendingSignature -> Active -> Completed | Terminated | Disputed

Rules:

- Active requires required signatures.

- Disputed contract cannot be unilaterally terminated.

- Material amendments require re-signature.

### 13.2.3 Escrow

Unfunded -> Funded -> PartiallyReleased -> FullyReleased
                 |-> Disputed
                 |-> Refunded

Rules:

- No release from Unfunded.

- No release with active dispute hold.

- Every movement writes ledger and audit records.

### 13.2.4 Dispute

Initiated -> EvidenceCollection -> DirectResolution -> Mediation -> Decision -> Enforcement -> Closed

Rules:

- Dispute initiation freezes disputed funds.

- Evidence window is time-bound.

- Closure requires decision and enforcement record.

## 13.3 8.3 State Machine Code Pattern

class ProposalStateMachine {
  private static transitions: Record<ProposalStatus, ProposalStatus[]> = {
    DRAFT: ['SUBMITTED'],
    SUBMITTED: ['UNDER_REVIEW', 'WITHDRAWN', 'EXPIRED'],
    UNDER_REVIEW: ['NEGOTIATING', 'ACCEPTED', 'REJECTED', 'EXPIRED'],
    NEGOTIATING: ['ACCEPTED', 'REJECTED', 'WITHDRAWN', 'EXPIRED'],
    ACCEPTED: [],
    REJECTED: [],
    WITHDRAWN: [],
    EXPIRED: []
  };

  static assertCanTransition(from: ProposalStatus, to: ProposalStatus) {
    if (!this.transitions[from].includes(to)) {
      throw new InvalidStateTransitionError(`${from} -> ${to} is not allowed`);
    }
  }
}

Backend enforcement is mandatory. Frontend state hiding is not enough.

# 14 Chapter 9 - Durable Workflows

## 14.1 9.1 Why REST Chains Fail

Long processes cannot be implemented as fragile chains of HTTP calls.

Examples:

- proposal approval;

- contract signing;

- escrow funding;

- milestone acceptance;

- dispute resolution;

- credential renewal;

- professional offboarding.

If a process can take hours, days, or weeks, it belongs in a durable workflow engine.

## 14.2 9.2 Temporal Workflow Example

export async function contractExecutionWorkflow(contractId: string): Promise<void> {
  await activities.requestSignature(contractId, 'professional');

  const professionalSigned = await workflow.condition(
    () => workflow.getSignalCount('professional-signed') > 0,
    '3 days'
  );

  if (!professionalSigned) {
    await activities.escalateSignatureDeadline(contractId, 'professional');
    return;
  }

  await activities.requestSignature(contractId, 'buyer');

  const buyerSigned = await workflow.condition(
    () => workflow.getSignalCount('buyer-signed') > 0,
    '3 days'
  );

  if (!buyerSigned) {
    await activities.escalateSignatureDeadline(contractId, 'buyer');
    return;
  }

  await activities.activateContract(contractId);
  await activities.requestEscrowFunding(contractId);

  const funded = await workflow.condition(
    () => workflow.getSignalCount('escrow-funded') > 0,
    '5 days'
  );

  if (!funded) {
    await activities.handleFundingTimeout(contractId);
    return;
  }

  await activities.notifyEngagementReady(contractId);
}

## 14.3 9.3 Workflow Rules

- Workflows orchestrate; activities do the work.

- Workflows must be deterministic.

- Use workflow time APIs, not raw Date.now().

- Every timeout must have an escalation path.

- Every workflow must be restart-safe.

# 15 Chapter 10 - Policy Engine

## 15.1 10.1 Why Policy Cannot Be Hard-Coded

Bad:

if contract.amount > 50000:
    require_vp_approval()

This fails because every enterprise may have different thresholds, approval roles, jurisdictions, and exceptions.

Good:

{
  "policyId": "approval-threshold-001",
  "version": 4,
  "orgId": "enterprise_acme",
  "condition": {
    "field": "contract.totalValue",
    "operator": "GREATER_THAN",
    "value": 50000
  },
  "action": "REQUIRE_APPROVAL",
  "approverRole": "VP_PROCUREMENT",
  "timeoutHours": 48,
  "escalationRole": "CPO"
}

## 15.2 10.2 Policy Decisions

| Decision | Meaning | System Action |
|---|---|---|
| ALLOW | Rules pass | Continue flow |
| REQUIRE_APPROVAL | Human approval needed | Publish ApprovalRequired; workflow pauses |
| BLOCK | Rule prohibits action | Reject action with reason; audit it |
| REQUIRE_EXCEPTION | Exception needed | Open exception workflow |

## 15.3 10.3 Policy Evaluation Algorithm

async function evaluatePolicy(context: PolicyContext): Promise<PolicyDecision> {
  const policies = await policyRepo.findActivePolicies(context.orgId, context.eventType);
  const results = [];

  for (const policy of policies) {
    const result = ruleEvaluator.evaluate(policy.rule, context);
    results.push({ policyId: policy.id, version: policy.version, result });
  }

  const decision = mostRestrictive(results);
  await audit.writePolicyEvaluation(context, results, decision);
  return decision;
}

Most restrictive wins:

BLOCK > REQUIRE_EXCEPTION > REQUIRE_APPROVAL > ALLOW

# 16 Chapter 11 - Audit

## 16.1 11.1 Audit Is Not Logging

Logs help engineers debug. Audit records prove what happened.

Application log:

Proposal accepted successfully

Audit record:

{
  "actor": "buyer_123",
  "action": "ProposalAccepted",
  "object": "proposal_789",
  "timestamp": "2026-01-22T10:44:00Z",
  "policyVersion": "policy_v4",
  "correlationId": "corr_abc",
  "authStrength": "HIGH"
}

## 16.2 11.2 Audit Requirements

Audit records must include:

- actor;

- action;

- object;

- timestamp;

- policy version;

- correlation ID;

- causation ID;

- authentication strength;

- evidence hash where applicable.

## 16.3 11.3 Immutable Audit Ledger

Audit records are append-only.

Record 1 -> hash_1
Record 2 -> hash(hash_1 + record_2)
Record 3 -> hash(hash_2 + record_3)

If any record changes, the chain breaks.

# 17 Chapter 12 - Idempotency

## 17.1 12.1 Why It Matters

If a buyer clicks Fund Escrow twice, the system must not charge twice.

## 17.2 12.2 API Idempotency

POST /v1/escrow/escrow_123/fund
Idempotency-Key: buyer_123-escrow_123-ms_001

## 17.3 12.3 Code Pattern

async function withIdempotency<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const existing = await idempotencyStore.get(key);
  if (existing) return existing.response as T;

  const result = await operation();
  await idempotencyStore.set(key, { response: result }, { ttl: '7d' });
  return result;
}

## 17.4 12.4 Event Consumer Idempotency

async function handleProposalAccepted(event: EventEnvelope<ProposalAccepted>) {
  const key = `event:${event.eventId}`;
  if (await inbox.has(key)) return;

  await db.transaction(async (trx) => {
    await contractService.generateFromProposal(event.payload, trx);
    await inbox.markProcessed(key, trx);
  });
}

# 18 Part IV - Marketplace, Search, Payments, AI, and Enterprise Systems

# 19 Chapter 13 - Search Engineering

## 19.1 13.1 Search Is Strategic

Search is not a filter. Search is the marketplace’s revenue engine.

A good search result must satisfy:

- semantic relevance;

- verified trust;

- availability;

- jurisdiction eligibility;

- pricing fit;

- buyer policy fit;

- explainability.

## 19.2 13.2 Search Pipeline

Query Understanding
  -> Intent classification
  -> Entity extraction
  -> Taxonomy mapping
Retrieval
  -> BM25 lexical search
  -> Dense vector search
  -> Structured filters
Fusion
  -> Reciprocal Rank Fusion
Re-ranking
  -> Trust, availability, responsiveness, policy fit
Explanation
  -> Why this result appears
Response

## 19.3 13.3 Ranking Factors

| Factor | Weight | Notes |
|---|---|---|
| Semantic relevance | 30% | Match buyer need to profile and offering |
| Trust score | 20% | Verified signals and outcomes |
| Contract success rate | 15% | Historical completion |
| Review score | 10% | Recency-weighted |
| Availability | 10% | Start date and capacity |
| Response behavior | 5% | Recent response speed |
| Pricing alignment | 5% | Budget fit if stated |
| Policy fit | 5% | Enterprise restrictions and eligibility |

## 19.4 13.4 Search Safety Rule

Policy-blocked, suspended, credential-expired, or jurisdiction-ineligible professionals must not appear in results for affected buyers.

# 20 Chapter 14 - AI Architecture

## 20.1 14.1 AI Doctrine

AI assists. Humans decide. Policy enforces. Audit records.

AI may:

- summarize profiles;

- help buyers describe needs;

- draft proposals;

- rank candidates;

- flag risk;

- summarize evidence.

AI must not:

- approve credentials;

- accept proposals;

- sign contracts;

- release payments;

- resolve disputes;

- ban users.

## 20.2 14.2 RAG for Knowledge-Assisted Features

Use Retrieval-Augmented Generation only when the answer must be grounded in approved content.

RAG pipeline:

User request
  -> classify intent
  -> retrieve approved knowledge chunks
  -> rank and filter chunks
  -> generate answer with citations to internal sources
  -> log prompt, model, chunks, output

## 20.3 14.3 Prompt Registry

Every production prompt requires:

- prompt ID;

- version;

- owner;

- approval status;

- target model;

- golden test set;

- rollback plan.

No unregistered production prompt is allowed.

## 20.4 14.4 AI Evaluation

Test AI systems for:

- factuality;

- hallucination rate;

- harmful output;

- bias in ranking;

- prompt injection resistance;

- regression against golden examples.

# 21 Chapter 15 - Payments, Ledger and Escrow

## 21.1 15.1 Treat Payments as Sacred

Payment logic must be boring, strict, and auditable.

Rules:

- no raw card data stored;

- no release without milestone acceptance;

- no release during active dispute;

- no duplicate charge;

- every movement reconciled;

- every provider webhook verified and idempotent.

## 21.2 15.2 Escrow Release Decision Tree

Release request received
  -> Is milestone accepted?
       No: reject
  -> Is there an active dispute hold?
       Yes: reject
  -> Has this release already processed?
       Yes: return original result
  -> Does policy require extra approval?
       Yes: start approval workflow
  -> Is provider ready?
       No: queue retry
  -> Is professional payout account valid?
       No: notify and queue
  -> Release funds
  -> Write ledger entry
  -> Publish EscrowReleased
  -> Write audit record

## 21.3 15.3 Ledger Principle

For internal financial correctness, model fund movement with ledger entries.

At minimum:

| Entry Type | Meaning |
|---|---|
| BuyerFunding | Buyer funds escrow |
| EscrowHold | Funds held against milestone |
| EscrowRelease | Funds released to professional |
| PlatformFee | Zoikorum fee recognition |
| Refund | Funds returned to buyer |
| Payout | Transfer to professional |
| Chargeback | Payment provider reversal |

For mature versions, adopt double-entry ledger design with balanced debits and credits.

## 21.4 15.4 Reconciliation

Daily reconciliation compares:

- Zoikorum internal ledger;

- payment provider charges;

- payout provider transfers;

- bank settlement records.

Any mismatch is a P0 financial incident.

# 22 Chapter 16 - Disputes

## 22.1 16.1 Dispute Principle

Disputes are not support tickets. They are governed evidence workflows.

## 22.2 16.2 Dispute Flow

DisputeInitiated
  -> funds frozen for disputed milestone
  -> evidence window opened
  -> direct resolution attempted
  -> mediation if unresolved
  -> decision issued
  -> escrow settlement executed
  -> dispute record sealed

## 22.3 16.3 Evidence Rules

Evidence must be:

- structured;

- timestamped;

- versioned;

- tied to contract/milestone;

- protected from tampering.

# 23 Chapter 17 - Enterprise Marketplace Engineering

## 23.1 17.1 Enterprise Objects

Enterprise accounts need more than a user table.

Objects include:

- organization;

- legal entity;

- business unit;

- cost center;

- role;

- authority limit;

- approval route;

- policy profile;

- procurement pack;

- audit export.

## 23.2 17.2 Approval Chains

Approval types:

- single approver;

- sequential multi-approver;

- parallel approval;

- conditional branching;

- emergency exception.

Each approval requires:

- actor;

- authority;

- timestamp;

- policy version;

- decision;

- reason where denied.

# 24 Part V - APIs, Security, Data, Distributed Systems and Cloud

# 25 Chapter 18 - API Design Standards

## 25.1 18.1 REST Standards

Use REST for resource operations.

Examples:

POST /v1/proposals
GET /v1/proposals/{proposalId}
POST /v1/proposals/{proposalId}/accept
GET /v1/contracts/{contractId}/milestones
POST /v1/disputes

## 25.2 18.2 Error Format

Use a consistent error response based on Problem Details.

{
  "type": "https://docs.zoikorum.com/errors/policy-blocked",
  "title": "Policy blocked this action",
  "status": 403,
  "detail": "This buyer requires Tier A professionals for regulated engagements.",
  "code": "POLICY_BLOCKED_MINIMUM_TRUST_TIER",
  "correlationId": "corr_123"
}

## 25.3 18.3 Pagination

Use cursor pagination for large lists.

GET /v1/professionals?category=finance-accounting&limit=20&cursor=eyJpZCI6...

Never return unbounded collections.

## 25.4 18.4 Optimistic Concurrency

Use versions or ETags for resources that may be edited by multiple actors.

PATCH /v1/proposals/proposal_123
If-Match: "version-7"

If the version changed, return 409 Conflict.

# 26 Chapter 19 - Security Engineering

## 26.1 19.1 Security Doctrine

Security is layered. No single control saves the platform.

Layers:

- edge protection;

- transport security;

- identity;

- authorization;

- application security;

- data protection;

- secrets management;

- monitoring and incident response.

## 26.2 19.2 Identity and Tokens

Use:

- short-lived access tokens;

- rotating refresh tokens;

- MFA for sensitive operations;

- passkeys where possible;

- SSO for enterprise;

- SCIM for lifecycle management.

## 26.3 19.3 Authorization

Use RBAC + ABAC.

Example ABAC rule:

A buyer may view a contract only if contract.buyerOrgId == actor.orgId.
A professional may submit milestone only if milestone.professionalId == actor.professionalId.
A platform operator may not mutate financial state unless assigned financial-ops role and step-up MFA is complete.

## 26.4 19.4 OWASP Risks to Prevent

| Risk | Zoikorum Control |
|---|---|
| SQL Injection | Parameterized queries, ORM review, SAST |
| XSS | Output encoding, CSP, HTML sanitization |
| CSRF | CSRF tokens for browser state-changing requests |
| SSRF | Egress allowlists, URL validation |
| Mass Assignment | Explicit DTO mapping |
| Broken Access Control | Centralized authorization middleware + tests |
| Secret Leakage | Secret scanning, Vault, no secrets in code |
| Dependency Risk | SCA scanning, SBOM, update policy |

# 27 Chapter 20 - Database Engineering

## 27.1 20.1 Relational Discipline

Use PostgreSQL for authoritative transactional state.

Rules:

- use migrations, never manual production DDL;

- design indexes deliberately;

- avoid full-table scans on large tables;

- understand transactions and isolation levels;

- keep OLTP and analytics separate.

## 27.2 20.2 Transaction Isolation

Use appropriate isolation:

| Case | Isolation |
|---|---|
| Profile edit | Read committed |
| Proposal acceptance | Repeatable read or transaction-level locks |
| Escrow release | Serializable or explicit row locks |
| Ledger update | Serializable preferred |

## 27.3 20.3 Migrations

Every migration needs:

- forward script;

- rollback or compensation plan;

- production data volume test;

- lock impact analysis;

- deployment sequence.

# 28 Chapter 21 - Distributed Systems Patterns

## 28.1 21.1 Outbox Pattern

Problem: database write succeeds but event publish fails.

Solution: write event to outbox table in same transaction as state change.

Begin transaction
  -> update Proposal status to Accepted
  -> insert ProposalAccepted into outbox
Commit
Outbox worker publishes event

## 28.2 21.2 Inbox Pattern

Problem: same event arrives twice.

Solution: consumer records processed event IDs.

Receive event
  -> check inbox
  -> process if not seen
  -> mark processed in same transaction

## 28.3 21.3 Retry Rules

- retry transient failures;

- do not retry validation errors;

- exponential backoff;

- jitter to avoid thundering herd;

- DLQ after maximum attempts;

- manual replay for financial events.

## 28.4 21.4 Circuit Breakers and Bulkheads

If a dependency is failing, stop hammering it.

Use circuit breakers around:

- payment provider;

- verification provider;

- AI model provider;

- email provider;

- search cluster.

Bulkhead critical services so notification failure cannot take down escrow release.

# 29 Chapter 22 - Caching

## 29.1 22.1 Cache-Aside Pattern

async function getTrustScore(professionalId: string) {
  const cached = await redis.get(`trust:${professionalId}`);
  if (cached) return JSON.parse(cached);

  const score = await trustRepo.findScore(professionalId);
  await redis.set(`trust:${professionalId}`, JSON.stringify(score), 'EX', 300);
  return score;
}

## 29.2 22.2 Cache Rules

- cache derived data, not source-of-truth financial state;

- invalidate via events where possible;

- use TTLs;

- protect against cache stampede;

- never let stale policy cache allow unsafe action.

# 30 Chapter 23 - Cloud and Deployment

## 30.1 23.1 Start Simple, Preserve the Target

A young team may start with managed services:

- managed PostgreSQL;

- managed Redis;

- managed Kafka or cloud event bus;

- managed Temporal;

- managed OpenSearch;

- object storage;

- container deployment.

Do not self-manage complex infrastructure before the team is ready.

## 30.2 23.2 Target Deployment

Target architecture:

CDN + WAF
  -> API Gateway
    -> Kubernetes services
      -> Domain databases
      -> Event bus
      -> Workflow engine
      -> Search cluster
      -> Object storage

## 30.3 23.3 Deployment Patterns

Use:

- blue/green deployments;

- canary releases;

- feature flags;

- kill switches;

- automated rollback;

- GitOps;

- infrastructure as code.

# 31 Chapter 24 - Reliability and SRE

## 31.1 24.1 SLIs and SLOs

| Service | SLI | SLO |
|---|---|---|
| Search | p99 latency | <300ms |
| Identity | availability | 99.99% |
| Proposal | mutation latency | p99 <500ms |
| Contract | activation workflow success | >99.5% |
| Escrow | release correctness | 100%; no duplicate release |
| Payments | reconciliation mismatch | 0 unresolved |
| Audit | write availability | 99.99% |

## 31.2 24.2 Error Budgets

If a service exhausts its error budget, feature work pauses and reliability work takes priority.

## 31.3 24.3 Incident Management

Every P0/P1 incident requires:

- incident commander;

- timeline;

- customer impact statement;

- root cause;

- corrective actions;

- post-incident review;

- runbook update.

# 32 Part VI - Build Execution, Testing, Standards and Culture

# 33 Chapter 25 - Vertical Slice Build Order

## 33.1 25.1 Why Vertical Slices

Do not build layers in isolation. Build one user journey end-to-end.

## 33.2 25.2 Slice 1 - Professional Discovery MVP

Build:

- ZoikoID signup/login;

- professional profile;

- service offering;

- taxonomy;

- profile publishing;

- search index;

- buyer search;

- audit records.

Test:

A professional publishes a profile.
The profile appears in search within 30 seconds.
A buyer can view the profile.
All key actions are audited.

## 33.3 25.3 Slice 2 - Proposal Lifecycle

Build:

- proposal request;

- professional proposal submission;

- proposal states;

- accept/reject;

- proposal events;

- notifications;

- audit.

Test:

A proposal cannot be accepted after expiry.
ProposalAccepted event starts downstream contract generation.
Duplicate accept request does not double-process.

## 33.4 25.4 Slice 3 - Contract Execution

Build:

- contract generation;

- signature workflow;

- milestones;

- contract activation;

- audit.

Test:

Contract cannot activate without both signatures.
Workflow resumes after restart.

## 33.5 25.5 Slice 4 - Escrow and Milestone Payment

Build:

- escrow funding;

- milestone delivery;

- milestone acceptance;

- release decision tree;

- provider webhooks;

- reconciliation.

Test:

Escrow cannot release without accepted milestone.
Duplicate release does not double-pay.
Provider timeout does not corrupt state.

## 33.6 25.6 Slice 5 - Dispute Resolution

Build:

- dispute initiation;

- escrow hold;

- evidence submission;

- mediation workflow;

- resolution;

- settlement execution.

Test:

Dispute freezes disputed milestone funds within 5 seconds.
Release is blocked while dispute is active.
Resolution executes correct fund split.

## 33.7 25.7 Slice 6 - Trust, Verification and Enterprise

Build:

- verification cases;

- credential checks;

- trust score;

- trust tiers;

- enterprise organizations;

- SSO;

- policy profiles;

- approval workflows;

- audit exports.

Test:

Credential verification updates trust and search.
Credential revocation reduces eligibility.
Enterprise threshold triggers approval workflow.

# 34 Chapter 26 - Testing Strategy

## 34.1 26.1 Unit Tests

Test domain invariants.

describe('Contract', () => {
  it('cannot activate without all required signatures', () => {
    const contract = Contract.generated();
    contract.recordSignature('buyer');
    expect(() => contract.activate()).toThrow(MissingSignatureError);
  });
});

## 34.2 26.2 Integration Tests

Test event flows.

describe('ProposalAccepted -> ContractGenerated', () => {
  it('generates a contract from an accepted proposal', async () => {
    await eventBus.publish(buildProposalAcceptedEvent());
    const event = await waitForEvent('ContractGenerated');
    expect(event.payload.proposalId).toBeDefined();
  });
});

## 34.3 26.3 Failure Tests

Test production failures before production finds them.

describe('Escrow release failures', () => {
  it('rejects release when dispute hold exists', async () => {
    await createFundedEscrow();
    await createDisputeHold();
    await expect(releaseEscrow()).rejects.toThrow(ActiveDisputeHoldError);
  });
});

## 34.4 26.4 End-to-End Tests

Test the platform spine:

Buyer finds professional
  -> requests proposal
  -> accepts proposal
  -> signs contract
  -> funds escrow
  -> accepts milestone
  -> funds released

# 35 Chapter 27 - Code Organization

## 35.1 27.1 Recommended Structure

/apps
  /api-gateway
  /worker
  /admin-api

/domains
  /identity
  /professional
  /buyer
  /firm
  /marketplace
  /proposal
  /contract
  /escrow
  /payments
  /verification
  /trust
  /policy
  /dispute
  /audit
  /search
  /messaging
  /notification
  /ai

/workflows
  /proposal-approval
  /contract-execution
  /escrow-funding
  /milestone-acceptance
  /dispute-resolution
  /credential-renewal

/shared
  /events
  /errors
  /auth
  /database
  /idempotency
  /logging
  /observability

## 35.2 27.2 Modular Monolith Is Acceptable

For a young team, a modular monolith is acceptable at first if boundaries are clean.

Rules:

- separate modules;

- separate database schemas;

- no cross-domain direct table access;

- events still exist;

- service interfaces are explicit.

The mistake is not starting as a monolith. The mistake is building a tangled monolith.

# 36 Chapter 28 - Developer Standards

## 36.1 28.1 Definition of Done

A feature is not done until:

- domain model is documented;

- state machine enforced;

- API documented;

- event schema published;

- audit record written;

- permissions checked;

- idempotency handled;

- policy evaluated where required;

- tests cover success and failure;

- logs, metrics, traces exist;

- runbook updated.

## 36.2 28.2 Pull Request Standard

Every PR must include:

- what changed;

- why it changed;

- test plan;

- screenshots or API examples where relevant;

- migration notes;

- rollout plan;

- rollback plan;

- security considerations.

## 36.3 28.3 Architecture Decision Records

Use ADRs for significant decisions:

ADR-012: Use Temporal for Contract Execution Workflow
Status: Accepted
Context: Contract signing and escrow funding are long-running.
Decision: Use durable workflow engine.
Consequences: More operational complexity, much better reliability.
Alternatives: Cron jobs, REST chain, message-only choreography.

# 37 Chapter 29 - Engineering Culture

## 37.1 29.1 How the Team Should Think

- Precision beats speed when money, trust, or legal state changes.

- Shortcuts that bypass governance are not allowed.

- Every engineer owns reliability, security, and auditability.

- Write code that the next engineer can understand.

- If something is confusing, improve the documentation.

## 37.2 29.2 Review Culture

A good review asks:

- Is the domain boundary correct?

- Is the state transition valid?

- Is the event correct?

- Is the policy evaluated?

- Is the action audited?

- Is it idempotent?

- What breaks under failure?

## 37.3 29.3 Incident Culture

Do not hide incidents. Investigate them.

The goal is not blame. The goal is system improvement.

# 38 Chapter 30 - Anti-Patterns and Correct Patterns

| Anti-Pattern | Why Dangerous | Correct Pattern |
|---|---|---|
| Services read each other’s databases | Hidden coupling and broken ownership | APIs, events, projections |
| Hard-coded enterprise rules | Every policy change becomes deployment | Policy engine |
| Cron jobs for long workflows | Fragile, invisible, restart-unsafe | Durable workflows |
| Releasing escrow from button click | Financial risk | Release decision tree |
| No idempotency | Duplicate charges or releases | Idempotency keys and inbox/outbox |
| Audit as logs | Not legally defensible | Immutable audit ledger |
| AI final decisions | Platform liability | Human-in-command |
| Search without governance filters | Unsafe discovery | Trust and policy-aware ranking |
| Raw payment data stored | Compliance violation | Provider tokenization |
| Manual admin edits without audit | Corrupts trust | Audited operator workflows |

# 39 Final Engineering Doctrine

Zoikorum must be built like a bank, searched like Google, governed like enterprise procurement, and experienced like a world-class marketplace.

The engineering team is not building features.

The engineering team is building the trust infrastructure that allows serious professional services to be bought and sold safely at marketplace speed.

No shortcuts. No hidden coupling. No unaudited commerce. No ungoverned trust.

# 40 Appendix A - Quick Reference Glossary

| Term | Definition |
|---|---|
| Aggregate Root | Primary entity through which an aggregate is modified |
| Bounded Context | Domain boundary with its own language and model |
| Causation ID | Event ID of the immediate cause of another event |
| Correlation ID | ID shared across all actions in a request chain |
| CQRS | Separating command models from query models |
| Dead Letter Queue | Queue for failed events after retries |
| Durable Workflow | Workflow that persists state and survives restarts |
| Event Sourcing | Storing events as source of truth |
| Idempotency | Safe repeat execution without duplicate side effects |
| Invariant | Rule that must always be true |
| Outbox Pattern | Transactionally writing state and event together |
| Policy Engine | Service evaluating configurable rules |
| Projection | Read-optimized view built from events |
| State Machine | Explicit lifecycle and transition rules |
| Trust Tier | Public trust category derived from verified signals |
| ZoikoID | Unified identity object for platform participants |

# 41 Appendix B - Engineer Pre-Flight Checklist

Before submitting a feature PR, confirm:

- Which domain owns this?

- What aggregate changes?

- What command causes it?

- What event is published?

- What state transition happens?

- Which policy applies?

- What audit record is written?

- Is the operation idempotent?

- What happens if the dependency fails?

- How will support/debug this in production?

- Which metric proves it works?

- Which test proves it fails safely?

# 42 Appendix C - First 30 Days Training Plan

## 42.1 Week 1 - Foundations

- Read Chapters 1-12.

- Build a toy Proposal state machine.

- Publish and consume a local ProposalAccepted event.

- Write an audit record.

## 42.2 Week 2 - Vertical Slice

- Build professional profile publish flow.

- Index profile into search.

- Add audit and event logs.

- Add tests for invalid publish.

## 42.3 Week 3 - Proposal and Contract

- Build request proposal and submit proposal.

- Add accept proposal state machine.

- Generate contract draft from accepted proposal.

- Add idempotency to accept endpoint.

## 42.4 Week 4 - Escrow Thinking and Failure Testing

- Implement mock escrow funding.

- Implement milestone acceptance.

- Add release decision tree.

- Simulate duplicate release and provider timeout.

At the end of 30 days, every engineer must demo an end-to-end slice and explain the events, policy, audit, and failure behavior.

Document End
