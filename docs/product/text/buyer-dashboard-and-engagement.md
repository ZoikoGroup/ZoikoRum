<!-- Generated from buyer-dashboard-and-engagement.docx — edit the .docx, not this file. -->

# Buyer Dashboard & Engagement Management

ZOIKORUM — BUYER DASHBOARD & ENGAGEMENT MANAGEMENT WIREFRAME v1.0

## DOCUMENT CONTROL

Platform: Zoikorum
 Artifact: Buyer Dashboard & Engagement Management 
 Category: Global Marketplace for Governed Professional Services
 Audience: Buyers · Enterprise Buyers · Procurement · Legal · Compliance · Product · Engineering
 Last Updated: January 22, 2026

## 1. EXECUTIVE INTENT

The Buyer Dashboard is the command center of Zoikorum.

It is where:

- discovery becomes execution

- contracts become living records

- payments become controlled outcomes

The dashboard must enable buyers to see, manage, and govern all professional engagements in one place—without friction, confusion, or risk exposure.

This is not a messaging inbox.
 This is not a task list.
 This is a governed engagement control plane.

## 2. NON-NEGOTIABLE UX PRINCIPLES

| UX Law | Enforcement |
|---|---|
| Jakob’s Law | Familiar dashboard patterns |
| Miller’s Law | ≤ 7 primary dashboard modules |
| Hick’s Law | ≤ 3 actions per context |
| Fitts’s Law | Large, obvious action targets |
| Progressive Disclosure | Detail hidden until needed |
| Recognition > Recall | Visual states, labels, badges |
| Serial Position Effect | Critical items top & bottom |
| Peak-End Rule | Strong closure per engagement |
| Error Prevention | Locked states, confirmations |
| Doherty Threshold | <400ms feedback everywhere |

## 3. DASHBOARD ARCHITECTURE OVERVIEW

Global Header

↓

Dashboard Summary (At-a-Glance)

↓

Active Engagements

↓

Pending Actions

↓

Proposals & Requests

↓

Payments & Contracts

↓

Messages & Activity

↓

Saved & Monitoring

↓

Enterprise Controls (Contextual)

↓

Global Footer

## 4. DASHBOARD LANDING — SUMMARY VIEW

### Purpose

Answer in 3 seconds:

“What’s happening right now?”

### Layout (Top of Page)

Summary Cards (Max 5):

- Active Engagements

- Pending Actions

- Open Proposals

- Funds in Protection

- Saved Professionals

Each card is clickable.

UX Law Applied:
 👉 Pre-attentive Processing — numbers + icons = instant comprehension

## 5. ACTIVE ENGAGEMENTS MODULE

### Purpose

Manage live work without chaos.

### Table Structure

| Professional | Service | Status | Milestone | Payment | Actions |
|---|---|---|---|---|---|

Status Badges:

- Draft

- Awaiting Signature

- Active

- In Review

- Completed

- Disputed (rare, prominent)

Milestone Indicator:

- Progress bar (visual)

- Tooltip on hover

Actions (Max 3):

- View Engagement

- Approve Milestone

- Message

UX Laws:

- Hick’s Law: 3 actions max

- Proximity: Status, payment, actions grouped

## 6. ENGAGEMENT DETAIL VIEW (CLICK-THROUGH)

### This is the single source of truth for an engagement.

#### Sections (Vertical Stack):

- Engagement Overview

- Contract & Scope

- Milestones & Deliverables

- Payments & Protection

- Messages & Files

- Activity Log

Each section collapsible.

## 7. CONTRACT & SCOPE PANEL

Read-Only by Default

Shows:

- Agreed scope

- Deliverables

- Timeline

- Terms

Edit Request CTA (If Allowed): Request Change →

Changes trigger:

- Versioning

- Professional approval

- Audit record

UX Law:
 👉 Error Prevention — no silent edits

## 8. MILESTONES & DELIVERABLES

### Visual Timeline

Each milestone shows:

- Description

- Due date

- Status

- Associated payment

Actions:

- Approve

- Request Revision

Approval Flow:

- Confirmation modal

- Clear irreversible language

## 9. PAYMENTS & PROTECTION

### Buyer Clarity Module

Funds Status:

- Held

- Scheduled

- Released

Protection Indicators: ✓ Escrow-style holding
 ✓ Conditional release
 ✓ Dispute path available

CTA: View payment breakdown →

UX Law:
 👉 Trust Visibility — money never feels ambiguous

## 10. PROPOSALS & REQUESTS MODULE

### Shows:

- Sent requests

- Received proposals

- Expired proposals

Proposal Card Includes:

- Professional

- Service

- Price

- Status

- Response deadline

Actions:

- View Proposal

- Accept

- Decline

Declines request reason (optional, structured).

## 11. PENDING ACTIONS (ATTENTION QUEUE)

### Purpose

Prevent stagnation.

Examples:

- Proposal awaiting response

- Contract awaiting signature

- Milestone awaiting approval

Design:

- Highlighted strip

- Reduces cognitive scanning

UX Law:
 👉 Zeigarnik Effect — unfinished items demand attention

## 12. MESSAGES & ACTIVITY

### Unified Thread per Engagement

- All messages tied to engagement

- Files versioned

- System events included

No external messaging required.

## 13. SAVED & MONITORING

### Saved Professionals

- Availability tracking

- Notification triggers

### Saved Searches

- Alert on new matches

- Filter persistence

UX Law:
 👉 Commitment & Consistency — encourages return

## 14. ENTERPRISE CONTROLS (CONTEXTUAL)

Visible only to enterprise buyers.

Includes:

- Policy-restricted engagements

- Approval workflows

- Multi-user roles

- Exportable audit logs

CTA: View enterprise controls →

## 15. GLOBAL SEARCH (DASHBOARD-SCOPED)

Search across:

- Engagements

- Professionals

- Messages

- Contracts

Autocomplete + filters.

## 16. ERROR & EDGE STATES

- Professional unavailable

- Payment failure

- Jurisdiction conflict

- Dispute initiation

Every state includes:

- Explanation

- Next step

- Support path

No dead ends.

## 17. ACCESSIBILITY & PERFORMANCE

- WCAG 2.2 AAA

- Keyboard navigable

- Screen-reader labels

- <400ms interaction feedback

- Skeleton loading states

## 18. ANALYTICS & AUDITABILITY

Tracked:

- Engagement lifecycle

- Approval timestamps

- Payment actions

- User actions

Immutable logs for enterprise export.

## 19. LEGAL POSITIONING

Zoikorum provides marketplace infrastructure, contracting facilitation, verification, and payment protection mechanisms. Professional services are delivered by independent third-party professionals and firms. Zoikorum does not provide regulated professional services.

## 20. DOCUMENT CONTROL

Version: 1.0
 Review Cycle: Quarterly or upon material change

Approvals Required:

- Product

- Design

- Legal

- Compliance

- Engineering

- Executive
