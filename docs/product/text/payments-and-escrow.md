<!-- Generated from payments-and-escrow.docx — edit the .docx, not this file. -->

# Payments & Escrow

# ZOIKORUM — PAYMENTS, ESCROW & RELEASE CONTROLS FLOW WIREFRAME v1.0

## GOVERNED PAYMENTS · RISK CONTAINMENT · AUTOMATED SETTLEMENT

## DOCUMENT CONTROL

Platform: Zoikorum
 Artifact: Payments, Escrow & Release Controls Flow
 Category: Global Marketplace for Governed Professional Services
 Standard: Fortune 10 · Tier-1 Financial UX · Audit-Grade Controls
 Document Classification: Production-Ready Interaction Wireframe
 Audience: Buyers · Professionals · Firms · Finance · Legal · Compliance · Enterprise Procurement · Product · Design · Engineering
Last Updated: January 22, 2026

## 0. EXECUTIVE INTENT

Payments are the highest-risk moment in professional services.

Zoikorum’s payment system exists to:

- Eliminate unilateral payment risk

- Separate work acceptance from funds movement

- Prevent disputes before they arise

- Enforce outcomes deterministically

- Produce audit-grade financial records

This is not a payments app.
 This is governed financial infrastructure for professional engagements.

Zoikorum does not hold funds casually.
 Zoikorum enforces conditions, authority, and timing before money moves.

## 1. NON-NEGOTIABLE UI / UX LAWS (MANDATORY)

| UX / UI Law | Enforcement |
|---|---|
| Jakob’s Law | Familiar escrow & checkout patterns |
| Hick’s Law | ≤ 3 primary payment actions per screen |
| Miller’s Law | ≤ 7 visible financial data blocks |
| Fitts’s Law | Primary CTAs ≥ 48px desktop / 56px mobile |
| Progressive Disclosure | Advanced controls revealed only when relevant |
| Recognition > Recall | Visual ledgers, milestone states, badges |
| Error Prevention | Pre-funding validation & confirmations |
| Doherty Threshold | <400ms feedback for all payment actions |
| Peak-End Rule | Clear confirmation after every financial action |
| Aesthetic-Usability Effect | Calm, trustworthy financial UI |
| WCAG 2.2 AAA (Target) | Full accessibility compliance |

## 2. CORE PAYMENT PRINCIPLES

- No work without funding

- No release without acceptance

- No acceptance without authority

- No discretion without policy

- No settlement without record

## 3. PAYMENT MODEL OVERVIEW

Zoikorum supports governed escrow-based payments, not peer-to-peer transfers.

### Supported Engagement Payment Models

- Fixed-price (single milestone)

- Fixed-price (multi-milestone)

- Time-boxed project

- Retainer (recurring milestones)

- Fractional / ongoing engagements

All models map to milestones with conditions.

## 4. PAYMENT ENTRY POINTS

Payments are initiated from:

- Engagement acceptance screen

- Contract execution step

- Milestone creation or update

- Retainer renewal

- Enterprise bulk funding workflow

No payment initiation is possible outside an active, contract-bound engagement.

## 5. GLOBAL PAYMENT FRAME (PERSISTENT UI)

Every payment-related screen includes:

- Engagement ID

- Contract reference

- Milestone ID (if applicable)

- Payment state badge

- Amount (currency + breakdown)

- Authority indicator

- Ledger preview

- “What happens next” panel

- Sticky primary action bar

## 6. PAYMENT STATES (SYSTEM-ENFORCED)

Each milestone transitions through immutable states:

- Unfunded

- Funded (Escrowed)

- In Progress

- Submitted for Acceptance

- Accepted

- Released

- Settled

Optional terminal states:

- Disputed

- Refunded

- Expired

- Cancelled

## 7. PHASE 1 — FUNDING INITIATION

### Objective

Ensure funds are secured before work begins.

### Required Inputs

- Funding amount

- Currency

- Payment method

- Milestone mapping

### UX Safeguards

- Clear breakdown: fees, taxes (if applicable), net payable

- “Funds will be held securely until acceptance” notice

- Confirmation modal before funding

### System Actions

- Validate payment method

- Lock milestone

- Create escrow ledger entry

## 8. PHASE 2 — ESCROW FUNDING

### Objective

Isolate funds from both parties until conditions are met.

### Escrow Behavior

- Funds are held in segregated accounts (or equivalent)

- Neither party can withdraw unilaterally

- Funds are visible but locked

### UX Indicators

- Escrow Funded badge

- Ledger showing “Held Balance”

- Countdown to expected delivery (if defined)

## 9. PHASE 3 — WORK IN PROGRESS (NO PAYMENT ACTIONS)

While work is in progress:

- No release buttons are visible

- Buyer sees “Work in progress”

- Professional sees “Funds secured”

This prevents premature payment pressure.

## 10. PHASE 4 — SUBMISSION FOR ACCEPTANCE

### Trigger

Professional submits deliverables.

### System Actions

- Lock further edits

- Notify buyer

- Start acceptance timer

### UX

- Deliverables checklist

- Acceptance criteria reminder

- Dispute option becomes visible (but secondary)

## 11. PHASE 5 — ACCEPTANCE DECISION

### Buyer Actions (Primary)

- Accept Work

- Request Revisions

- Raise Dispute

### UX Safeguards

- Acceptance requires explicit confirmation

- Summary of what acceptance triggers (payment release)

- Authority check (enterprise)

## 12. PHASE 6 — RELEASE AUTHORIZATION

### Authority Model

- Individual buyer (default)

- Multi-approver (enterprise)

- Automated acceptance (policy-controlled)

### UX

- Approval chain shown visually

- Pending approvals highlighted

- SLA countdown visible

## 13. PHASE 7 — FUNDS RELEASE

### System Actions

- Execute escrow release

- Update ledger

- Generate receipt

- Notify both parties

### UX

- “Funds released successfully” confirmation

- Timestamp + transaction ID

- Downloadable receipt (PDF)

## 14. PHASE 8 — SETTLEMENT & PAYOUT

### Professional View

- Net amount

- Fees deducted

- Payout method

- Expected settlement date

### Buyer View

- Total paid

- Ledger update

- Engagement cost summary

## 15. RETAINERS & RECURRING PAYMENTS

### Behavior

- Funds reserved per cycle

- Auto-funding (if authorized)

- Manual acceptance per cycle (default)

### UX

- Calendar view of cycles

- Upcoming funding reminders

- Pause / cancel controls (policy-bound)

## 16. DISPUTE INTEGRATION

If a dispute is raised:

- Funds immediately frozen

- Release disabled

- Dispute workflow takes precedence

- Payment state changes to Disputed

No manual override is possible outside policy.

## 17. ENTERPRISE PAYMENT CONTROLS

Enterprise policy profiles may define:

- Mandatory escrow thresholds

- Approval chains

- Auto-release rules

- Legal review triggers

- Spend limits

- Currency restrictions

Enterprise dashboards show:

- Funds on hold

- Exposure by vendor

- Release timelines

- Audit exports

## 18. EDGE CASES & FAILSAFES

Handled explicitly:

- Partial acceptance

- Partial release

- Over-funding

- Currency conversion failure

- Payment method failure

- Sanctions or compliance flags

- Chargeback attempts

Each has deterministic system behavior.

## 19. ANALYTICS & KPIs

Tracked metrics:

- Time from funding to release

- Dispute rate per payment

- Acceptance latency

- Refund frequency

- Enterprise approval bottlenecks

Used for:

- Risk scoring

- Trust tier adjustments

- Enterprise reporting

## 20. ACCESSIBILITY & PERFORMANCE

- Keyboard navigable payment flows

- Screen-reader friendly ledgers

- High-contrast financial indicators

- Skeleton loaders

- <400ms interaction feedback

## 21. AUDIT & RECORD KEEPING

Every payment produces immutable records:

- Funding event

- Escrow ledger

- Acceptance decision

- Release execution

- Settlement confirmation

Exports available in:

- PDF

- CSV

- JSON (enterprise)

## 22. LEGAL POSITIONING

Zoikorum provides payment orchestration and escrow infrastructure only. Zoikorum does not act as a bank, lender, or fiduciary unless explicitly disclosed. Payment services are provided by regulated third-party partners. All payments operate under platform terms, policy profiles, and applicable law.

## 23. DOCUMENT CONTROL

Version: 1.0
 Review Cycle: Quarterly or upon material change

Approvals Required:
 Product · Design · Legal · Compliance · Engineering · Executive
