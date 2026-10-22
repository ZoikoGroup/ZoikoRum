"""Clean free text (stored error messages) before staff screens show it.

Errors are written by handlers and libraries, so they can quote a webhook URL with a token in it, an Authorization
header, a connection string or a person's email. Staff need the shape of the failure, never those values."""

from __future__ import annotations

import re

HIDDEN = "[hidden]"

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # user:password@ in any URL or connection string
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@"), rf"\1{HIDDEN}@"),
    # query strings and fragments (signed URLs, ?token=...)
    (re.compile(r"(?i)(\bhttps?://[^\s?#'\"<>]+)[?#][^\s'\"<>]*"), rf"\1?{HIDDEN}"),
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {HIDDEN}"),
    # key=value / "key": "value" where the key names a secret
    (re.compile(r"""(?ix)
        (["']?\b[a-z0-9_-]*(?:secret|password|passwd|pwd|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|signature|sig|auth|credential|cookie|session)[a-z0-9_-]*\b["']?)
        (\s*[:=]\s*)
        (["']?)[^\s,;&'"}\]]+\3"""), rf"\1\2\3{HIDDEN}\3"),
    # provider keys with well-known prefixes (sk_live_..., whsec_..., AKIA..., ghp_...)
    (re.compile(r"\b(?:sk|rk|pk|whsec|xox[abpr]|ghp|gho|github_pat|AKIA|ASIA)[_-]?[A-Za-z0-9_-]{10,}\b"), HIDDEN),
    # JSON Web Tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), HIDDEN),
    # email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email hidden]"),
    # long opaque strings (keys, signatures); UUIDs and short ids stay readable
    (re.compile(r"\b(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{40,}={0,2}"), HIDDEN),
)


def redact(text: str | None) -> str | None:
    """The text with credentials, tokens, query strings and emails replaced by a marker."""
    if not text:
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
