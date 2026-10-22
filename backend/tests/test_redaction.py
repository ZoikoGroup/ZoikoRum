"""Stored error text is cleaned before staff screens show it."""

from zoikorum.shared.redaction import redact


def test_credentials_tokens_and_emails_are_hidden():
    raw = ("POST https://hooks.example.com/in?token=abc123secretvalue failed for jane.doe@example.com; "
           "db postgresql://zk:hunter2@db.internal:5432/zk; Authorization: Bearer abcdefghijklmnop123; "
           "api_key=sk_live_51Habcdefghijklmnopqr \"client_secret\": \"s3cr3tvalue\" "
           "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    clean = redact(raw)
    for leaked in ("abc123secretvalue", "jane.doe@example.com", "hunter2", "abcdefghijklmnop123", "sk_live_51H",
                   "s3cr3tvalue", "eyJhbGciOiJIUzI1NiJ9"):
        assert leaked not in clean, leaked
    assert "https://hooks.example.com/in" in clean  # where it failed stays readable
    assert "db.internal:5432" in clean


def test_ordinary_errors_stay_readable():
    text = "TimeoutError: consumer notification.webhook timed out after 10s for event 3f2c1b9e-8a7d-4c6b-9e1f-0a2b3c4d5e6f"
    assert redact(text) == text
    assert redact(None) is None and redact("") == ""
