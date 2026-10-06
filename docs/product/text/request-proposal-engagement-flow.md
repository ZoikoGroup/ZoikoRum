<!-- Generated from request-proposal-engagement-flow.docx — edit the .docx, not this file. -->

# Request Proposal & Engagement Flow

ZOIKORUM — REQUEST PROPOSAL & ENGAGEMENT FLOW WIREFRAME v1.0

FORTUNE-10 GOVERNED ENGAGEMENT CREATION SYSTEM

# Document Control

| Field | Value |
|---|---|
| Platform | Zoikorum |
| Artifact | Request Proposal & Engagement Flow (Canonical) |
| Category | Global Marketplace for Governed Professional Services |
| Document Classification | Production-Ready Interaction Wireframe |
| Audience | Buyers · Professionals · Firms · Enterprise Buyers · Procurement · Legal · Compliance · Product · Design · Engineering |
| Standard | Fortune 10 · Tier-1 Marketplace UX · Governance-First |
| Status | Production-Ready |
| Version | 1.0 |
| Last Updated | January 22, 2026 |

# 1. Executive Intent

The Request Proposal & Engagement Flow is the conversion spine of Zoikorum. It transforms marketplace discovery into a governed engagement that is contract-ready, payment-protected, and audit-recorded before work begins. The flow must feel fast and familiar while enforcing governance as protection—not bureaucracy.

This flow is not a contact form. It is not informal messaging. It is a controlled engagement creation system.

# 2. Non-Negotiable UX / UI Laws (Enforced)

- Jakob’s Law — patterns mirror familiar proposal + checkout flows (Upwork/Fiverr) while adding governance signals.

- Hick’s Law — each step presents no more than 3 primary choices; advanced options are hidden.

- Miller’s Law — information chunking: 5–7 visible objects per panel; long lists are collapsed.

- Fitts’s Law — primary CTAs are large (min 48px height desktop, 56px mobile) and placed consistently.

- Progressive Disclosure — complexity appears only after intent (request submitted) and only when relevant.

- Recognition over Recall — prefilled fields, templates, pill summaries, and “Edit” links avoid memory burden.

- Error Prevention — validation, conflict detection, and locked states prevent ambiguous commitments.

- Serial Position Effect — the most critical messages appear at the beginning and end of each step.

- Aesthetic–Usability Effect — clean hierarchy, whitespace, and calm reassurance reduce perceived risk.

- Doherty Threshold — feedback for any user action occurs within 400ms (skeleton states where necessary).

- Peak-End Rule — the flow ends with a strong confirmation, clear next steps, and risk reassurance.

- Consistency & Standards — identical terminology and components across buyer/professional/enterprise contexts.

- Accessibility (WCAG 2.2 AAA target) — keyboard navigation, semantic structure, focus indicators, contrast, and assistive labels.

# 3. System Map (End-to-End)

Entry → Request (Buyer) → Proposal (Professional) → Review (Buyer) → Agreement Finalization → Payment Protection Setup → Engagement Activation → Redirect to Dashboards.

No dead ends. Every state presents an explanation, a next action, and a support path.

# 4. Entry Points & Gating

Supported entry points:

- Professional Profile — Primary CTA: Request Proposal

- Category Results — Card CTA: Request Proposal

- Comparison View — Request Proposal for selected professional(s)

- Saved Professionals — Request Proposal

- Buyer Dashboard — Post Requirement / Request Proposal

Identity gating rules:

- Anonymous users may browse; proposal submission requires sign-in.

- If user is not signed in, the system captures intent first (opens flow), then prompts sign-in at submission.

- Enterprise accounts may enforce additional buyer verification (policy dependent).

# 5. Global Flow UI Frame (Persistent Elements)

All steps share the same shell to preserve orientation (Jakob’s Law).

- Step indicator (1–6) with short labels; shows progress and supports back navigation.

- Persistent ‘Save Draft’ for buyer (when signed in) from Step 1 onward.

- Sticky right-side ‘Engagement Summary’ (desktop) / collapsible summary drawer (mobile).

- Persistent governance strip: Verified Identity · Contract-Ready · Payment Protection · Audit Record.

- Help entry: ‘Need help?’ opens contextual article or support.

# 6. Step 1 — Request Proposal (Buyer Intent Capture)

Objective: capture the buyer’s need with minimal friction while structuring for clarity.

Layout: single column form (desktop modal / mobile full-screen). One primary CTA.

Fields (Required unless stated):

- Service Needed (prefilled from profile/service card; editable)

- Engagement Type (radio): Advisory / Project / Retainer / Fractional

- Brief Objective (single sentence) — 300 character limit with counter

- Details (textarea) — 1,200 character limit with guidance prompts

- Desired Start Date (date picker)

- Estimated Duration (dropdown): 1–2 weeks / 3–6 weeks / 2–3 months / 3–6 months / Ongoing

Optional (collapsed by default):

- Budget Range (slider)

- Delivery Mode: Remote / On-site / Hybrid (selecting On-site triggers location capture)

- Confidentiality: NDA required before proposal (toggle)

- Attachments (optional) — max 3 files; virus scanned; shown as thumbnails with remove action

Microcopy standards (plain language):

- Prompt example: “Try: ‘Need help preparing audited financials for year-end close.’”

- NDA toggle note: “You can request an NDA before discussing sensitive details.”

- Budget note: “Optional — helps professionals propose accurately.”

Validation & error prevention:

- Objective required; must not be blank; inline error appears on blur.

- Date cannot be in the past; duration required.

- Attachment types restricted (PDF/DOCX/XLSX/PNG/JPG).

Primary CTA: Send Request (48px height desktop; full-width 56px mobile).

Secondary actions: Save Draft · Cancel.

# 7. Step 1 Confirmation State (Instant Feedback)

On submit, show immediate confirmation within 400ms (Doherty Threshold).

- Success message: “Request sent. You’ll be notified when the professional responds.”

- Next actions: Track Request · Request Another Proposal · Browse Similar Professionals

- Auto-create request thread in the engagement workspace; status = ‘Awaiting Proposal’.

# 8. Step 2 — Professional Proposal Creation

Objective: enable professionals to respond with structured proposals aligned to governance controls.

Professional sees buyer request in read-only format (prevents misunderstanding).

Proposal Builder sections:

- Proposal Summary — short message to buyer (500 characters)

- Scope Alignment — confirm deliverables OR propose edits (tracked as suggested changes)

- Deliverables — structured list; must map to milestones

- Timeline — start date, milestone dates, completion date

- Pricing — hourly/fixed/retainer; itemized if milestone-based

- Assumptions & Exclusions — structured bullets; prevents scope creep

- Optional Attachments — portfolio items or supporting docs (policy gated)

Governance signals (always visible):

- Contract will be generated from the accepted proposal scope.

- Payment protection options are available and will be configured by the buyer.

- Dispute resolution pathway exists; all actions create an audit record.

Professional validation:

- Proposal cannot be submitted without at least one deliverable and one price.

- If buyer required NDA, professional must accept NDA before viewing attachments or sensitive fields.

- If buyer policy requires Tier A, system blocks submission if professional is not eligible.

Primary CTA: Submit Proposal. Secondary: Save Draft · Decline Request.

# 9. Step 3 — Proposal Review (Buyer)

Objective: enable fast, confident evaluation with minimal cognitive load.

UI: proposal cards (grid) with a consistent schema; optional comparison (max 3).

Proposal card includes:

- Professional name + trust tier badge

- Scope snapshot (top 3 deliverables, +X more)

- Timeline summary

- Price summary (range or total) + pricing model

- Engagement readiness icons: Contract-ready · Payment protection · Audit record

- CTA group (max 3): View Details · Request Revision · Accept Proposal

Buyer actions:

- Accept Proposal — primary action; triggers agreement finalization.

- Request Revision — opens structured change request (no free-form ambiguity).

- Decline — optional reason; non-punitive; improves marketplace signals.

Decision support:

- Explainable ‘Why this proposal matches’ tooltip (recognition > recall).

- Highlight deltas from buyer request (scope/price/timeline) using diff blocks.

# 10. Step 4 — Agreement Finalization (Contract-First)

Objective: convert accepted proposal into enforceable engagement terms.

Agreement screen is read-only by default and uses progressive disclosure for legal text.

Visible summary panel (always visible):

- Parties (buyer entity + professional/firm)

- Scope and deliverables

- Milestones and acceptance criteria

- Pricing and payment schedule

- Change order rules

- Dispute process reference

Expandable sections (collapsed):

- Standard terms (platform template)

- Data handling / confidentiality (if applicable)

- Jurisdiction and governing law (policy dependent)

Signature model:

- Buyer signs first (or enterprise approval workflow triggers).

- Professional countersigns.

- Timestamped signature receipts stored in engagement dossier.

Primary CTA: Continue to Payment Protection Setup.

Secondary: Request Change Order (returns to structured revision).

# 11. Step 5 — Payment Protection Setup

Objective: configure safe payment mechanics without confusion.

Payment options (policy dependent):

- Milestone Funding — fund total or per milestone; releases require acceptance.

- Retainer Funding — monthly cycle with acceptance gates (where applicable).

- Fixed Release — single release upon completion acceptance.

Payment summary panel (always visible):

- Total amount

- Funds to be held / funded now

- Release conditions (plain language)

- Approver (enterprise role, if applicable)

- Dispute hold behavior (plain language)

Confirmations and error prevention:

- Final review modal: “You are about to fund protected payment for this engagement.”

- If funding fails, provide retry + alternate method + support path.

Primary CTA: Fund & Activate Engagement.

# 12. Step 6 — Engagement Activated (Strong End State)

Objective: deliver a confident, reassuring end state (Peak-End Rule).

Activation screen displays:

- Engagement Status: Active

- Engagement ID

- Next milestone and due date

- Where to collaborate: engagement workspace link

- What’s protected: contract + payment + audit record

Primary CTAs: Go to Buyer Dashboard · View Engagement Workspace.

Secondary: Invite team members (enterprise) · Request additional proposals.

# 13. Engagement Workspace (Created Automatically)

Immediately after activation, the system creates a governed workspace.

Workspace tabs:

- Overview — key terms, contacts, next milestone

- Scope — read-only contract scope + versions

- Milestones — submissions, acceptance, revision requests

- Messages — engagement-threaded messages (no off-platform dependency)

- Files — versioned artifacts with access controls

- Payments — ledger view, release history, holds

- Activity Log — immutable timeline of events

# 14. Change Orders (Scope Versioning)

Objective: prevent scope creep and protect both sides.

Change request initiation (buyer or professional):

- Select change type: add deliverable / modify deliverable / extend timeline / pricing change

- Structured delta form with before/after preview

- Impact summary: time + cost + milestone adjustments

- Approval required by both parties; enterprise may require additional approver

- All changes produce a new version number and immutable record

# 15. Dispute Entry Point (Branch, Not Default)

Dispute path exists but is not foregrounded unless triggered.

Dispute triggers:

- Buyer rejects deliverable and escalation requested

- Professional claims non-payment or unfair rejection

- Policy violation flags (rare)

Dispute initiation UI: structured reason + evidence upload + timeline. Funds held per protection terms.

# 16. Error & Edge States (No Dead Ends)

Conflict detection examples:

- Tier conflict: Buyer requires Tier A; selected professional is Tier B → system blocks acceptance and offers alternatives.

- Jurisdiction conflict: Professional not eligible for buyer’s region → block activation; suggest eligible professionals.

- NDA required but not accepted → block viewing attachments; provide accept NDA path.

- Payment method failure → retry options + support escalation; do not lose state.

Empty states:

- No proposal received: suggest requesting additional professionals; provide timeline and reminders.

- Proposal expired: notify and allow re-request with preserved scope.

# 17. Notifications & Timing

Notification channels: in-app + email (optional) + enterprise webhook (optional).

Key notifications:

- Request sent

- Proposal received

- Revision requested/received

- Agreement ready for signature

- Counter-sign completed

- Payment funded

- Milestone submitted

- Milestone approved / revision requested

- Engagement completed

- Dispute opened/updated/closed

# 18. Audit & Record Generation (System of Record)

Every step logs: actor, timestamp, action, object, state transition, and attachments hash.

Generated outputs:

- Request Record (buyer intent + initial scope)

- Proposal Record (professional response + pricing)

- Executed Agreement (signed)

- Payment Protection Ledger (funds held/released)

- Milestone Acceptance Log

- Change Order History

- Dispute Record (if applicable)

- Export Pack (PDF/CSV/JSON) with attestations

# 19. Performance & Interaction Standards

- First Contentful Paint: < 1.2s

- Time to Interactive: < 3.5s

- Core Web Vitals: CLS < 0.1

- Any action feedback: < 400ms (Doherty Threshold)

- Autosave cadence: within 1s of pause in typing

# 20. Accessibility (WCAG 2.2 AAA Target)

- All fields have explicit labels and inline help.

- Keyboard navigation for steps, buttons, modals.

- Focus states are always visible and high contrast.

- Color is never the only indicator (icons + text + patterns).

- Screen-reader friendly: semantic headings and ARIA where needed.

# 21. Analytics & Funnel Instrumentation

Primary funnel events (buyer):

- Clicked Request Proposal

- Completed Step 1 (request submitted)

- Viewed proposal

- Accepted proposal

- Signed agreement

- Funded payment protection

- Engagement activated

Primary funnel events (professional):

- Opened request

- Saved proposal draft

- Submitted proposal

- Viewed revision request

- Countersigned agreement

- Submitted milestone

Quality metrics: abandonment per step; time per step; revision rate; dispute incidence; time-to-activation.

# 22. Legal Positioning

Zoikorum provides marketplace infrastructure, verification, contracting facilitation, and payment protection mechanisms. Professional services are delivered by independent third-party professionals and firms. Zoikorum does not provide regulated professional services.

# 23. Document Control

Review Cycle: Quarterly or upon material change.

Approvals Required: Product · Design · Legal · Compliance · Engineering · Executive.
