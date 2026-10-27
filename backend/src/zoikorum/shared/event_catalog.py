"""The platform event catalog - the single list of every domain event.

Topic convention (Architecture 6.1): zoikorum.{domain}.{aggregate}.{action}.v{n}
Events are FACTS in the past tense. Only the owning domain may publish an event
from its section. Add new events here first (schema-first, Appendix C), then
publish/consume them.

Events in FINANCIAL_EVENTS are never auto-replayed from the dead-letter queue;
an operator with FINANCIAL_OPS must authorise replay (Architecture 6.4).
"""

from __future__ import annotations


def _t(domain: str, aggregate: str, action: str, v: int = 1) -> str:
    return f"zoikorum.{domain}.{aggregate}.{action}.v{v}"


class E:
    # ---- Identity ------------------------------------------------------------
    IDENTITY_CREATED = _t("identity", "identity", "created")
    EMAIL_CONFIRMED = _t("identity", "identity", "email_confirmed")
    EMAIL_CONFIRMATION_REQUESTED = _t("identity", "identity", "email_confirmation_requested")  # "resend the link"
    MFA_ENROLLED = _t("identity", "identity", "mfa_enrolled")
    PASSKEY_ADDED = _t("identity", "identity", "passkey_added")
    PASSKEY_REMOVED = _t("identity", "identity", "passkey_removed")
    MFA_RECOVERY_CODE_USED = _t("identity", "identity", "mfa_recovery_code_used")  # signed in with a one-time recovery code
    MFA_RESET = _t("identity", "identity", "mfa_reset")  # staff removed two-step verification after an identity check
    AUTHENTICATION_SUCCEEDED = _t("identity", "session", "authentication_succeeded")
    AUTHENTICATION_FAILED = _t("identity", "session", "authentication_failed")
    SESSION_CREATED = _t("identity", "session", "created")
    SESSION_REVOKED = _t("identity", "session", "revoked")
    STEP_UP_COMPLETED = _t("identity", "session", "step_up_completed")
    IDENTITY_SUSPENDED = _t("identity", "identity", "suspended")
    IDENTITY_REINSTATED = _t("identity", "identity", "reinstated")
    DUPLICATE_ACCOUNT_SUSPECTED = _t("identity", "duplicate", "suspected")
    DUPLICATE_ACCOUNT_ANSWERED = _t("identity", "duplicate", "answered")
    DUPLICATE_ACCOUNT_RESOLVED = _t("identity", "duplicate", "resolved")
    IDENTITY_SOFT_DELETED = _t("identity", "identity", "soft_deleted")
    PLATFORM_ROLE_GRANTED = _t("identity", "identity", "platform_role_granted")
    PLATFORM_ROLE_REVOKED = _t("identity", "identity", "platform_role_revoked")
    PLATFORM_ROLE_EXPIRED = _t("identity", "identity", "platform_role_expired")  # a time-limited (just-in-time) grant ended
    PERSONA_ADDED = _t("identity", "identity", "persona_added")
    PASSWORD_RESET_REQUESTED = _t("identity", "identity", "password_reset_requested")
    PASSWORD_CHANGED = _t("identity", "identity", "password_changed")
    IDENTITY_PROFILE_UPDATED = _t("identity", "identity", "profile_updated")
    DATA_REQUEST_CREATED = _t("identity", "data_request", "created")
    DATA_REQUEST_COMPLETED = _t("identity", "data_request", "completed")  # export ready, or account erased
    DATA_REQUEST_BLOCKED = _t("identity", "data_request", "blocked")  # erasure waits for open engagements, money, ...
    DATA_REQUEST_CANCELLED = _t("identity", "data_request", "cancelled")

    # ---- Buyer ---------------------------------------------------------------
    BUYER_REGISTERED = _t("buyer", "buyer", "registered")
    ORGANIZATION_CREATED = _t("buyer", "organization", "created")
    BUSINESS_UNIT_CREATED = _t("buyer", "business_unit", "created")
    BUSINESS_UNITS_MERGED = _t("buyer", "business_unit", "merged")  # policy profiles follow the surviving unit
    COST_CENTER_CREATED = _t("buyer", "cost_center", "created")
    LEGAL_ENTITY_CREATED = _t("buyer", "legal_entity", "created")
    LEGAL_ENTITY_UPDATED = _t("buyer", "legal_entity", "updated")  # details, default, or archived
    ORG_MEMBER_ADDED = _t("buyer", "organization", "member_added")
    BUYER_ROLE_ASSIGNED = _t("buyer", "organization", "role_assigned")
    ORG_MEMBER_REMOVED = _t("buyer", "organization", "member_removed")
    ORG_MEMBER_INVITED = _t("buyer", "organization", "member_invited")
    ORG_INVITATION_REVOKED = _t("buyer", "organization", "invitation_revoked")
    ORGANIZATION_UPDATED = _t("buyer", "organization", "updated")
    SPEND_LIMIT_UPDATED = _t("buyer", "organization", "spend_limit_updated")
    BILLING_CONTACTS_UPDATED = _t("buyer", "organization", "billing_contacts_updated")

    # ---- Firm ----------------------------------------------------------------
    FIRM_REGISTERED = _t("firm", "firm", "registered")
    FIRM_VERIFIED = _t("firm", "firm", "verified")
    FIRM_MEMBER_INVITED = _t("firm", "firm", "member_invited")
    FIRM_MEMBER_JOINED = _t("firm", "firm", "member_joined")
    FIRM_MEMBER_REMOVED = _t("firm", "firm", "member_removed")
    FIRM_MEMBER_ROLES_CHANGED = _t("firm", "firm", "member_roles_changed")
    FIRM_INVITATION_REVOKED = _t("firm", "firm", "invitation_revoked")
    FIRM_PROFILE_UPDATED = _t("firm", "firm", "profile_updated")
    FIRM_OFFERING_PUBLISHED = _t("firm", "offering", "published")  # regulated offerings: a verified licensed member delivers
    FIRM_OFFERING_UNPUBLISHED = _t("firm", "offering", "unpublished")

    # ---- Professional --------------------------------------------------------
    PROFESSIONAL_REGISTERED = _t("professional", "professional", "registered")
    PROFILE_UPDATED = _t("professional", "professional", "profile_updated")
    PROFILE_VIEWED = _t("professional", "professional", "profile_viewed")
    ENTERPRISE_READINESS_REQUESTED = _t("professional", "enterprise", "readiness_requested")  # Compliance reviews
    ENTERPRISE_READINESS_DECIDED = _t("professional", "enterprise", "readiness_decided")  # analytics only: someone else opened the public profile
    PROFILE_PUBLISHED = _t("professional", "professional", "profile_published")
    PROFILE_UNPUBLISHED = _t("professional", "professional", "profile_unpublished")
    PROFILE_SUSPENDED = _t("professional", "professional", "profile_suspended")
    PROFILE_REINSTATED = _t("professional", "professional", "profile_reinstated")
    SERVICE_OFFERING_CREATED = _t("professional", "offering", "created")
    SERVICE_OFFERING_UPDATED = _t("professional", "offering", "updated")
    SERVICE_OFFERING_STATUS_CHANGED = _t("professional", "offering", "status_changed")
    AVAILABILITY_UPDATED = _t("professional", "professional", "availability_updated")
    CAPACITY_CHANGED = _t("professional", "professional", "capacity_changed")
    JURISDICTIONS_UPDATED = _t("professional", "professional", "jurisdictions_updated")
    CREDENTIAL_SUBMITTED = _t("professional", "credential", "submitted")
    CREDENTIAL_WITHDRAWN = _t("professional", "credential", "withdrawn")  # the professional removed it; its check closes

    # ---- Marketplace ---------------------------------------------------------
    TAXONOMY_UPDATED = _t("marketplace", "taxonomy", "updated")
    TAXONOMY_SUGGESTION_SUBMITTED = _t("marketplace", "taxonomy_suggestion", "submitted")
    TAXONOMY_SUGGESTION_RESOLVED = _t("marketplace", "taxonomy_suggestion", "resolved")  # APPROVED | MERGED | REJECTED
    LISTING_VIEWED = _t("marketplace", "listing", "viewed")
    PROFESSIONAL_SAVED = _t("marketplace", "listing", "bookmarked")
    PROFESSIONAL_UNSAVED = _t("marketplace", "listing", "unbookmarked")
    SEARCH_SAVED = _t("marketplace", "saved_search", "created")
    MATCH_REQUESTED = _t("marketplace", "match", "requested")
    COLLECTION_UPDATED = _t("marketplace", "collection", "updated")

    # ---- Search --------------------------------------------------------------
    SEARCH_PERFORMED = _t("search", "query", "performed")
    SEARCH_ZERO_RESULT = _t("search", "query", "zero_result")

    # ---- Proposal ------------------------------------------------------------
    PROPOSAL_REQUESTED = _t("proposal", "request", "created")
    PROPOSAL_REQUEST_DECLINED = _t("proposal", "request", "declined")
    PROPOSAL_REQUEST_REMINDER = _t("proposal", "request", "reminder")  # to the professional: answer is due soon
    PROPOSAL_REQUEST_UNANSWERED = _t("proposal", "request", "unanswered")  # to the buyer: the time to answer passed
    PROPOSAL_REQUEST_CANCELLED = _t("proposal", "request", "cancelled")
    OPEN_BRIEF_POSTED = _t("proposal", "brief", "posted")  # a buyer described a need for matching professionals to see
    OPEN_BRIEF_INTEREST = _t("proposal", "brief", "interest")  # a professional said they are interested (to the buyer)
    NDA_ACCEPTED = _t("proposal", "request", "nda_accepted")
    PROPOSAL_SUBMITTED = _t("proposal", "proposal", "submitted")
    PROPOSAL_REVISION_REQUESTED = _t("proposal", "proposal", "revision_requested")
    PROPOSAL_REVISED = _t("proposal", "proposal", "revised")
    PROPOSAL_ACCEPTANCE_PENDING_APPROVAL = _t("proposal", "proposal", "acceptance_pending_approval")
    PROPOSAL_ACCEPTED = _t("proposal", "proposal", "accepted")
    PROPOSAL_REJECTED = _t("proposal", "proposal", "rejected")
    PROPOSAL_WITHDRAWN = _t("proposal", "proposal", "withdrawn")
    PROPOSAL_EXPIRED = _t("proposal", "proposal", "expired")

    # ---- Contract ------------------------------------------------------------
    CONTRACT_GENERATED = _t("contract", "contract", "generated")
    CONTRACT_SIGNED = _t("contract", "contract", "signed")
    CONTRACT_ACTIVATED = _t("contract", "contract", "activated")
    CONTRACT_COMPLETED = _t("contract", "contract", "completed")
    CONTRACT_TERMINATED = _t("contract", "contract", "terminated")
    CONTRACT_TERMINATION_REQUESTED = _t("contract", "termination", "requested")  # one side asks to end by agreement
    RETAINER_PAUSED = _t("contract", "retainer", "paused")
    ESCROW_AUTO_FUNDING_CHANGED = _t("escrow", "account", "auto_funding_changed")
    ESCROW_AUTO_FUNDING_FAILED = _t("escrow", "account", "auto_funding_failed")  # the buyer funds the cycle by hand
    RETAINER_RESUMED = _t("contract", "retainer", "resumed")
    CONTRACT_TERMINATION_DECLINED = _t("contract", "termination", "declined")
    CONTRACT_TERMINATION_WITHDRAWN = _t("contract", "termination", "withdrawn")  # withdrawn, lapsed or overtaken by a dispute
    CONTRACT_DISPUTED = _t("contract", "contract", "disputed")
    # Buyers on open engagements are told when the professional is suspended or a check lapses (playbook: Level 3+).
    CONTRACT_PROFESSIONAL_STATUS_CHANGED = _t("contract", "contract", "professional_status_changed")
    CONTRACT_DISPUTE_CLEARED = _t("contract", "contract", "dispute_cleared")
    SIGNATURE_DEADLINE_ESCALATED = _t("contract", "contract", "signature_deadline_escalated")
    CHANGE_ORDER_REQUESTED = _t("contract", "change_order", "requested")
    CHANGE_ORDER_APPROVED = _t("contract", "change_order", "approved")
    CHANGE_ORDER_REJECTED = _t("contract", "change_order", "rejected")
    CONTRACT_AMENDED = _t("contract", "contract", "amended")
    MILESTONE_CREATED = _t("contract", "milestone", "created")
    MILESTONE_STARTED = _t("contract", "milestone", "started")
    MILESTONE_SUBMITTED = _t("contract", "milestone", "submitted")  # a.k.a. MilestoneDelivered
    MILESTONE_REVISION_REQUESTED = _t("contract", "milestone", "revision_requested")
    MILESTONE_ACCEPTED = _t("contract", "milestone", "accepted")
    MILESTONE_ACCEPTANCE_PENDING_APPROVAL = _t("contract", "milestone", "acceptance_pending_approval")
    MILESTONE_ACCEPTANCE_REMINDER = _t("contract", "milestone", "acceptance_reminder")  # review window closes soon
    MILESTONE_ACCEPTANCE_OVERDUE = _t("contract", "milestone", "acceptance_overdue")  # review window passed: escalate
    MILESTONE_FUNDING_REVERSED = _t("contract", "milestone", "funding_reversed")  # back to pending funding after a chargeback
    MILESTONE_PARTIAL_ACCEPTANCE_OFFERED = _t("contract", "milestone", "partial_acceptance_offered")
    MILESTONE_PARTIAL_ACCEPTANCE_DECLINED = _t("contract", "milestone", "partial_acceptance_declined")
    MILESTONE_FUNDING_REMINDER = _t("contract", "milestone", "funding_reminder")  # unfunded cycle/milestone due soon
    MILESTONE_CANCELLED = _t("contract", "milestone", "cancelled")  # e.g. remaining retainer cycles cancelled

    # ---- Escrow (financial) --------------------------------------------------
    ESCROW_OPENED = _t("escrow", "account", "opened")
    ESCROW_FUNDING_REQUESTED = _t("escrow", "account", "funding_requested")
    ESCROW_FUNDED = _t("escrow", "account", "funded")
    ESCROW_HOLD_APPLIED = _t("escrow", "account", "hold_applied")
    ESCROW_HOLD_RELEASED = _t("escrow", "account", "hold_released")
    ESCROW_RELEASE_EVALUATED = _t("escrow", "account", "release_evaluated")
    ESCROW_RELEASE_BLOCKED = _t("escrow", "account", "release_blocked")  # accepted work, release approval denied or expired
    ESCROW_RELEASE_ESCALATED = _t("escrow", "account", "release_escalated")  # ...and still not released some days later
    ESCROW_RELEASE_PENDING_APPROVAL = _t("escrow", "account", "release_pending_approval")
    ESCROW_RELEASED = _t("escrow", "account", "released")
    ESCROW_REFUNDED = _t("escrow", "account", "refunded")
    ESCROW_RESOLUTION_EXECUTED = _t("escrow", "account", "resolution_executed")
    ESCROW_FUNDING_REVERSED = _t("escrow", "account", "funding_reversed")  # a chargeback took held money back
    ESCROW_FUNDING_EXPIRED = _t("escrow", "account", "funding_expired")  # never funded within the window: allocations EXPIRED

    # ---- Payments (financial) ------------------------------------------------
    PAYMENT_INTENT_CREATED = _t("payments", "payment_intent", "created")
    PAYMENT_CAPTURED = _t("payments", "payment_intent", "captured")
    PAYMENT_FAILED = _t("payments", "payment_intent", "failed")
    PAYOUT_INITIATED = _t("payments", "payout", "initiated")
    PAYOUT_SETTLED = _t("payments", "payout", "settled")
    PAYOUT_FAILED = _t("payments", "payout", "failed")
    REFUND_INITIATED = _t("payments", "refund", "initiated")
    REFUND_SETTLED = _t("payments", "refund", "settled")
    INVOICE_ISSUED = _t("payments", "invoice", "issued")
    PAYMENT_CHARGED_BACK = _t("payments", "payment_intent", "charged_back")  # card issuer reversed a captured payment
    CHARGEBACK_RECEIVED = _t("payments", "payment_intent", "chargeback_received")
    REFUND_FAILED = _t("payments", "refund", "failed")  # the provider could not return the money; retried daily
    RECONCILIATION_COMPLETED = _t("payments", "reconciliation", "completed")
    RECONCILIATION_MISMATCH = _t("payments", "reconciliation", "mismatch_detected")

    # ---- Verification --------------------------------------------------------
    VERIFICATION_STARTED = _t("verification", "case", "started")
    VERIFICATION_EVIDENCE_SUBMITTED = _t("verification", "case", "evidence_submitted")
    VERIFICATION_NEEDS_INFO = _t("verification", "case", "needs_info")
    VERIFICATION_COMPLETED = _t("verification", "case", "completed")
    VERIFICATION_FAILED = _t("verification", "case", "failed")
    VERIFICATION_EXPIRING = _t("verification", "case", "expiring")
    VERIFICATION_EXPIRED = _t("verification", "case", "expired")
    VERIFICATION_REVOKED = _t("verification", "case", "revoked")
    VERIFICATION_APPEAL_FILED = _t("verification", "appeal", "filed")
    VERIFICATION_DUPLICATE_DOCUMENT = _t("verification", "evidence", "duplicate_document")  # same ID document from two accounts
    VERIFICATION_FRAUD_SUSPECTED = _t("verification", "case", "fraud_suspected")  # reviewer: document appears altered or fake
    VERIFICATION_EVIDENCE_FLAGGED = _t("verification", "evidence", "flagged")  # automatic check: unrelated or unreadable (hint only)
    VERIFICATION_APPEAL_DECIDED = _t("verification", "appeal", "decided")

    # ---- Trust ---------------------------------------------------------------
    TRUST_SIGNAL_ADDED = _t("trust", "profile", "signal_added")
    TRUST_SIGNAL_REVOKED = _t("trust", "profile", "signal_revoked")
    TRUST_SCORE_RECOMPUTED = _t("trust", "profile", "score_recomputed")
    TRUST_TIER_CHANGED = _t("trust", "profile", "tier_changed")
    TRUST_TIER_NUDGE = _t("trust", "profile", "tier_nudge")
    SAVED_PROFESSIONAL_AVAILABLE = _t("marketplace", "saved_professional", "available")  # to people who saved them
    SAVED_SEARCH_MATCHES = _t("marketplace", "saved_search", "new_matches")  # daily: new professionals match a saved search  # a buyer needs a higher tier: what to verify to qualify
    TRUST_PROFILE_FLAGGED = _t("trust", "profile", "flagged")

    # ---- Policy --------------------------------------------------------------
    POLICY_CREATED = _t("policy", "profile", "created")
    POLICY_DRAFT_UPDATED = _t("policy", "profile", "draft_updated")
    APPROVAL_EXPIRED = _t("policy", "approval", "expired")
    POLICY_VERSION_ACTIVATED = _t("policy", "profile", "version_activated")
    POLICY_EVALUATED = _t("policy", "evaluation", "completed")
    POLICY_VIOLATION_DETECTED = _t("policy", "evaluation", "violation_detected")
    APPROVAL_REQUIRED = _t("policy", "approval", "requested")
    APPROVAL_GRANTED = _t("policy", "approval", "granted")
    APPROVAL_DENIED = _t("policy", "approval", "denied")
    APPROVAL_ESCALATED = _t("policy", "approval", "escalated")
    EXCEPTION_REQUESTED = _t("policy", "exception", "requested")
    EXCEPTION_GRANTED = _t("policy", "exception", "granted")
    EXCEPTION_DENIED = _t("policy", "exception", "denied")
    EXCEPTION_EXPIRED = _t("policy", "exception", "expired")

    # ---- Dispute -------------------------------------------------------------
    DISPUTE_INITIATED = _t("dispute", "case", "initiated")
    DISPUTE_EVIDENCE_WINDOW_OPENED = _t("dispute", "case", "evidence_window_opened")
    DISPUTE_EVIDENCE_SUBMITTED = _t("dispute", "case", "evidence_submitted")
    DISPUTE_RESOLUTION_PROPOSED = _t("dispute", "case", "resolution_proposed")
    DISPUTE_RESOLUTION_AGREED = _t("dispute", "case", "resolution_agreed")
    DISPUTE_ESCALATED = _t("dispute", "case", "escalated")
    DISPUTE_RECOMMENDATION_ISSUED = _t("dispute", "case", "recommendation_issued")
    DISPUTE_RESOLVED = _t("dispute", "case", "resolved")  # decision issued
    DISPUTE_ENFORCED = _t("dispute", "case", "enforced")
    DISPUTE_CLOSED = _t("dispute", "case", "closed")
    DISPUTE_APPEALED = _t("dispute", "case", "appealed")
    DISPUTE_APPEAL_DECIDED = _t("dispute", "case", "appeal_decided")
    REVIEW_CREATED = _t("review", "review", "created")

    # ---- Audit ---------------------------------------------------------------
    AUDIT_ENTRY_REQUESTED = _t("audit", "entry", "requested")  # explicit audit-only entries
    AUDIT_EXPORT_REQUESTED = _t("audit", "export", "requested")
    AUDIT_EXPORT_COMPLETED = _t("audit", "export", "completed")
    HASH_CHAIN_VALIDATED = _t("audit", "chain", "validated")
    HASH_CHAIN_BROKEN = _t("audit", "chain", "broken")

    # ---- Messaging -----------------------------------------------------------
    THREAD_CREATED = _t("messaging", "thread", "created")
    MESSAGE_SENT = _t("messaging", "message", "sent")
    MESSAGE_FLAGGED = _t("messaging", "message", "flagged")
    THREAD_LOCKED = _t("messaging", "thread", "locked")
    THREAD_UNLOCKED = _t("messaging", "thread", "unlocked")

    # ---- Notification --------------------------------------------------------
    NOTIFICATION_QUEUED = _t("notification", "notification", "queued")
    NOTIFICATION_DELIVERED = _t("notification", "notification", "delivered")
    NOTIFICATION_FAILED = _t("notification", "notification", "failed")
    NOTIFICATION_PREFERENCES_UPDATED = _t("notification", "preferences", "updated")

    # ---- AI ------------------------------------------------------------------
    AI_OUTPUT_GENERATED = _t("ai", "inference", "output_generated")
    PROMPT_VERSION_ACTIVATED = _t("ai", "prompt", "version_activated")
    RISK_FLAG_RAISED = _t("ai", "risk", "flag_raised")

    # ---- Administration / Trust & Safety enforcement -------------------------
    ENFORCEMENT_CASE_OPENED = _t("admin", "enforcement_case", "opened")
    ENFORCEMENT_CASE_CLOSED = _t("admin", "enforcement_case", "closed")  # reviewed, no action needed
    USER_REPORT_SUBMITTED = _t("admin", "user_report", "submitted")
    DISPUTE_CLARIFICATION_REQUESTED = _t("dispute", "case", "clarification_requested")
    DISPUTE_REFERRED_TO_ARBITRATION = _t("dispute", "case", "referred_to_arbitration")
    DISPUTE_PATTERN_FLAGGED = _t("dispute", "case", "pattern_flagged")
    DISPUTE_PROVISIONAL_DECISION_ISSUED = _t("dispute", "case", "provisional_decision_issued")  # binding recommendation / enterprise admin decision
    DISPUTE_REPORT_READY = _t("dispute", "report", "ready")  # scheduled dispute report for an organisation admin
    DISPUTE_RETENTION_DUE = _t("dispute", "case", "retention_due")  # Legal reviews the closed record  # advisory: repeated disputes decided against the opener
    SUPPORT_REQUEST_OPENED = _t("support", "request", "opened")
    SUPPORT_REQUEST_ANSWERED = _t("support", "request", "answered")  # staff replied: the person is told
    SUPPORT_REQUEST_RESOLVED = _t("support", "request", "resolved")
    USER_REPORT_CLOSED = _t("admin", "user_report", "closed")
    ENFORCEMENT_ACTION_APPLIED = _t("admin", "enforcement_case", "action_applied")
    ENFORCEMENT_ACTION_REVERSED = _t("admin", "enforcement_case", "action_reversed")
    ENFORCEMENT_APPEAL_FILED = _t("admin", "enforcement_case", "appeal_filed")
    ENFORCEMENT_APPEAL_DECIDED = _t("admin", "enforcement_case", "appeal_decided")
    ENFORCEMENT_REMEDIATION_COMPLETED = _t("admin", "enforcement_case", "remediation_completed")
    OPERATOR_ACTION_LOGGED = _t("admin", "operator", "action_logged")
    # Maker-checker for privileged staff actions (admin/approvals.py): REQUESTED -> APPLIED | FAILED | REJECTED | EXPIRED | CANCELLED
    STAFF_APPROVAL_REQUESTED = _t("admin", "approval_request", "requested")
    STAFF_APPROVAL_REJECTED = _t("admin", "approval_request", "rejected")
    STAFF_APPROVAL_APPLIED = _t("admin", "approval_request", "applied")  # approved by a second person and carried out
    STAFF_APPROVAL_FAILED = _t("admin", "approval_request", "failed")  # approved, but the action could not be carried out
    STAFF_APPROVAL_EXPIRED = _t("admin", "approval_request", "expired")
    STAFF_APPROVAL_CANCELLED = _t("admin", "approval_request", "cancelled")
    CASE_ASSIGNED = _t("admin", "case", "assigned")  # a staff case has a new owner: the owner is told


ALL_EVENTS: frozenset[str] = frozenset(v for k, v in vars(E).items() if k.isupper())

FINANCIAL_EVENTS: frozenset[str] = frozenset(
    e
    for e in ALL_EVENTS
    if e.startswith(("zoikorum.escrow.", "zoikorum.payments."))
)


def domain_of(event_type: str) -> str:
    return event_type.split(".")[1]
