<!-- Generated from engineering-backend-architecture.docx — edit the .docx, not this file. -->

# Engineering Backend Architecture

ZOIKORUM(TM)

Engineering Architecture

Backend Platform Architecture & Implementation Guide

| Field | Value |
|---|---|
| Classification | Internal - Engineering Leadership |
| Version | 1.0 |
| Status | Authoritative Reference |
| Owner | Office of the CTO |
| Prepared For | Young tactile engineering team, CTO office, architecture leads, product, security, compliance |
| Language | American English |
| Date | 2026 |

Document doctrine: Business intent first, domain architecture second, service design third, infrastructure last.

# Foreword

This document is the authoritative backend engineering specification for Zoikorum. It defines what to build, why it matters, and how each component supports the platform's core business outcome: a governed global marketplace where professionals and firms can be discovered, contracted, paid, verified, evaluated, and held accountable at enterprise grade.

Zoikorum is not merely an e-commerce marketplace, a freelancer directory, or a procurement portal. It is a marketplace operating system for high-trust professional services. That distinction shapes every architectural decision.

The document is intentionally written for a young tactile engineering team: concrete enough to build from, structured enough to learn from, and rigorous enough to survive enterprise, security, compliance, and investor review.

## Defining Architectural Commitments

- Domain-first, infrastructure-second: business domains are modeled before databases are selected.

- Events over shared state: services communicate through versioned APIs and event contracts, not database joins.

- Governance as a first-class core: verification, policy, audit, disputes, and trust are not add-ons.

- Durable process over fragile choreography: long-running commercial processes use workflow orchestration.

- Policy-as-code: configurable enterprise rules are versioned and evaluated centrally, not embedded in service logic.

- Auditability by default: every commercial, trust, policy, and payment action is traceable.

- Security and privacy by design: sensitive data is minimized, encrypted, segregated, and access-controlled.

# Table of Contents

- Part I - Executive Engineering Overview

- Part II - Domain Architecture

- Part III - Bounded Contexts and Domain Models

- Part IV - Platform Capabilities

- Part V - Service Architecture

- Part VI - Event-Driven Architecture

- Part VII - API Architecture

- Part VIII - Database and Data Architecture

- Part IX - Search Architecture

- Part X - AI Architecture and Governance

- Part XI - Identity Architecture

- Part XII - Marketplace Engine

- Part XIII - Governance Engine

- Part XIV - Security Architecture

- Part XV - Deployment Architecture

- Part XVI - Observability

- Part XVII - Performance Engineering

- Part XVIII - Disaster Recovery

- Part XIX - Engineering Standards

- Part XX - Delivery Roadmap

- Appendices - Glossary, ADR Index, Build Checklists

# PART I - EXECUTIVE ENGINEERING OVERVIEW

## 1.1 What Zoikorum Is

Zoikorum is a Tier-0 global marketplace for governed professional services. It connects buyers - individuals, businesses, and enterprise procurement teams - with professionals and firms that offer specialized services under verification, contract, payment protection, audit, and policy controls.

The strategic distinction from consumer freelance platforms is fundamental:

| Dimension | Consumer Gig Platforms | Zoikorum Target Standard |
|---|---|---|
| Primary buyer | Individuals and SMBs | Individuals, SMBs, firms, enterprise procurement, regulated teams |
| Trust model | Reviews and ratings dominate | Verified identity, credential validation, jurisdiction eligibility, audit history |
| Engagement model | Gig listing, simple fixed price | Proposal, statement of work, milestone, retainer, fractional, enterprise workflows |
| Payment model | Basic escrow or direct payout | Governed payment protection, release conditions, ledger, dispute holds |
| Governance | Minimal and reactive | Policy engine, approval workflows, trust tiers, immutable audit ledger |
| Search | Keyword and category search | Hybrid lexical + semantic + trust-filtered + policy-aware ranking |
| Enterprise readiness | Often bolted on | Native: SSO, SCIM, policy profiles, audit exports, approval chains |

## 1.2 Architectural Philosophy

| Pillar | Meaning | Engineering Consequence |
|---|---|---|
| Trust Infrastructure | Trust is computed from verified signals, not assumed. | Trust domain, verification service, credential renewal workflows, trust projections. |
| Governance Infrastructure | Enterprise rules are configurable and enforceable. | Policy service, workflow engine, approvals, exception logging. |
| Marketplace Intelligence | Discovery must be fast, relevant, explainable, and safe. | Search service, ranking engine, vector retrieval, explainable scoring. |
| Durable Commerce | Contracts, payments, escrow, milestones, and disputes are long-running and failure-sensitive. | Temporal/workflow orchestration, idempotency keys, outbox pattern, compensation workflows. |

## 1.3 Binding Engineering Principles

| Principle | Implementation Rule |
|---|---|
| EP-01 Domains before databases | No schema is designed without a domain model and aggregate boundaries. |
| EP-02 Explicit service contracts | Every service exposes versioned APIs/events. Implicit shared data is prohibited. |
| EP-03 Events for cross-domain state change | Domains publish state changes; subscribers maintain projections. |
| EP-04 Idempotency for commercial operations | Payments, escrow, contract, and release actions must be idempotent. |
| EP-05 Immutable audit ledger | Audit records are append-only; update/delete is prohibited. |
| EP-06 Failure-first design | Failure modes, retries, DLQs, compensations, and operator runbooks are designed upfront. |
| EP-07 Policy is configuration | Enterprise and jurisdictional rules live in the policy engine, not scattered application code. |
| EP-08 Security is layered | Edge, transport, identity, service authorization, data-level access, and observability all participate. |
| EP-09 Privacy is minimization | Collect only what is necessary, isolate sensitive data, and provide retention controls. |
| EP-10 Young-team clarity | Every domain, service, event, API, and state machine must be documented in buildable language. |

# PART II - DOMAIN ARCHITECTURE

## 2.1 Domain-Driven Design Foundation

Zoikorum is partitioned into bounded contexts. Each bounded context has its own language, data ownership, events, APIs, and engineering accountability. Domain boundaries are business boundaries; they are not arbitrary microservice slices.

| Domain | Business Purpose | Ownership |
|---|---|---|
| Identity | Authentication, authorization, sessions, SSO, MFA | Platform |
| Professional | Profiles, offerings, availability, service identity | Marketplace |
| Buyer | Buyer profiles, organizations, teams, procurement context | Marketplace |
| Firm | Firm accounts, team professionals, firm verification | Marketplace |
| Marketplace | Discovery, listing, matching, ranking, recommendations | Marketplace |
| Proposal | Request, proposal, negotiation, acceptance/expiry | Commerce |
| Contract | Contract generation, execution, milestones, amendments | Commerce |
| Escrow | Funds holding, release conditions, holds, refunds | Commerce |
| Payments | Payment processing, invoices, tax, payout orchestration | Commerce |
| Verification | Identity, credential, license, insurance, checks | Trust |
| Trust | Trust score, trust tiers, signals, risk flags | Trust |
| Search | Indexing, faceting, vector retrieval, autocomplete | Intelligence |
| Messaging | Secure in-context communication and file exchange | Communication |
| Notification | Email, in-app, push, digests, webhooks | Communication |
| Policy | Enterprise rules, approvals, restrictions, exceptions | Governance |
| Dispute | Dispute intake, evidence, mediation, outcome | Governance |
| Audit | Immutable ledger, exports, evidence attestations | Governance |
| Analytics | Operational metrics, product analytics, enterprise reports | Intelligence |
| AI | Matching assistance, summarization, risk flagging, prompts | Intelligence |
| Security | Threat detection, fraud, bot prevention, anomalies | Security |
| Administration | Operator tools, configuration, moderation | Platform |

## 2.2 Domain Interaction Model

Domains never share databases. Cross-domain data access occurs through only three approved patterns:

- Synchronous query API when real-time authoritative data is required.

- Asynchronous domain events when another domain needs to react to state change.

- Materialized read projections built locally from event streams for fast queries.

Database-level joins across domain boundaries are prohibited. If a developer feels they need a cross-domain join, the domain model or projection strategy is wrong.

## 2.3 Ownership and Autonomy

- Each domain has one owning team and one accountable technical lead.

- Only the owning service writes to the domain database.

- Domain APIs and event schemas are versioned and backward-compatible.

- Each domain owns its SLAs, runbooks, dashboards, and data quality.

# PART III - BOUNDED CONTEXTS AND DOMAIN MODELS

## 3.x Identity Domain

| Element | Specification |
|---|---|
| Purpose | Manage every platform actor, authentication path, session, MFA state, enterprise federation, and account lifecycle. |
| Aggregate Root | Identity |
| Entities | Credential, Session, MFADevice, APIKey, IdentityLink, ConsentRecord, DeviceFingerprint |
| Value Objects | EmailAddress, PhoneNumber, IdentityProvider, AuthenticationStrength, SessionRiskLevel |
| Domain Events | IdentityCreated, EmailConfirmed, MFAEnrolled, AuthenticationSucceeded, AuthenticationFailed, SessionCreated, SessionRevoked, IdentitySuspended, IdentitySoftDeleted |
| Invariants | High-risk operations require elevated authentication; enterprise-federated identities cannot change email without IdP reconfirmation; active sessions inherit enterprise session policy. |

## 3.x Professional Domain

| Element | Specification |
|---|---|
| Purpose | Represent the professional or firm offering services: profile, offerings, availability, capacity, pricing, and public representation. |
| Aggregate Root | Professional |
| Entities | ServiceOffering, Experience, QualificationClaim, PortfolioItem, AvailabilityWindow, PricingStructure, CapacityRule, ProfilePublication |
| Value Objects | Specialization, DeliveryMode, JurisdictionLicense, ExperienceLevel, LanguageProficiency, ResponseTimeBand |
| Domain Events | ProfessionalRegistered, ProfilePublished, ProfileSuspended, ServiceOfferingCreated, ServiceOfferingUpdated, AvailabilityUpdated, PricingUpdated, QualificationClaimAdded |
| Invariants | A profile may be visible as Discovery only before verification; contract-activating capabilities require policy-required trust tier; declared active capacity must not be exceeded without explicit override. |

## 3.x Firm Domain

| Element | Specification |
|---|---|
| Purpose | Represent professional firms, their admins, team members, firm credentials, and firm-level offerings. |
| Aggregate Root | Firm |
| Entities | FirmMember, FirmOffering, FirmCredential, FirmRoleAssignment, FirmVerificationCase |
| Value Objects | FirmSizeBand, FirmJurisdiction, OwnershipDeclaration, AuthorizedRepresentative |
| Domain Events | FirmRegistered, FirmVerified, FirmMemberInvited, FirmMemberRemoved, FirmOfferingPublished |
| Invariants | A firm cannot publish firm-level regulated offerings without at least one verified authorized representative and policy-required firm verification. |

## 3.x Buyer Domain

| Element | Specification |
|---|---|
| Purpose | Represent buyers, organizations, teams, procurement context, cost centers, and buyer authority. |
| Aggregate Root | BuyerOrganization |
| Entities | BuyerUser, BusinessUnit, CostCenter, BuyerRole, ProcurementProfile, SpendLimit |
| Value Objects | BuyerType, AuthorityLevel, OrganizationTier, BusinessUnitPath |
| Domain Events | BuyerRegistered, OrganizationCreated, BusinessUnitCreated, BuyerRoleAssigned, SpendLimitUpdated |
| Invariants | A buyer cannot approve spend beyond assigned authority; enterprise users inherit role and policy from organization configuration. |

## 3.x Marketplace Domain

| Element | Specification |
|---|---|
| Purpose | Handle listing, discovery, matching, rankings, saved searches, saved professionals, and marketplace intent. |
| Aggregate Root | MarketplaceListing |
| Entities | CapabilityTaxonomy, MatchRequest, MatchResult, SavedSearch, SavedProfessional, RankingExplanation |
| Value Objects | RankingSignals, MatchConfidence, SearchIntent, ExplainedRank |
| Domain Events | MatchRequested, MatchResultsProduced, ListingViewed, ListingBookmarked, SearchPerformed, SearchZeroResult |
| Invariants | Policy-blocked professionals must not appear for affected buyers; suspended profiles cannot be discoverable. |

## 3.x Proposal Domain

| Element | Specification |
|---|---|
| Purpose | Manage request, proposal, revision, negotiation, acceptance, rejection, expiry, and handoff to contract. |
| Aggregate Root | Proposal |
| Entities | ProposalTerm, Revision, ProposalThread, ApprovalCheckpoint, ProposalAttachment |
| Value Objects | ProposalStatus, ProposalType, ExpiryPolicy, RevisionReason |
| Domain Events | ProposalRequested, ProposalDrafted, ProposalSubmitted, ProposalRevised, ProposalAccepted, ProposalRejected, ProposalExpired, ApprovalRequested |
| Invariants | A proposal cannot be accepted if any policy-required approval is pending; accepted terms become immutable input to the Contract domain. |

## 3.x Contract Domain

| Element | Specification |
|---|---|
| Purpose | Generate, execute, amend, suspend, complete, and terminate contract-bound engagements. |
| Aggregate Root | Contract |
| Entities | ContractTerm, Milestone, Deliverable, Amendment, SignatureRecord, CompletionRecord, AcceptanceCriteria |
| Value Objects | ContractStatus, MilestoneStatus, SignatureMethod, AmendmentMateriality |
| Domain Events | ContractGenerated, ContractSigned, ContractActivated, MilestoneCreated, MilestoneDelivered, MilestoneAccepted, ContractAmended, ContractCompleted, ContractDisputed |
| Invariants | A contract cannot activate without all required signatures; material amendments require re-signature; disputed contracts cannot be unilaterally terminated. |

## 3.x Escrow Domain

| Element | Specification |
|---|---|
| Purpose | Maintain funds protection, release conditions, holds, refunds, and escrow audit records. |
| Aggregate Root | EscrowAccount |
| Entities | EscrowDeposit, ReleaseInstruction, HoldInstruction, RefundInstruction, EscrowAuditEntry |
| Value Objects | EscrowStatus, ReleaseCondition, LedgerReference, FundsState |
| Domain Events | EscrowOpened, EscrowFunded, EscrowHoldApplied, ReleaseEvaluated, EscrowReleased, EscrowRefunded |
| Invariants | No release without accepted milestone or dispute resolution instruction; no release with active dispute hold; every fund movement creates an audit entry. |

## 3.x Payments Domain

| Element | Specification |
|---|---|
| Purpose | Process payment methods, charges, payouts, invoices, taxes, fees, refunds, and reconciliations. |
| Aggregate Root | PaymentIntent |
| Entities | PaymentMethod, Charge, Payout, Invoice, TaxCalculation, FeeLine, ReconciliationBatch |
| Value Objects | Money, Currency, TaxJurisdiction, PaymentProviderToken, FeeType |
| Domain Events | PaymentIntentCreated, PaymentAuthorized, PaymentCaptured, PaymentFailed, PayoutInitiated, PayoutSettled, InvoiceIssued |
| Invariants | No raw card data stored; all provider callbacks are idempotent; payouts require completed compliance checks. |

## 3.x Verification Domain

| Element | Specification |
|---|---|
| Purpose | Conduct and maintain identity, credential, license, insurance, background, and firm verification cases. |
| Aggregate Root | VerificationCase |
| Entities | VerificationSubject, EvidenceItem, ProviderResponse, ReviewDecision, ExpiryReminder |
| Value Objects | VerificationType, VerificationStatus, EvidenceHash, ExpiryDate, ProviderReference |
| Domain Events | VerificationStarted, EvidenceSubmitted, VerificationCompleted, VerificationFailed, VerificationExpiring, VerificationExpired, VerificationRevoked |
| Invariants | Verified status requires positive provider or approved human review; expiring verification triggers renewal workflow; revoked verification updates Professional and Trust. |

## 3.x Trust Domain

| Element | Specification |
|---|---|
| Purpose | Compute and publish trust tiers, trust signals, eligibility flags, and trust history. |
| Aggregate Root | TrustProfile |
| Entities | TrustSignal, TrustScoreSnapshot, TierHistory, RiskFlag, SignalDecayRule |
| Value Objects | TrustScore, TrustTier, SignalWeight, SignalSource, TimeDecayFactor |
| Domain Events | TrustSignalAdded, TrustScoreRecomputed, TrustTierChanged, TrustProfileFlagged, TrustSignalRevoked |
| Invariants | Adverse signals trigger immediate recomputation; tier changes require hysteresis; trust scoring must remain explainable. |

## 3.x Policy Domain

| Element | Specification |
|---|---|
| Purpose | Evaluate configurable business rules for eligibility, spend, approvals, jurisdiction, release, exceptions, and enterprise profiles. |
| Aggregate Root | PolicyProfile |
| Entities | PolicyRule, ApprovalRoute, ExceptionRequest, PolicyVersion, PolicyEvaluation |
| Value Objects | PolicyDecision, RuleCondition, RiskLevel, ApprovalAuthority, PolicyScope |
| Domain Events | PolicyCreated, PolicyVersionActivated, PolicyEvaluated, ApprovalRequired, ApprovalGranted, ApprovalDenied, PolicyViolationDetected |
| Invariants | Policies are versioned; active engagements retain applied policy version; exceptions are time-bound and audit-logged. |

## 3.x Dispute Domain

| Element | Specification |
|---|---|
| Purpose | Manage governed dispute intake, evidence, direct resolution, mediation, escalation, decision, and enforcement. |
| Aggregate Root | DisputeCase |
| Entities | DisputeCategory, EvidenceBundle, ResolutionProposal, MediationRecord, DecisionPackage, AppealRequest |
| Value Objects | DisputeStatus, DesiredOutcome, EvidenceType, ResolutionOutcome |
| Domain Events | DisputeInitiated, EvidenceWindowOpened, EvidenceSubmitted, ResolutionProposed, DisputeEscalated, DisputeResolved, DisputeClosed |
| Invariants | Dispute initiation applies escrow hold; evidence is versioned; resolution must produce enforceable payment or engagement instruction. |

## 3.x Audit Domain

| Element | Specification |
|---|---|
| Purpose | Write immutable records for commercial, trust, policy, security, and operator events. |
| Aggregate Root | AuditRecord |
| Entities | AuditEnvelope, HashChainEntry, ExportJob, AttestationRecord |
| Value Objects | Actor, Action, ObjectReference, CorrelationId, EvidenceHash |
| Domain Events | AuditRecordWritten, AuditExportRequested, AuditExportCompleted, HashChainValidated, HashChainBroken |
| Invariants | Insert-only; no update or delete; records include actor, action, timestamp, object, policy version, and correlation ID. |

# PART IV - PLATFORM CAPABILITIES

A capability is what the platform does for users and enterprises. Services are how engineering delivers those capabilities.

| Capability | Description | Primary Domains |
|---|---|---|
| Professional Discovery | Find professionals/firms matching buyer intent with trust and policy filters. | Marketplace, Search, AI, Trust, Policy |
| Category Taxonomy | Maintain strategic profession taxonomy and specialization trees. | Marketplace, Administration |
| Profile & Offering Management | Enable professionals/firms to publish structured services. | Professional, Firm, Verification |
| Proposal Management | Request, negotiate, revise, and accept proposals. | Proposal, Policy, Notification |
| Contract Execution | Generate, sign, version, and govern contracts. | Contract, Policy, Audit |
| Milestone Management | Manage deliverables, acceptance, revision, and completion. | Contract, Escrow, Dispute |
| Escrow & Payments | Hold, release, settle, refund, invoice, and reconcile funds. | Escrow, Payments, Audit |
| Verification & Credentialing | Validate identity, licenses, certifications, insurance, and jurisdictions. | Verification, Trust |
| Trust Scoring | Compute tiers and signals from verified evidence and platform outcomes. | Trust, Professional, Search |
| Secure Messaging | In-context communication tied to proposal/engagement records. | Messaging, Audit |
| Dispute Resolution | Collect evidence, mediate, escalate, decide, and enforce outcomes. | Dispute, Escrow, Audit |
| Policy Profiles | Encode enterprise rules, approvals, spend thresholds, and restrictions. | Policy, Workflow |
| Audit & Compliance | Produce immutable records and export packages. | Audit, Evidence Vault |
| AI Assistance | Assist search, proposal drafting, summarization, risk flagging. | AI, Search, Governance |
| Analytics | Deliver operational, marketplace, enterprise, and risk intelligence. | Analytics |

# PART V - SERVICE ARCHITECTURE

## 5.1 Service Design Standard

Every service must be documented with the same template. Inconsistent service specs are not accepted in architecture review.

- Purpose

- Responsibilities

- APIs

- Events Published

- Events Consumed

- Storage

- External Dependencies

- Internal Dependencies

- Security Controls

- Scaling Model

- Failure Modes

- SLA Targets

| Service | Responsibilities | Events Published | Events Consumed | Storage | SLA / Target |
|---|---|---|---|---|---|
| Professional Service | Professional lifecycle, profiles, offerings, availability, capacity, publication. | ProfessionalRegistered, ProfilePublished, ServiceOfferingCreated | VerificationCompleted, TrustTierChanged, ContractCompleted | PostgreSQL + Redis | p99 read <100ms; publish <300ms |
| Firm Service | Firm profiles, member management, firm verification, firm offerings. | FirmRegistered, FirmVerified, FirmMemberInvited | VerificationCompleted, PolicyEvaluated | PostgreSQL | p99 read <150ms |
| Buyer Service | Buyer accounts, organizations, cost centers, roles, spend context. | BuyerRegistered, OrganizationCreated, BuyerRoleAssigned | PolicyVersionActivated | PostgreSQL | p99 read <100ms |
| Marketplace Service | Listings, saved searches, saved profiles, match requests. | MatchRequested, ListingViewed, ListingBookmarked | ProfilePublished, TrustTierChanged | PostgreSQL + Redis | p99 <150ms |
| Search Service | Hybrid search, autocomplete, facets, trust/policy filtering. | SearchPerformed, SearchZeroResult | ProfilePublished, TrustTierChanged, AvailabilityUpdated | OpenSearch + Vector DB + Redis | p99 <300ms |
| Proposal Service | Requests, proposals, revisions, negotiation, acceptance/expiry. | ProposalRequested, ProposalSubmitted, ProposalAccepted | PolicyEvaluated, ApprovalGranted | PostgreSQL | p99 mutation <500ms |
| Contract Service | Generate/sign contracts, milestones, amendments, completion. | ContractGenerated, ContractActivated, MilestoneAccepted | ProposalAccepted, DisputeResolved | PostgreSQL + Blob | p99 read <200ms |
| Escrow Service | Escrow account, holds, release evaluation, refunds. | EscrowOpened, EscrowFunded, EscrowReleased | ContractActivated, MilestoneAccepted, DisputeInitiated | Isolated PostgreSQL | 99.99%; p99 <500ms |
| Payments Service | Payment intents, charges, payouts, invoices, reconciliation. | PaymentAuthorized, PayoutSettled, InvoiceIssued | EscrowReleased, RefundInstructionCreated | Isolated PostgreSQL | 99.99%; p99 <1000ms |
| Verification Service | Identity, credential, license, insurance, firm verification. | VerificationStarted, VerificationCompleted, VerificationExpired | ProfessionalRegistered, CredentialSubmitted | PostgreSQL + Blob | Case SLA provider-dependent |
| Trust Service | Trust signals, scores, tiers, risk flags. | TrustScoreRecomputed, TrustTierChanged | VerificationCompleted, ContractCompleted, DisputeResolved | PostgreSQL + Redis | Adverse recompute <5s |
| Policy Service | Policy profiles, rule evaluation, approvals, exceptions. | PolicyEvaluated, ApprovalRequired, PolicyViolationDetected | ProposalSubmitted, ContractGenerated, EscrowReleaseRequested | PostgreSQL + Rules Store | p99 evaluation <80ms |
| Workflow Service | Durable orchestration for long-running business processes. | WorkflowStarted, WorkflowCompleted, WorkflowFailed | ProposalAccepted, VerificationExpiring, ContractActivated | Temporal persistence DB | Workflow resume guaranteed |
| Dispute Service | Dispute intake, evidence, mediation, decision, closure. | DisputeInitiated, DisputeResolved, DisputeClosed | MilestoneRejected, PaymentHoldApplied | PostgreSQL + Blob | Evidence operations <500ms |
| Audit Service | Immutable audit ledger, export jobs, hash chain validation. | AuditRecordWritten, AuditExportCompleted | All critical domain events | Append-only DB + S3 Object Lock | Write availability 99.99% |
| Messaging Service | Engagement-bound messages, attachments, moderation, evidence export. | MessageSent, MessageFlagged | EngagementActivated, DisputeInitiated | PostgreSQL + Blob | p99 send <200ms |
| Notification Service | Email, in-app, push, webhooks, preferences. | NotificationQueued, NotificationDelivered | All domain events | PostgreSQL + Redis | Delivery p99 <5s |
| AI Service | Inference orchestration, prompts, model registry, safety logs. | AIOutputGenerated, ModelVersionChanged | SearchRequested, ProposalDraftRequested, DisputeEvidenceSubmitted | PostgreSQL + Vector DB | Fallback to non-AI |
| Administration Service | Operator tools, moderation queues, taxonomy management. | TaxonomyUpdated, OperatorActionLogged | RiskFlagRaised | PostgreSQL | Operator actions audit logged |

## 5.2 Service Failure Modes Standard

- Every service must define graceful degradation behavior.

- Every mutation must be protected by idempotency key or workflow id.

- Every event publisher uses the outbox pattern.

- Every event consumer is idempotent and DLQ-aware.

- Every service has a runbook for database failure, dependency failure, event lag, and partial outage.

# PART VI - EVENT-DRIVEN ARCHITECTURE

## 6.1 Event Bus Architecture

Zoikorum uses an event bus as the integration fabric between domains. The default implementation is Apache Kafka or managed Kafka equivalent. Kafka is not used as a random message queue; it is the platform's domain event backbone.

- At-least-once delivery with consumer idempotency.

- Schema validation through a schema registry using Avro or Protobuf.

- Consumer groups isolate domain subscribers.

- Replay capability for projections and audit reconstruction.

- Dead-letter queues for failed processing.

Topic convention: zoikorum.{domain}.{aggregate}.{action}.v{version}. Example: zoikorum.contract.contract.activated.v1.

## 6.2 Event Envelope Standard

All events must include:
eventId, eventType, occurredAt, producedBy, correlationId, causationId, aggregateType, aggregateId, schemaVersion, tenantId, payload.

## 6.3 Critical Event Flows

| Flow | Sequence |
|---|---|
| Proposal to Contract | ProposalAccepted -> ContractGenerated -> ContractSigned -> ContractActivated -> EscrowOpened -> FundingRequested -> AuditRecordWritten |
| Milestone Release | MilestoneDelivered -> BuyerReviewStarted -> MilestoneAccepted -> ReleaseEvaluated -> EscrowReleased -> PayoutInitiated -> TrustSignalAdded |
| Dispute | DisputeInitiated -> EscrowHoldApplied -> EvidenceWindowOpened -> ResolutionProposed -> DisputeResolved -> EscrowResolutionExecuted -> AuditExportReady |
| Credential Expiry | VerificationExpiring -> RenewalTaskCreated -> ReminderSent -> VerificationExpired -> QualificationRevoked -> TrustScoreRecomputed -> SearchReindexed |
| Policy Approval | ProposalSubmitted -> PolicyEvaluated -> ApprovalRequired -> ApprovalGranted -> ProposalAdvanced -> AuditRecordWritten |

## 6.4 Idempotency and DLQ

- Consumer checks idempotency store by eventId before processing.

- Processing and idempotency write are committed atomically when possible.

- Financial events require manual DLQ replay authorization.

- Non-financial replay may be automated after safe backoff.

- Correlation ID must appear in logs, traces, audit records, and support tooling.

# PART VII - API ARCHITECTURE

## 7.1 API Principles

- REST for resource operations; GraphQL for front-end aggregation when it reduces client complexity; gRPC for internal high-throughput service-to-service calls.

- Breaking changes require a new major version and six-month deprecation window.

- All mutation endpoints accept Idempotency-Key.

- No unbounded collection endpoints; cursor pagination required.

- Sensitive operations require elevated authentication and step-up MFA.

## 7.2 Gateway Architecture

Client -> WAF/DDoS -> API Gateway -> Auth Validation -> Rate Limiting -> GraphQL/BFF or Service Router -> Domain Services.

## 7.3 Endpoint Examples

| Method | Path | Purpose | Control |
|---|---|---|---|
| POST | /v1/proposals | Create proposal request or professional proposal | Idempotency-Key required |
| POST | /v1/contracts/{id}/sign | Sign contract | Step-up MFA required |
| POST | /v1/escrow/{id}/fund | Fund escrow | Policy + payment validation |
| POST | /v1/milestones/{id}/accept | Accept milestone | Authority check required |
| POST | /v1/disputes | Open dispute | Freezes disputed funds |
| POST | /v1/policies/evaluate | Evaluate policy context | Used by services and admin tools |
| GET | /v1/audit/exports/{id} | Download audit export | Role + policy restricted |

## 7.4 Rate Limiting

| Consumer | Standard Limit | Burst Limit |
|---|---|---|
| Anonymous | 60 req/min | 120 req/min |
| Authenticated individual | 300 req/min | 600 req/min |
| Enterprise API client | 1,000 req/min | 2,000 req/min |
| Partner integration | Custom SLA | Custom SLA |

## 7.5 Webhook Architecture

- HMAC-SHA256 signatures on delivery.

- Event subscription filtering by event type.

- Retries with exponential backoff for 24 hours.

- Delivery logs retained for at least 90 days.

- Test endpoint and replay tool available to enterprise clients.

# PART VIII - DATABASE AND DATA ARCHITECTURE

## 8.1 Database Per Domain

| Domain | Storage | Justification |
|---|---|---|
| Identity | PostgreSQL dedicated | Authentication state, PII isolation, ACID |
| Professional | PostgreSQL + Redis | Relational profile data + availability cache |
| Marketplace | PostgreSQL + Redis | Listing state + saved searches |
| Proposal | PostgreSQL | State machine and negotiation history |
| Contract | PostgreSQL + Blob | Contract tree + signed PDFs + deliverables |
| Escrow | Dedicated PostgreSQL | Financial correctness; ACID mandatory |
| Payments | Isolated PostgreSQL | PCI-adjacent isolation, payouts, invoices |
| Verification | PostgreSQL + Blob | Verification cases and evidence |
| Trust | PostgreSQL + Redis | Scores + low-latency tier reads |
| Search | OpenSearch + Vector DB | Lexical, faceted, semantic retrieval |
| Messaging | PostgreSQL + Blob | Threads + attachments |
| Dispute | PostgreSQL + Blob | Cases + evidence bundles |
| Audit | Append-only PostgreSQL + S3 Object Lock | Immutable ledger and archives |
| Analytics | ClickHouse or Redshift | High-volume OLAP |
| AI | PostgreSQL + Vector DB | Prompts, models, embeddings, inference logs |

## 8.2 Special Data Controls

- Payments database: dedicated cluster, dedicated KMS keys, no ad-hoc operator queries, point-in-time recovery, cross-region replication.

- Audit database: insert-only role, no update/delete, hash chaining, hourly chain validation, S3 Object Lock after 90 days.

- Verification evidence: encrypted blob storage with per-document keys; access via service identities only.

- PII: field-level encryption for sensitive attributes and strict retention policies.

## 8.3 Data Governance

- Every table must have created_at, updated_at where mutation applies, and domain-specific versioning for state machines.

- All schema migrations are in version control and tested on production-scale data.

- No analytics workload runs directly against OLTP databases.

- Data retention is policy-configured by evidence type, jurisdiction, and enterprise profile.

# PART IX - SEARCH ARCHITECTURE

## 9.1 Strategic Doctrine

Search is the marketplace's revenue engine. A buyer who cannot find the right professional quickly will leave. Therefore search must be fast, accurate, explainable, trust-aware, and policy-aware.

## 9.2 Search Pipeline

- Query understanding: classify intent, extract entities, map terms to taxonomy.

- Retrieval: parallel BM25 lexical retrieval and dense vector retrieval.

- Structured filtering: trust tier, jurisdiction, availability, pricing, credential, enterprise policies.

- Fusion: reciprocal rank fusion across lexical and semantic candidate sets.

- Re-ranking: trust score, responsiveness, availability, engagement history, personalization.

- Explanation: generate human-readable ranking rationale.

## 9.3 Search SLAs and Safety

- p50 query latency <80ms; p99 <300ms.

- Suspended, restricted, policy-blocked, or jurisdiction-ineligible profiles must not appear.

- All search ranking experiments must include fairness and diversity guardrails.

- Search zero-result rate is a board-visible marketplace health metric.

## 9.4 Ranking Factors

| Factor | Default Weight | Notes |
|---|---|---|
| Semantic relevance | 30% | Embedding similarity to buyer need and taxonomy match |
| Trust score/tier | 20% | Verified evidence and outcomes |
| Contract success rate | 15% | Completion history, weighted by recency |
| Feedback/reviews | 10% | Secondary trust signal, not primary |
| Availability | 10% | Alignment to required start date and capacity |
| Response behavior | 5% | Recent response rate and response speed |
| Pricing alignment | 5% | Fit to budget, if stated |
| Policy fit | 5% | Enterprise restrictions and required checks |

## 9.5 Explainable Search Requirement

Each result must be capable of answering 'Why am I seeing this?' in plain language: matched specialization, verified credential, eligible jurisdiction, availability, pricing fit, and trust tier.

# PART X - AI ARCHITECTURE AND GOVERNANCE

## 10.1 AI Doctrine

AI assists. Policy constrains. Humans decide. AI may improve search, summarization, drafting, and risk flagging. AI must not autonomously approve verification, execute contracts, release funds, resolve disputes, or enforce sanctions.

## 10.2 AI Capabilities

| Capability | Input | Output | Human Approval | Audit |
|---|---|---|---|---|
| Professional Matching Assistant | Buyer need | Structured match request | Not required | Input/output/model logged |
| Proposal Assistant | Buyer request + service offering | Draft proposal | Professional must submit | Draft and final diff logged |
| Contract Summarizer | Executed contract | Plain-language summary | Not required; disclaimer mandatory | Document hash + summary logged |
| Dispute Mediation Assistant | Evidence bundle + contract + timeline | Suggested resolution | Human mediator required | AI output + human decision logged |
| Fraud/Risk Detection | Behavioral + payment + identity signals | Risk score + reason codes | Required for hard enforcement | Risk features and action logged |
| Search Re-ranking | Candidate set + buyer context | Re-ranked results | Not required; monitored | Factors logged for analysis |

## 10.3 Prompt Governance

- All prompts live in a Prompt Registry and have version, owner, model target, test suite, and approval status.

- No production inference may use an unregistered system prompt.

- Prompt changes require code review and AI safety review.

- Golden dataset tests must pass before deployment.

- AI outputs influencing commercial or trust workflows are logged with model version and prompt version.

## 10.4 AI Safety Constraints

- No black-box denials: any AI-flagged restriction must have explainable reason codes.

- No use of protected attributes for ranking unless legally justified and approved for fairness monitoring.

- Human override is required for account restriction, credential rejection, dispute resolution, or payment hold beyond policy automation.

# PART XI - IDENTITY ARCHITECTURE

## 11.1 ZoikoID

ZoikoID is the unified identity object for every participant: buyers, professionals, firm administrators, enterprise procurement users, dispute mediators, compliance officers, and platform operators.

## 11.2 Authentication Methods

| Method | Context | Notes |
|---|---|---|
| Email + password | Standard signup | Minimum 12 characters; secure hashing |
| Passkey/WebAuthn | All contexts | Preferred phishing-resistant authentication |
| Google OAuth | Consumer/SMB | Low-friction signup |
| Microsoft OAuth | Enterprise-friendly | Microsoft 365 |
| SAML 2.0 | Enterprise | Customer-managed identity provider |
| OIDC | Enterprise/partners | Modern federation option |
| SCIM 2.0 | Enterprise | Automated lifecycle provisioning/deprovisioning |

## 11.3 Authorization

Authorization is RBAC + ABAC. RBAC defines coarse roles; ABAC enforces context: org, contract owner, policy profile, authority level, trust tier, and data sensitivity.

## 11.4 Sensitive Operation Step-Up

- Contract signing, escrow release, payment method changes, credential verification submission, and operator enforcement require elevated auth strength.

- Enterprise policies may require step-up MFA for approvals above thresholds.

# PART XII - MARKETPLACE ENGINE

## 12.1 Matching Engine

The Matching Engine translates buyer intent into ranked, policy-safe professional recommendations.

- Intent extraction from natural language or structured form.

- Capability taxonomy mapping.

- Candidate retrieval through Search Service.

- Constraint filtering: availability, trust, jurisdiction, enterprise policy.

- Scoring and re-ranking.

- Explanation generation.

## 12.2 Capability Taxonomy

The taxonomy is hierarchical, versioned, and mapped to profiles, services, proposals, SEO pages, and filters. Category examples: Finance & Accounting -> Finance Leadership -> Fractional CFO.

## 12.3 Pricing Engine

- Market rate ranges by taxonomy, experience level, region, and engagement model.

- Buyer budget estimation before proposal request.

- Professional benchmarking with anonymized peer data.

- No individual contract price is exposed to other users.

## 12.4 Availability Engine

- Professional calendar sync optional.

- Effective availability computed from active engagements and capacity rules.

- Search can filter by start window and capacity.

- New commitments automatically reduce availability.

# PART XIII - GOVERNANCE ENGINE

## 13.1 Overview

The Governance Engine consists of Policy Engine, Workflow Engine, Audit Engine, Trust Engine, and Evidence Vault. These components are first-class architecture, not administration utilities.

## 13.2 Policy Engine

Policies are data. They are versioned, scoped, evaluated, and audited. Policy decisions return ALLOW, REQUIRE_APPROVAL, BLOCK, or REQUIRE_EXCEPTION.

| Policy Type | Example |
|---|---|
| Approval threshold | Contracts above $50,000 require VP approval |
| Trust requirement | Only Tier A professionals for regulated work |
| Jurisdiction restriction | Local license required for certain categories |
| Spend control | Cost center cannot exceed quarterly allocation |
| Release control | Milestone above threshold needs budget owner approval |
| Exception authority | Only Legal Admin may approve cross-border exception |

## 13.3 Durable Workflow Engine

Use Temporal or equivalent for long-running processes that must survive failures.

- Proposal approval workflow

- Contract execution workflow

- Escrow funding workflow

- Milestone acceptance workflow

- Dispute resolution workflow

- Credential renewal workflow

- Professional offboarding workflow

## 13.4 Evidence Vault

- Stores signed contracts, amendments, verification evidence, dispute evidence, audit exports.

- Documents are immutable after commit; new versions are appended.

- Access controlled by service identity and policy decision.

- Every access event is audit-logged.

## 13.5 Audit Engine

- Writes every commercial, trust, policy, security, and operator action.

- Hash chain validation detects tampering.

- Exports include policy version, actor, timestamp, object references, and evidence hashes.

# PART XIV - SECURITY ARCHITECTURE

## 14.1 Security Posture

Zoikorum targets SOC 2 Type II alignment and ISO 27001-ready controls. Security is layered: edge, transport, identity, service authorization, application, data, secrets, monitoring, incident response.

## 14.2 Controls

| Layer | Controls |
|---|---|
| Edge | WAF, DDoS, bot detection, IP reputation, rate limiting |
| Transport | TLS 1.3, mTLS between services through service mesh |
| Identity | ZoikoID, MFA, passkeys, SSO, SCIM |
| Authorization | RBAC + ABAC, policy checks, least privilege |
| Application | OWASP ASVS Level 2+, schema validation, CSRF protection, CSP |
| Data | Encryption at rest, field-level encryption, KMS, data minimization |
| Secrets | Vault/Secrets Manager, rotation, no secrets in code |
| Supply Chain | Image scanning, dependency scanning, signed containers, SBOM |
| Detection | SIEM, anomaly detection, threat dashboards |

## 14.3 Incident Response

| Severity | Examples | Target |
|---|---|---|
| P0 | Data breach, payments down, platform unavailable | 15-minute response |
| P1 | Suspected breach, major degradation | 30-minute response |
| P2 | Service below SLA | 2-hour response |

- Runbooks version-controlled.

- Quarterly game days.

- Post-incident review required for P0/P1.

# PART XV - DEPLOYMENT ARCHITECTURE

## 15.1 Deployment Model

- Cloud platform: AWS or GCP primary, cloud-portable infrastructure practices.

- Kubernetes managed cluster: EKS/GKE.

- Service mesh: Istio or equivalent for mTLS, traffic management, circuit breakers, telemetry.

- Ingress: managed load balancer + ingress controller.

- Containers signed and scanned before deployment.

## 15.2 Deployment Patterns

- Blue/green for standard service releases.

- Canary for high-risk changes: 5% -> 20% -> 50% -> 100%.

- Feature flags for dark launch and progressive rollout.

- Rollback target: <3 minutes for failed deployment.

- GitOps: Terraform + ArgoCD/Flux; no manual prod changes outside approved break-glass.

# PART XVI - OBSERVABILITY

## 16.1 Three Pillars

- Logs: structured JSON with correlationId, causationId, actorId, tenantId, service, route, eventId.

- Metrics: RED for services, USE for infrastructure, business metrics for marketplace health.

- Tracing: OpenTelemetry, 100% sampling for payments/escrow/contracts/disputes, sampled reads for low-risk queries.

## 16.2 SLOs

| Service | Availability SLO | Latency SLO |
|---|---|---|
| Search | 99.9% | p99 <300ms |
| Identity/Auth | 99.99% | p99 <100ms |
| Professional | 99.9% | p99 <100ms |
| Proposal | 99.9% | p99 <500ms mutation |
| Contract | 99.95% | p99 <200ms |
| Escrow | 99.99% | p99 <500ms |
| Payments | 99.99% | p99 <1000ms |
| Audit | 99.99% | write p99 <200ms |

## 16.3 Business Dashboards

- Search zero-result rate

- Proposal -> contract conversion

- Contract activation latency

- Escrow balance and release latency

- Dispute rate and resolution time

- Verification completion and expiry rates

- Trust tier distribution

- Enterprise approval bottlenecks

# PART XVII - PERFORMANCE ENGINEERING

## 17.1 Latency Budgets

| User Action | Target | Budget Notes |
|---|---|---|
| Homepage/category search | p99 <300ms | Retrieval, fusion, policy filtering, response serialization |
| Profile load | p99 <200ms | Profile projection + trust summary + offering summary |
| Proposal submission | p99 <500ms | Validation, policy evaluation, workflow start, event outbox |
| Contract generation | p99 <2s | Template render, policy clauses, document storage |
| Milestone acceptance | p99 <500ms | Authority check, state transition, release workflow trigger |
| Payment release action | p99 <1000ms | Provider latency tolerated through async confirmation |

## 17.2 Caching

| Data | Cache | TTL | Invalidation |
|---|---|---|---|
| Trust score | Redis | 5 min | TrustScoreRecomputed event |
| Search facets | Redis | 30 sec | Rolling TTL |
| Taxonomy | In-memory | 1 hour | TaxonomyUpdated event |
| Policy profile | Redis | 5 min | PolicyVersionActivated |
| Availability | Redis | 1 min | AvailabilityUpdated |
| User session | Redis | Session duration | SessionRevoked |

## 17.3 Database Standards

- All OLTP queries >50ms appear in slow query review.

- No full-table scans on tables above 100k rows without ADR.

- Connection pool alerts at 80% utilization.

- All high-cardinality filters require indexes or search index projection.

# PART XVIII - DISASTER RECOVERY

## 18.1 Recovery Objectives

| Service Tier | RPO | RTO |
|---|---|---|
| Payments and Escrow | 0 seconds preferred | <30 seconds |
| Identity and Auth | <1 minute | <2 minutes |
| Contract and Audit | <1 minute | <5 minutes |
| Core Marketplace | <5 minutes | <15 minutes |
| Search Index | <30 minutes | <30 minutes |
| Analytics | <1 hour | <4 hours |

## 18.2 Backup and Replication

- PostgreSQL WAL shipping and daily logical backups.

- Cross-region replication for contract, verification, and evidence storage.

- Search index snapshots plus replay from event streams.

- KMS/HSM key recovery through break-glass procedure only.

## 18.3 Chaos Engineering

- Quarterly chaos game days.

- Automated fault injection in staging.

- Unresolved resilience gaps classified as P1 reliability debt.

# PART XIX - ENGINEERING STANDARDS

## 19.1 Architecture Decision Records

Every significant decision requires an ADR with context, decision, consequences, and alternatives.

## 19.2 Definition of Done

- Domain model updated.

- API and event contracts documented and versioned.

- Unit tests >=80% for new code.

- Integration tests cover happy path and top three failure modes.

- Security review completed for sensitive workflows.

- Performance test run against representative data.

- Observability dashboards and alerts configured.

- Runbook updated.

- Feature flag configured.

- Documentation updated for tactile engineering handoff.

## 19.3 Code Review

- No merge without at least one independent reviewer.

- Security-sensitive changes require security-aware reviewer.

- Payments/escrow/policy/identity changes require senior review.

- AI prompt changes require AI safety review.

- Database migrations require DB-competent review.

## 19.4 Testing Strategy

- Unit tests for domain logic and invariants.

- Contract tests for service API compatibility.

- Integration tests for event flows.

- End-to-end tests for proposal -> contract -> escrow -> milestone -> release.

- Load tests for search and proposal flows.

- Security tests in CI/CD.

# PART XX - DELIVERY ROADMAP

| Wave | Timeframe | Minimum Viable Capability |
|---|---|---|
| Wave 1 - Platform Foundation | Months 1-4 | ZoikoID, professional/buyer registration, taxonomy, basic search, notifications, audit ledger, CI/CD, event bus, observability. |
| Wave 2 - Core Marketplace | Months 3-7 | Faceted/semantic search, proposals, messaging, contract generation, availability, saved professionals/searches. |
| Wave 3 - Trust and Verification | Months 6-10 | Identity verification, credential verification, trust score, trust tiers, review system, basic policy engine. |
| Wave 4 - Commercial Engine | Months 9-14 | Payments, escrow, milestones, release controls, invoices, dispute initiation and evidence collection. |
| Wave 5 - Enterprise Procurement | Months 13-18 | Enterprise orgs, SSO, SCIM, policy profiles, approval workflows, spend reporting, audit exports. |
| Wave 6 - Intelligence and Scale | Months 17-24 | AI matching, proposal assistant, contract summarizer, fraud detection, advanced analytics, market rate benchmarking. |

## 20.2 Build Discipline for Young Team

- Build vertical slices, not isolated components: e.g., professional profile -> search indexing -> profile result -> request proposal.

- Start with simple domain invariants; do not over-engineer microservices before domain ownership is clear.

- Use modular monolith or service cluster for early MVP if team capacity requires; keep domain boundaries strict so extraction is clean.

- Never compromise audit, idempotency, or policy enforcement even in MVP.

- Every release should include a demoable user outcome and an engineering artifact (event contract, API spec, or runbook).

# APPENDIX A - GLOSSARY

| Term | Definition |
|---|---|
| Aggregate Root | Primary entity through which an aggregate is modified. |
| Bounded Context | Business boundary with its own language, model, data, and ownership. |
| Correlation ID | ID propagated across service calls/events to reconstruct a request chain. |
| Causation ID | ID of the immediate upstream event/action that caused the current event. |
| DLQ | Dead Letter Queue for events that failed after retries. |
| Durable Workflow | Workflow persisted by a workflow engine and resilient to restarts. |
| Escrow | Funds held pending contractually defined conditions. |
| Idempotency | Safe repeat execution without duplicate side effects. |
| Policy Engine | Service that evaluates configurable business rules. |
| Trust Score | Weighted computed signal of professional trustworthiness. |
| Trust Tier | Public trust category derived from trust score and eligibility rules. |
| ZoikoID | Unified identity object for all platform actors. |

# APPENDIX B - ADR Index

| ADR | Title | Status |
|---|---|---|
| ADR-001 | Domain-per-database isolation | Accepted |
| ADR-002 | Kafka/event bus for domain events | Accepted |
| ADR-003 | Temporal for durable workflows | Accepted |
| ADR-004 | Policy-as-code engine | Accepted |
| ADR-005 | Hybrid OpenSearch + vector search | Accepted |
| ADR-006 | RBAC + ABAC authorization | Accepted |
| ADR-007 | Append-only audit ledger with hash chaining | Accepted |
| ADR-008 | Passkey-first authentication strategy | Accepted |
| ADR-009 | Consumer-driven contract testing | Accepted |
| ADR-010 | GitOps deployment model | Accepted |
| ADR-011 | AI prompt registry and inference audit | Accepted |
| ADR-012 | Evidence Vault as governed data store | Accepted |

# APPENDIX C - Engineering Handoff Checklist

- Can every service owner explain its aggregate roots and invariants?

- Are all event schemas in the registry before implementation?

- Do commercial workflows have workflow definitions and compensation paths?

- Are policy decisions externalized from application code?

- Does every financial operation have an idempotency key and audit record?

- Do all search results pass trust, jurisdiction, and policy filters?

- Can every buyer-facing AI output show explanation and model/prompt version?

- Can the platform reconstruct proposal -> contract -> escrow -> release through correlation ID?

# Document End

This specification is the authoritative Tier-0 backend architecture baseline. Domain-specific technical specifications, API contracts, and implementation tickets must trace back to this document. No shortcuts. No hidden coupling. No ungoverned commerce.
