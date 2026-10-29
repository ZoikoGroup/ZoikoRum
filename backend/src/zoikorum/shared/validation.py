"""Shared text rules for names and similar free text. Unicode-friendly: letters (and their combining marks, which Indic
and other scripts need) are matched by category, not by an ASCII range. Validate on write only; reads are never checked.
Messages carry no field name: the request handler prefixes it ("legalName: ...")."""
from __future__ import annotations

import re
import unicodedata

_APOS = "'\u2019"


def _is_letter(ch: str) -> bool:
    return ch.isalpha() or unicodedata.category(ch).startswith("M")


def _tidy(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()


def _text(v: str, extra: str, what: str, lo: int, hi: int) -> str:
    v = _tidy(v)
    if not lo <= len(v) <= hi:
        raise ValueError(f"must be {lo}-{hi} characters")
    bad = next((c for c in v if not (_is_letter(c) or c == " " or c in extra)), None)
    if bad is not None:
        raise ValueError(f"{what}; '{bad}' is not allowed")
    if not any(c.isalpha() for c in v):
        raise ValueError("must contain at least one letter")
    return v


def person_name(v: str, hi: int = 200) -> str:
    """Letters, spaces, apostrophe, hyphen and period."""
    return _text(v, _APOS + "-.", "may contain only letters, spaces, apostrophes, hyphens and periods", 1, hi)


def org_name(v: str, hi: int = 200, lo: int = 2) -> str:
    """Letters, spaces and . , & ' - ( ); no digits."""
    return _text(v, _APOS + "-.,&()", "may contain only letters, spaces and . , & ' - ( )", lo, hi)


def role_title(v: str, hi: int = 120) -> str:
    """Letters, spaces and & / , ' - . ( ); no digits."""
    return _text(v, _APOS + "-.,&/()", "may contain only letters, spaces and & / , ' - . ( )", 1, hi)


def city_name(v: str, hi: int = 100) -> str:
    return _text(v, _APOS + "-.", "may contain only letters, spaces, apostrophes, hyphens and periods", 1, hi)


def language_name(v: str, hi: int = 60) -> str:
    return _text(v, "-,", "may contain only letters, spaces, hyphens and commas", 1, hi)


def registration_number(v: str) -> str:
    v = v.strip()
    if not re.fullmatch(r"[A-Za-z0-9/-]{4,30}", v):
        raise ValueError("must be 4-30 characters: letters, digits, hyphen and slash only (no spaces or other symbols)")
    return v.upper()


def website_url(v: str) -> str:
    """A web address with an http(s) scheme and a host that contains a dot; no spaces."""
    from urllib.parse import urlsplit

    v = v.strip()
    err = "must be a valid web address such as https://example.com"
    if not v or re.search(r"\s", v) or not re.match(r"(?i)https?://", v):
        raise ValueError(err)
    try:
        parts = urlsplit(v)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - raises on a bad port
    except ValueError:
        raise ValueError(err) from None
    if "." not in host.strip(".") or host.startswith(".") or host.endswith(".") or ".." in host \
            or not re.fullmatch(r"[A-Za-z0-9.-]+", host.encode("idna").decode("ascii", "ignore") or "") or parts.username:
        raise ValueError(err)
    return v
