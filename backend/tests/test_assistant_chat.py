from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from zoikorum.domains.ai import service
from zoikorum.domains.ai.models import ChatFeedback, InferenceLog


async def test_chat_log_is_redacted_and_feedback_is_persisted(client, make_user, sf, monkeypatch):
    async def fake_chat(settings, message):
        return json.dumps({
            "intent": "general",
            "answer": "The sky looks blue because air scatters short wavelengths of sunlight.",
            "sections": [{"title": "Why", "items": ["Shorter wavelengths scatter more."]}],
            "suggestions": ["Why are sunsets red?", "How does light travel?"],
            "limitations": "I explain general information only.",
        })

    monkeypatch.setattr(service, "_ollama_chat", fake_chat)
    user = await make_user("chat-feedback")

    response = await client.post("/v1/ai/chat", headers=user.h, json={"message": "Why is the sky blue?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"].startswith("The sky looks blue")

    async with sf() as session:
        log = await session.get(InferenceLog, uuid.UUID(body["answerId"]))
        assert log is not None
        assert log.purpose == "assistant-chat"
        stored = json.loads(log.output)
        assert stored["redacted"] is True
        assert "scatters" not in log.output

    response = await client.post(f"/v1/ai/chat/{body['answerId']}/feedback", headers=user.h,
                                 json={"rating": "HELPFUL"})
    assert response.status_code == 200, response.text
    assert response.json() == {"recorded": True}

    response = await client.post(f"/v1/ai/chat/{body['answerId']}/feedback", headers=user.h,
                                 json={"rating": "NOT_HELPFUL", "reason": "missing_sources"})
    assert response.status_code == 200, response.text

    async with sf() as session:
        rows = (await session.scalars(select(ChatFeedback))).all()
        assert len(rows) == 1
        assert rows[0].rating == "NOT_HELPFUL"
        assert rows[0].reason == "missing_sources"


async def test_chat_feedback_rejects_another_persons_answer(client, make_user, sf, monkeypatch):
    async def fake_chat(settings, message):
        return json.dumps({"intent": "general", "answer": "A short answer.", "sections": [],
                           "suggestions": ["Next question?"], "limitations": "Advisory only."})

    monkeypatch.setattr(service, "_ollama_chat", fake_chat)
    owner = await make_user("chat-owner")
    other = await make_user("chat-other")

    response = await client.post("/v1/ai/chat", headers=owner.h, json={"message": "Hello"})
    assert response.status_code == 200, response.text
    answer_id = response.json()["answerId"]

    response = await client.post(f"/v1/ai/chat/{answer_id}/feedback", headers=other.h, json={"rating": "HELPFUL"})
    assert response.status_code == 404, response.text
