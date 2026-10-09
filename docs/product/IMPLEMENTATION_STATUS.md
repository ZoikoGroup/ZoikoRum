# Repository implementation assessment

> Historical audit: this snapshot predates the merged Steps 12–18 and provider work. Its classifications are not current completion claims. See [current implementation status](../../backend/docs/CURRENT_STATUS.md) and [Steps 12–18](../../backend/docs/STEPS_12_18_IMPLEMENTATION.md).


> Historical assessment of the checkout before the dev merge. The merge now brings in Step 9 disputes, stored uploads and payment operations; entries describing those as absent are superseded. Messaging and change orders are retained on maruthi_dev. This document is not a fresh audit of the merged product.

Assessment: 7 October 2026. Source requirements: the Word documents in `docs/product/`, readable extracts in `docs/product/text/`, and `backend/docs/BUILD_SPEC.md`. This describes the current checkout, including uncommitted work. A screen, facade, model or passing test alone does not establish complete implementation.

| Step | Classification | Existing behavior and remaining work |
| --- | --- | --- |
| 0 Foundation | NEEDS FINISHING | Postgres domain schemas, modular backend, migrations, transactional events, timers, audit chain and CI exist. Validate current migrations and architecture after the new modules. |
| 1 Login and roles | NEEDS FINISHING | Shared login, signup, persona dashboards, staff roles, MFA and reset exist. Connect real email delivery and account enforcement. |
| 2 Organisations and firms | COMPLETELY IMPLEMENTED within organisation-management scope | Profiles, live memberships, invitations, roles, business units, cost centres and configured spend limits exist. Policy-driven buying is separately incomplete in Step 12. |
| 3 Professional profile | COMPLETELY IMPLEMENTED within profile-management scope | Finance & Accounting taxonomy, profile editing, offerings, pricing, publishing and photos exist. Outcome-based reputation is separately incomplete in Step 15. |
| 4 Verification and trust | NEEDS FINISHING | Evidence metadata/review, dimensions, tiers and expiry timers exist. Evidence bytes are not stored by the submission API. Missing completed-work/review metrics, dispute effects, enforcement and production provider integrations. |
| 5 Search and discovery | NEEDS FINISHING | Filters, ranking, result explanations and saved professionals exist. Missing enterprise eligibility, outcome signals and AI intent extraction. |
| 5a Customer portal | NEEDS FINISHING | Management screens and core domain integrations exist. Policies, disputes, notifications and reporting still lack complete workflows. |
| 6 Requests and proposals | NEEDS FINISHING | Requests, NDA, revisions, decline and acceptance exist. Request files remain metadata-only; enterprise policies and approvals are incomplete. |
| 7 Contracts | NEEDS FINISHING | Generation, ordered MFA signatures, milestones and immutable revision history exist. Missing policy pinning and real dispute integration; submission files remain metadata-only. |
| 8 Escrow and payments | NEEDS FINISHING | Funding, ledger allocations, release, fees, invoices and payouts work through the test adapter. Missing production provider, policy approvals and real dispute integration. |
| 9 Disputes and mediation | NOT IMPLEMENTED | Dispute facade raises `NotImplementedError`; no actual aggregate, API or screens. Messaging dispute projections are not this module. |
| 10 Messaging | NEEDS FINISHING | Backend, migrations, immutable messages/files, NDA/live participant checks, unread positions, abuse signals, lifecycle notes and three-panel frontend exist. Final tests/migration verification and actual Step 9 integration remain. |
| 11 Change orders | NEEDS FINISHING | Other-party decisions, material re-signing, immutable revisions, escrow amendment handling and frontend exist. Finish verification and enterprise policy integration. |
| 12 Enterprise policies and approvals | NOT IMPLEMENTED | Facade is a stub. Missing versioned profiles, evaluations, approvals, exceptions, commercial hooks, eligibility and screens. |
| 13 Notifications | NOT IMPLEMENTED | Missing persisted inbox/preferences, lifecycle email delivery, retries, reminders and enterprise webhooks. Existing tokens are not email delivery. |
| 14 Dispute extras | NOT IMPLEMENTED | Missing appeals, automatic deadline disputes and trust effects; Step 9 is a prerequisite. |
| 15 Reviews and outcomes | NOT IMPLEMENTED | Missing verified engagement reviews, outcome metrics and trust/search projections. |
| 16 AI assistance | NOT IMPLEMENTED | Facade is a stub. Missing approved prompts, audited advisory drafting/summaries, provider/fallback distinction and screens. |
| 17 Reports and analytics | NOT IMPLEMENTED | Some screens show totals; documented currency-safe reports, projections, exports, rebuilds and platform analytics are missing. |
| 18 Admin and safety | NOT IMPLEMENTED within enforcement scope | Staff-role administration exists. Missing enforcement cases, independent decisions, six-field notices, appeals, restrictions, risk triage, dead-letter operations and regulator exports. |

## Files and architecture

Backend: `backend/src/zoikorum/domains/`; shared infrastructure: `backend/src/zoikorum/shared/`; migrations: `backend/alembic/versions/`; tests: `backend/tests/`. Frontend: `frontend/src/api/`, `frontend/src/pages/`, `frontend/src/components/`. Messaging: `domains/messaging/`, `tests/test_messaging.py`, `frontend/src/api/messaging.ts`, `frontend/src/pages/customer/Pipeline.tsx`. Change orders: `domains/contract/`, `domains/escrow/`, `tests/test_contract.py`, `frontend/src/pages/Engagements.tsx`.

Architecture: FastAPI/async SQLAlchemy/Postgres modular monolith, one schema per domain, facade-based cross-domain reads and transactional event-based workflows; React/TypeScript frontend with shared auth and API infrastructure. Cross-schema foreign keys must not replace facade contracts.

Customer and professional request-to-funded-work paths exist. Firm/enterprise organisation management exists, but policy-governed enterprise procurement is incomplete. Staff identity/verification tools exist; mediator, dispute decisions, enforcement and regulator workflows are incomplete. No role has the entire documented workflow implemented end to end.

## Ordered development gates

1. Finish Step 10 tests and migrations: both roles, live membership/NDA, file bytes/versions, retries, pagination/read positions and multiple/reordered dispute events.
2. Verify Step 11: independent decisions, material re-signing, immutable before/after versions, signature order, rejection and escrow adjustments.
3. Implement Step 12: versioned profiles, most-restrictive evaluations, sequential/parallel approvals, separation of duties, expiring exceptions, pinned policy versions and all documented action hooks/screens.
4. Implement Step 13: real persisted notifications, preferences, adapters, retryable delivery, reminders and signed webhook deliveries. Label console/test delivery accurately.
5. Implement the absent Step 9 before Step 14: evidence, frozen funds, structured resolution, mediation, independent platform decisions, financial enforcement and role-specific screens.
6. Implement Step 14 appeals, deadline triggers and dispute outcomes; replace synthetic event tests with actual dispute-to-messaging tests.
7. Implement Step 15 completed-work reviews, outcome statistics and explainable trust/search integration.
8. Implement Step 16 advisory AI, approved prompts, inference audit, provider/fallback behavior and user confirmation; AI never decides disputes or moves money.
9. Implement Step 17 authorised currency-safe reporting, exports, rebuildable projections and staleness indicators.
10. Implement Step 18 enforcement, notices, independent approval/appeals, time-bound restrictions, risk triage, dead-letter replay and regulator exports. Restrictions must affect existing commands.
11. Revisit dependent earlier steps and run complete backend, frontend, migration and role-wise end-to-end validation.

## Ambiguities and limitations

- The roadmap shorthand says timeline changes re-sign. `BUILD_SPEC.md` distinguishes material scope/pricing changes (re-sign) from non-material timeline changes (mutual approval/direct amendment); the engineering architecture requires re-signing for material amendments. Do not silently classify changes affecting scope or commercial value as non-material.
- Policy facade and configuration use different default acceptance/signature windows. Step 12 must resolve and persist effective settings.
- Calls, tasks, schedule and notes shown in the reference image are not implemented services; they must not appear as working controls.
- Fake payments, local file storage and console/token-based email support development. They do not establish production integration.
- The contract-history migration backfills the currently stored version. It cannot recover historical versions that were never retained; do not invent earlier contract documents.
- `frontend/src/pages/Engagements.tsx` currently sums active contract values across currencies and displays the first currency. Step 17 must group monetary totals by currency rather than imply a conversion.

## Verification recorded during this assessment

- Architecture, messaging and contract checks: 16 passed before the final messaging refinements.
- Expanded architecture/messaging regression checks: 8 passed, including live member removal, private uploads, actual bytes, versions, pagination, read positions and delayed dispute events.
- Frontend production builds passed. Existing bundle-size warnings remain; lint reported warnings in existing components.
- Local Alembic upgrade succeeded after fixing the async driver's multi-command migration error. The drift check reported no new upgrade operations after the naming correction.
- A separate unread-summary integration check passed after wiring the sidebar badge.
- The entire migration chain upgraded a fresh database successfully; its drift check also reported no new upgrade operations.
- Full backend regression is still running; this document does not claim its result in advance.

Overall: substantial core marketplace implementation; messaging/change orders are under verification. Enterprise governance, dispute management and the remaining operating layers require substantial implementation. The product is not complete.
