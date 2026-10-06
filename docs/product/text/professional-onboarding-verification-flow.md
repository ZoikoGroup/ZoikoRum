<!-- Generated from professional-onboarding-verification-flow.docx — edit the .docx, not this file. -->

# Professional Onboarding & Verification Flow

ZOIKORUM — PROFESSIONAL ONBOARDING & VERIFICATION FLOW WIREFRAME v1.0

Governed Entry, Credential Validation & Trust Establishment System

# Document Control

- Platform: Zoikorum

- Artifact: Professional Onboarding & Verification Flow

- Category: Global Marketplace for Governed Professional Services

- Document Classification: Production-Ready Interaction Wireframe

- Audience: Independent Professionals · Firms · Compliance · Legal · Product · Design · Engineering · Enterprise Buyers

- Last Updated: January 22, 2026

# 0. Executive Intent

Professional onboarding is where Zoikorum earns trust at scale. This flow must feel fast and welcoming while producing a defensible, reviewable trust outcome for buyers, enterprises, and regulators.

Onboarding must: (1) enable rapid marketplace participation, (2) establish transparent verification status, (3) enforce eligibility where required, (4) prevent misrepresentation, and (5) preserve user dignity.

This is not a compliance dump. It is a progressive trust-establishment system: AI assists; policy constrains; humans decide.

# 1. Non‑Negotiable UX / UI Laws (Enforced)

- Jakob’s Law — familiar signup, checklist, and KYC patterns; no exotic flows.

- Hick’s Law — ≤3 primary decisions per screen; advanced options hidden.

- Miller’s Law — information chunking; ≤7 visible elements per panel; long lists collapse.

- Fitts’s Law — large CTAs (48px desktop, 56px mobile), consistent placement.

- Progressive Disclosure — only show deeper checks when profession/policy requires them.

- Recognition over Recall — checklists, templates, previews, and persistent summaries.

- Error Prevention — inline validation, conflict detection, confirmation modals for irreversible actions.

- Serial Position Effect — key risk/benefit statements appear first and last in each step.

- Aesthetic–Usability Effect — calm, minimal UI reduces perceived friction and increases completion.

- Doherty Threshold — system feedback <400ms; skeleton states when needed.

- Peak‑End Rule — clear completion, next steps, and reassurance at the end.

- WCAG 2.2 AAA target — keyboard navigation, contrast, focus states, screen reader semantics.

# 2. System Map (End‑to‑End)

Two onboarding tracks share one framework: Individual Professional and Firm. The first decision is track selection, then the system adapts.

High-level sequence:

- Entry → Choose Track (Individual / Firm) → Account Creation → Profile Basics → Services & Specializations → Pricing & Availability (light) → Verification Checklist → Identity Verification → Credentials Verification (conditional) → Jurisdiction & Eligibility → Optional Enhancements (insurance, background checks) → Trust Tier Assignment → Profile Activation → Dashboard Handoff

No dead ends. Every failure state presents: explanation, resolution path, and support escalation.

# 3. Entry Points & Gating

Entry points:

- Homepage: Join as a Professional / Join as a Firm

- Category pages: Join

- Invite links: enterprise/firm onboarding invite

- Request Proposal gating: “Complete verification to proceed”

Gating rules (canonical):

- Browsing is open; proposal submission as a professional requires sign-in.

- Profile publishing is permitted at Tier C (Discovery) with strict limitations.

- Executing contract-required engagements requires Tier B or Tier A depending on enterprise/buyer policy.

- Category-specific regulated professions may require Tier A before profile is discoverable beyond limited preview (policy-driven).

# 4. Global Onboarding Shell (Persistent Frame)

The onboarding shell remains constant across steps to preserve orientation and reduce cognitive load.

- Top-left: Zoikorum logo (returns to home after confirmation modal).

- Top-center: Stepper (max 7 steps) with labels and completion state.

- Top-right: Save & Exit, Help, Language selector (Phase 1: English variants).

- Main: single primary task panel; secondary context on right (desktop) / collapsible drawer (mobile).

- Right/Drawer: Verification checklist + Trust Tier preview + ‘Why we ask this’ contextual explanations.

- Footer strip: Privacy reassurance (Encrypted · Used for verification only · Access controlled).

# 5. Step 0 — Choose Track (Individual vs Firm)

Objective: establish onboarding path with one simple choice.

UI: two large cards with icons, 2–3 bullets each (Hick’s Law).

- Card A: I’m an Individual Professional — “Offer services as an independent professional.”

- Card B: I’m a Firm — “List a firm and manage multiple professionals under one account.”

CTA: Continue (primary). Secondary: Learn the difference (link opens short modal).

Edge case: If invite link specifies track, this step is auto-selected and shown as read-only confirmation.

# 6. Step 1 — Account Creation

Objective: create secure account with minimal friction.

Fields (required):

- Email

- Password (strength meter + requirements)

- Country of residence/incorporation

- Agree to Terms (checkbox; link opens in new tab)

Optional: referral / invite code (collapsed).

CTAs: Create account (primary) · Sign in (secondary).

States & behaviors:

- Inline validation on blur; no full-page error dumps.

- Email verification required before profile can be published.

- If user abandons, persist draft for 7 days (anonymous) or indefinitely (signed-in).

Security & UX:

- MFA prompt appears after initial sign-in (optional for standard; required for enterprise-ready designation).

- Passwordless option (future): shown as ‘Coming soon’ only if enabled; otherwise omitted.

# 7. Step 2 — Profile Basics (Identity & Positioning)

Objective: capture accurate identity and primary professional positioning without marketing fluff.

Individual required fields:

- Legal name (as on ID)

- Display name (defaults to legal name; editable)

- Profile photo (required before publish; quality guidance and cropping tool)

- Primary category (e.g., Finance & Accounting)

- Primary role title (selected from controlled list; searchable)

- Years of experience (range selector)

Firm required fields:

- Registered legal name

- Trading name (optional)

- Company registration number (jurisdiction-specific formatting)

- Primary category focus

- Headquarters country

- Firm size band (1–5, 6–20, 21–100, 100+)

Optional (collapsed):

- Short bio (max 300 words; readability scoring; no superlatives)

- Languages

- Website / portfolio link (policy scan for safety)

Copy rules (quality control):

- No guarantees, no unverified claims, no ‘best/leading/top’ language.

- If claims imply regulated capacity, require credential verification before display.

# 8. Step 3 — Services & Specializations (Taxonomy‑First)

Objective: ensure discoverability using controlled taxonomy; prevent free-form spam.

UI pattern: specialization picker with search + expandable group cards (Miller’s Law).

Rules:

- Select 1 primary specialization and up to 5 secondary specializations.

- Specializations must come from Zoikorum taxonomy; no free text.

- Each specialization includes a short system description and typical deliverables (preview).

Deliverables templates:

- User selects common deliverables templates per specialization (optional).

- Templates help proposal accuracy and reduce time-to-proposal.

CTAs: Continue (primary) · Save & Exit (secondary).

# 9. Step 4 — Pricing, Availability & Engagement Preferences (Lightweight)

Objective: allow buyers to understand fit while avoiding premature commitments.

Fields:

- Engagement types offered: Advisory / Project / Retainer / Fractional (multi-select).

- Delivery mode: Remote / On-site / Hybrid (on-site triggers location regions).

- Indicative pricing model: Hourly / Fixed / Retainer / Custom (not binding).

- Availability: Available now / 2 weeks / 1 month / Not specified.

Progressive disclosure: Budget ranges and rate cards are optional and hidden.

Fairness rule: Do not penalize professionals for withholding pricing; instead show ‘Quote on request’.

# 10. Step 5 — Verification Checklist (Transparency Layer)

Objective: make verification understandable, controllable, and motivating.

UI: checklist panel with status chips, ETA, and “Why we ask this” tooltips.

Canonical checklist items:

- Email confirmed (required)

- Identity verification (required for Tier B+)

- Credential verification (conditional)

- Jurisdiction eligibility (conditional)

- Optional: background screening (policy-dependent)

- Optional: insurance verification (policy-dependent)

Motivation and disclosure:

- Show what the professional can do at each tier (capabilities matrix).

- Show ‘Unlocks’ for the next tier (e.g., “Tier A unlocks enterprise and regulated engagements”).

- Show estimated completion times per item.

# 11. Step 6 — Identity Verification (Mandatory for Tier B+)

Objective: establish real identity for trust and fraud prevention.

Individual flow UI:

- Choose document type (passport / national ID / driver’s license where supported)

- Capture document (camera flow with edge detection)

- Live selfie + liveness check

- Confirm extracted details (read-only with corrections request)

Firm flow UI:

- Upload incorporation evidence (jurisdiction-specific)

- Verify authorized representative identity (same as individual identity flow)

- Confirm beneficial ownership declaration (policy-dependent; may be deferred)

States: Pending · Verified · Needs action · Failed.

Error prevention:

- Blurry photo detection with immediate retake prompts.

- Mismatch handling: ‘Name differs’ → guided correction + support escalation.

- Drop-off recovery: resume from last successful sub-step.

# 12. Step 7 — Credential Verification (Conditional & Profession‑Aware)

Credential verification triggers based on: category, selected specialization, buyer policy, enterprise requirements, or regulatory markers.

Credential types:

- Licenses (e.g., CPA, ACA, Bar admission, Medical license)

- Certifications (e.g., ACCA, CFA, CIA)

- Memberships (e.g., professional bodies)

- Academic degrees (optional; displayed only if verified or user-asserted with label)

UI pattern: guided credential wizard (one credential at a time) to prevent overwhelm.

Per credential fields:

- Credential name (searchable list)

- Issuing body

- Credential ID / registration number

- Jurisdiction/state/country

- Issue and expiry date (if applicable)

- Evidence upload or verification link

Verification outcomes:

- Validated (display ‘Validated’)

- Pending (display ‘Pending’)

- Not applicable (display ‘Not applicable’)

- Failed (display ‘Not validated’ with reason; hide credential claim until resolved)

# 13. Jurisdiction & Eligibility (Policy‑Bound)

Objective: prevent illegal engagements and set clear boundaries.

Inputs:

- Where you can serve: countries/regions (multi-select)

- Where you are licensed (if applicable)

- Restrictions: sanctions screening flags where required (system-run)

- Data handling constraints (e.g., ‘Can handle regulated data’ toggle, enterprise-only).

System behaviors:

- If user selects cross-border service, show compliance reminder and require acknowledgment.

- If credentials are jurisdiction-limited, the system warns and auto-labels listings by eligible regions.

- Buyer location vs professional eligibility mismatch is surfaced early in discovery and at proposal time.

# 14. Optional Enhancements (Policy‑Dependent)

These steps appear only when needed (Progressive Disclosure).

- Background checks (enhanced): shown for high-stakes categories; requires consent; results summarized as pass/fail bands.

- Insurance verification: professional liability insurance upload/verification; shown only if enterprise policy requires it.

- Security attestation: for enterprise-ready designation (basic questionnaire; not a certification).

# 15. Trust Tier Assignment (Explainable & Reviewable)

Tier logic is system-determined and explainable. The user is shown ‘why’ in plain language.

Tier definitions (canonical):

- Tier A — Fully Verified: identity verified + required credentials validated (where applicable) + jurisdiction eligibility confirmed (where applicable) + any required checks completed.

- Tier B — Verified Identity: identity verified + baseline eligibility checks; credentials may be pending/not required.

- Tier C — Discovery: profile created; verification incomplete; limited engagement capability.

Capabilities matrix (displayed):

- Tier C: profile visible with limited signals; can receive interest; cannot activate protected engagements until Tier B+ (policy dependent).

- Tier B: can submit proposals and activate standard engagements; may be excluded from enterprise policies requiring Tier A.

- Tier A: eligible for enterprise-ready and regulated engagement modes; highest trust badge.

# 16. Human Review & SLA (Compliance Operations)

Some steps require human review (especially Tier A approvals). This must be transparent and time-bounded.

- Queue status visible: ‘In review’ with estimated time window.

- Review outcomes: Approved / Needs more info / Rejected with reason (and appeal path).

- SLA targets: Identity review <24 hours (median); Credential review <48 hours (median) where manual; background checks per provider timelines.

- Escalation: ‘Request review help’ opens support ticket with prefilled context.

# 17. Profile Publishing & Disclosure Rules

Publishing is the moment of marketplace exposure and must enforce truthfulness.

- Before publish: mandatory preview screen shows exactly how the profile will appear to buyers.

- Unverified claims are labeled as ‘Self-reported’ or hidden if policy requires validation.

- Any credential that fails validation is removed from public display until resolved.

- Professional must confirm ‘Information is accurate’ attestation to publish.

# 18. Completion Screen (Peak‑End Rule)

The final state must feel rewarding, clear, and safe.

Completion UI shows:

- Your Trust Tier badge and what it means

- What you can do now (3 bullets)

- Recommended next actions (2–3)

- Where to manage requests (link to Professional Dashboard)

CTAs: Go to Dashboard (primary) · Improve verification (secondary) · View profile (tertiary).

# 19. Notifications, Reminders & Re‑Engagement

Notifications must be helpful, not coercive.

- Verification status updates (in-app + email optional)

- Credential expiry reminders (30/14/7 days)

- Tier upgrade nudges triggered only when blocked by buyer policy (contextual)

- Security alerts: new device sign-in, MFA prompts

# 20. Edge Cases & Error States (No Dead Ends)

- Document unreadable → guided retake + tips + auto-capture

- Name mismatch → guided correction + support escalation

- Credential not found → manual review request + alternative evidence

- Jurisdiction conflict → clear explanation + adjust eligibility settings

- User abandons mid-flow → autosave + resume prompt on return

- Duplicate account suspected → merge flow with support path

- Firm rep not authorized → request new authorized rep verification

# 21. Accessibility & Inclusive Design

- Keyboard navigable stepper; all CTAs reachable via tab order

- Focus states always visible; no color-only cues

- Captions/instructions for camera flows; alternative upload path

- Error messages are plain language and include resolution steps

# 22. Performance Standards

- First Contentful Paint < 1.2s

- Time to Interactive < 3.5s

- Autosave within 1s after typing stops

- Any button/action feedback < 400ms

# 23. Audit Logging & Data Governance

Every verification action produces an audit record: actor, timestamp, action, and status change.

- Evidence files stored encrypted; access-controlled; least-privilege

- Retention configurable (enterprise policies may require longer retention)

- Right-to-access and deletion workflows supported where applicable (policy/jurisdiction)

# 24. Legal Positioning

Zoikorum performs verification to establish eligibility and trust signals. Verification does not constitute licensing, endorsement, or certification of professional services. Professionals remain independently responsible for complying with applicable laws and professional standards.

# 25. Analytics & Success Metrics

Product KPIs:

- Onboarding completion rate (target ≥ 65% for individuals; ≥ 55% for firms)

- Identity verification completion rate (target ≥ 85% of starters)

- Tier upgrade rate (C→B, B→A) by category

- Median time to publish (target: <10 minutes for Tier C; <20 minutes for Tier B; Tier A varies by credential)

- Drop-off points by step (heatmap-informed optimization)

- Support ticket rate per 1,000 onboardings (quality metric)

# 26. Document Control

- Review cycle: Quarterly or upon material change

- Approvals required: Product · Design · Legal · Compliance · Engineering · Executive
