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
