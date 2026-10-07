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
    MFA_ENROLLED = _t("identity", "identity", "mfa_enrolled")
    AUTHENTICATION_SUCCEEDED = _t("identity", "session", "authentication_succeeded")
    AUTHENTICATION_FAILED = _t("identity", "session", "authentication_failed")
    SESSION_CREATED = _t("identity", "session", "created")
    SESSION_REVOKED = _t("identity", "session", "revoked")
    STEP_UP_COMPLETED = _t("identity", "session", "step_up_completed")
    IDENTITY_SUSPENDED = _t("identity", "identity", "suspended")
    IDENTITY_REINSTATED = _t("identity", "identity", "reinstated")
    IDENTITY_SOFT_DELETED = _t("identity", "identity", "soft_deleted")
    PLATFORM_ROLE_GRANTED = _t("identity", "identity", "platform_role_granted")
    PLATFORM_ROLE_REVOKED = _t("identity", "identity", "platform_role_revoked")
    PERSONA_ADDED = _t("identity", "identity", "persona_added")
    PASSWORD_RESET_REQUESTED = _t("identity", "identity", "password_reset_requested")
    PASSWORD_CHANGED = _t("identity", "identity", "password_changed")
    IDENTITY_PROFILE_UPDATED = _t("identity", "identity", "profile_updated")
    DATA_REQUEST_CREATED = _t("identity", "data_request", "created")

    # ---- Buyer ---------------------------------------------------------------
    BUYER_REGISTERED = _t("buyer", "buyer", "registered")
    ORGANIZATION_CREATED = _t("buyer", "organization", "created")
    BUSINESS_UNIT_CREATED = _t("buyer", "business_unit", "created")
    COST_CENTER_CREATED = _t("buyer", "cost_center", "created")
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

    # ---- Professional --------------------------------------------------------
    PROFESSIONAL_REGISTERED = _t("professional", "professional", "registered")
    PROFILE_UPDATED = _t("professional", "professional", "profile_updated")
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

    # ---- Marketplace ---------------------------------------------------------
    TAXONOMY_UPDATED = _t("marketplace", "taxonomy", "updated")
    LISTING_VIEWED = _t("marketplace", "listing", "viewed")
    PROFESSIONAL_SAVED = _t("marketplace", "listing", "bookmarked")
    SEARCH_SAVED = _t("marketplace", "saved_search", "created")
    MATCH_REQUESTED = _t("marketplace", "match", "requested")
    COLLECTION_UPDATED = _t("marketplace", "collection", "updated")

    # ---- Search --------------------------------------------------------------
    SEARCH_PERFORMED = _t("search", "query", "performed")
    SEARCH_ZERO_RESULT = _t("search", "query", "zero_result")

    # ---- Proposal ------------------------------------------------------------
    PROPOSAL_REQUESTED = _t("proposal", "request", "created")
    PROPOSAL_REQUEST_DECLINED = _t("proposal", "request", "declined")
    PROPOSAL_REQUEST_CANCELLED = _t("proposal", "request", "cancelled")
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
    CONTRACT_DISPUTED = _t("contract", "contract", "disputed")
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

    # ---- Escrow (financial) --------------------------------------------------
    ESCROW_OPENED = _t("escrow", "account", "opened")
    ESCROW_FUNDING_REQUESTED = _t("escrow", "account", "funding_requested")
    ESCROW_FUNDED = _t("escrow", "account", "funded")
    ESCROW_HOLD_APPLIED = _t("escrow", "account", "hold_applied")
    ESCROW_HOLD_RELEASED = _t("escrow", "account", "hold_released")
    ESCROW_RELEASE_EVALUATED = _t("escrow", "account", "release_evaluated")
    ESCROW_RELEASE_PENDING_APPROVAL = _t("escrow", "account", "release_pending_approval")
    ESCROW_RELEASED = _t("escrow", "account", "released")
    ESCROW_REFUNDED = _t("escrow", "account", "refunded")
    ESCROW_RESOLUTION_EXECUTED = _t("escrow", "account", "resolution_executed")

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
    CHARGEBACK_RECEIVED = _t("payments", "payment_intent", "chargeback_received")
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

    # ---- Trust ---------------------------------------------------------------
    TRUST_SIGNAL_ADDED = _t("trust", "profile", "signal_added")
    TRUST_SIGNAL_REVOKED = _t("trust", "profile", "signal_revoked")
    TRUST_SCORE_RECOMPUTED = _t("trust", "profile", "score_recomputed")
    TRUST_TIER_CHANGED = _t("trust", "profile", "tier_changed")
    TRUST_PROFILE_FLAGGED = _t("trust", "profile", "flagged")

    # ---- Policy --------------------------------------------------------------
    POLICY_CREATED = _t("policy", "profile", "created")
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
    ENFORCEMENT_ACTION_APPLIED = _t("admin", "enforcement_case", "action_applied")
    ENFORCEMENT_ACTION_REVERSED = _t("admin", "enforcement_case", "action_reversed")
    ENFORCEMENT_APPEAL_FILED = _t("admin", "enforcement_case", "appeal_filed")
    ENFORCEMENT_APPEAL_DECIDED = _t("admin", "enforcement_case", "appeal_decided")
    OPERATOR_ACTION_LOGGED = _t("admin", "operator", "action_logged")


ALL_EVENTS: frozenset[str] = frozenset(v for k, v in vars(E).items() if k.isupper())

FINANCIAL_EVENTS: frozenset[str] = frozenset(
    e
    for e in ALL_EVENTS
    if e.startswith(("zoikorum.escrow.", "zoikorum.payments."))
)


def domain_of(event_type: str) -> str:
    return event_type.split(".")[1]
