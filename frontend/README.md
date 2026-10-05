# Zoikorum Frontend

Web client for the Zoikorum marketplace. It talks to the backend only through the
versioned REST API in `../backend` (`/v1/...`). Business rules, state machines and
policy checks live in the backend. The UI must never be the only line of enforcement.

Status: **not scaffolded yet.** The backend is being built first; this folder
reserves the structure the wireframe documents describe.

## Screens (from the wireframe docs) → backend domains

| Screen (wireframe doc) | Route | Backend APIs |
|---|---|---|
| Homepage | `/` | marketplace taxonomy, search |
| Category page (Finance & Accounting) | `/c/:category` | `GET /v1/search/professionals` (facets, "why this result") |
| Professional profile | `/p/:professionalId` | professional, trust, verification summary |
| Request Proposal & Engagement flow | `/engage/:professionalId` | proposal, contract, escrow, payments |
| Buyer dashboard & engagements | `/buyer` | analytics projections, contract, escrow, messaging |
| Professional onboarding & verification | `/join` | identity, professional, firm, verification, trust |
| Professional dashboard & service mgmt | `/pro` | professional offerings, proposal, contract, payments |
| Payments, escrow & release controls | `/engagements/:id/payments` | escrow, payments, policy approvals |
| Dispute resolution | `/disputes/:id` | dispute, escrow, messaging |
| Enterprise policy profiles & approvals | `/enterprise/policies` | buyer orgs, policy |
| Trust & Safety / enforcement (internal) | `/ops` | admin, verification review queues, audit |

## Planned structure

```
frontend/
  src/
    api/          typed API client generated from the backend OpenAPI spec
    features/     one folder per screen above
    components/   shared UI (trust tier badge, money, status badges, timelines)
    auth/         token storage, refresh, step-up MFA prompt
```

UX rules carried through from the docs: ≤3 primary actions per screen, a "Why am I
seeing this?" explanation on every ranked result and enforcement notice, no colour-only
signals (WCAG 2.2 AA minimum), and under 400ms feedback on every action.
