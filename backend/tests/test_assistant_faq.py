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
])
def test_common_platform_questions_have_an_instant_answer(message: str, intent: str):
    entry = service._match_faq(message)
    assert entry is not None, message
    assert entry["intent"] == intent


@pytest.mark.unit
def test_general_knowledge_still_uses_the_model():
    assert service._match_faq("Who wrote Hamlet?") is None
    assert service.PLATFORM_RE.search("Who wrote Hamlet?") is None


@pytest.mark.unit
def test_unmatched_zoikorum_question_gets_the_platform_overview():
    assert service._match_faq("tell me something about zoikorum") is not None
