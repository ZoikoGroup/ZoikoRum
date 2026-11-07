from __future__ import annotations

import pytest

from zoikorum.domains.ai import service


@pytest.mark.unit
@pytest.mark.parametrize(("message", "intent"), [
    ("explore zoikorum", "general"),
    ("explore the platform", "general"),
    ("how do i get started", "general"),
    ("how do i compare", "enterprise_discovery"),
    ("how many can i compare", "enterprise_discovery"),
    ("how do i contact a professional", "contracts_milestones"),
    ("how do i request changes", "contracts_milestones"),
    ("how do payments work", "protected_payments"),
    ("how do i get paid", "protected_payments"),
    ("how long do payouts take", "protected_payments"),
    ("how do i become verified", "trust_verification"),
    ("my account is blocked", "support_handoff"),
    ("how do i invite someone", "account_help"),
    ("what languages", "enterprise_discovery"),
    ("how many professionals can i request", "contracts_milestones"),
    ("support hours", "support_handoff"),
    ("does zoikorum charge", "pricing_public"),
    ("how do i terminate", "contracts_milestones"),
    ("how do i set up a team", "account_help"),
    ("can i reply to a review", "trust_verification"),
    ("can i use zoikorum in europe", "enterprise_discovery"),
    ("how do i use zoikorum in the uk", "enterprise_discovery"),
    ("do you support cryptocurrency", "protected_payments"),
    ("can i pay with paypal", "protected_payments"),
    ("can i pay with bitcoin", "protected_payments"),
    ("is there a mobile app", "account_help"),
    ("how do i find work as a professional", "professional_onboarding"),
    ("how do i get more clients", "professional_onboarding"),
    ("how do i set my hourly rate", "pricing_public"),
    ("what does amber mean", "trust_verification"),
    ("what does green mean", "trust_verification"),
    ("how do i add a team member", "account_help"),
    ("how do i export my data", "account_help"),
    ("how do i add a passkey", "account_help"),
    ("how do i use a passkey", "account_help"),
    ("i lost my authenticator", "account_help"),
    ("how do i get recovery codes", "account_help"),
    ("can i sign in with google", "account_help"),
    ("can i sign in with microsoft", "account_help"),
    ("how do i set up single sign-on", "account_help"),
    ("do you support okta", "account_help"),
    ("how do i enable scim", "account_help"),
    ("how do i report a bug", "support_handoff"),
    ("my payment is not working", "support_handoff"),
    ("how do i request a feature", "support_handoff"),
    ("how long does support take", "support_handoff"),
    ("is there live chat", "support_handoff"),
    ("how do i get in touch", "support_handoff"),
    ("can i edit my review reply", "trust_verification"),
    ("can i delete my review", "trust_verification"),
])
def test_common_platform_questions_have_an_instant_answer(message: str, intent: str):
    entry = service._match_faq(message)
    assert entry is not None, message
    assert entry["intent"] == intent


@pytest.mark.unit
def test_unknown_platform_questions_get_the_safe_overview():
    message = "does zoikorum have a physical office in antarctica"
    assert service._match_faq(message) is None
    assert service.PLATFORM_RE.search(message)
    assert service.GENERAL_FAQ["intent"] == "general"
    reply = service._curated_reply(service.GENERAL_FAQ)
    assert "governed marketplace" in reply["answer"]
    assert reply["intent"] == "general"


@pytest.mark.unit
def test_general_knowledge_still_uses_the_model():
    assert service._match_faq("Who wrote Hamlet?") is None
    assert service.PLATFORM_RE.search("Who wrote Hamlet?") is None


@pytest.mark.unit
def test_general_platform_questions_use_the_overview():
    assert service._match_faq("tell me something about zoikorum") is service.GENERAL_FAQ


@pytest.mark.unit
def test_chat_fallback_models_include_the_production_model():
    assert "qwen2.5:0.5b" in service.CHAT_FALLBACK_MODELS


@pytest.mark.unit
def test_security_answer_covers_passkeys_recovery_and_sso():
    passkey = service._match_faq("how do i add a passkey")
    recovery = service._match_faq("i lost my authenticator")
    sso = service._match_faq("how do i set up single sign-on")
    assert passkey is not None and "passkey" in passkey["answer"].lower()
    assert recovery is not None and "recovery code" in recovery["answer"].lower()
    assert sso is not None and "single sign-on" in sso["answer"].lower()
    assert sso is not None and "scim" in sso["answer"].lower()


@pytest.mark.unit
def test_support_answer_covers_bugs_and_feedback():
    for message in ("how do i report a bug", "how do i request a feature", "is there live chat"):
        entry = service._match_faq(message)
        assert entry is not None, message
        assert entry["intent"] == "support_handoff", message
        assert "help request" in entry["answer"].lower(), message


@pytest.mark.unit
def test_review_answer_is_accurate_about_editable_replies():
    entry = service._match_faq("can i edit my review reply")
    assert entry is not None
    assert "post one public reply and edit it" in entry["answer"]
    assert "edits recorded" in entry["answer"]


@pytest.mark.unit
def test_payout_answer_does_not_invent_a_fixed_sla():
    entry = service._match_faq("how long do payouts take")
    assert entry is not None
    assert "two business days" not in entry["answer"].lower()
    assert "expected bank arrival date" in entry["answer"].lower()


@pytest.mark.unit
def test_general_links_help_a_general_question():
    labels = [label for label, _ in service.RELATED_PAGES["general"]]
    assert "Help Center" in labels
    assert "Browse professionals" in labels
    assert all("Privacy" not in label for label in labels)
