"""Delivering milestone work, deliverable by deliverable (pure rules, no database).

The contract already lists what each milestone delivers and how it will be judged (deliverables with acceptance
criteria). A delivery follows that list: every deliverable gets evidence (files, or links to a live site, a shared
document or a code repository) and an optional note on how it meets its criteria. Before anything reaches the buyer the
checks below run; blockers stop the send, warnings are shown so the professional can fix or acknowledge them.

Links are recognised from the address alone. Nothing here fetches a URL: the server never opens an address a user typed.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import date, datetime
from urllib.parse import urlsplit

from zoikorum.shared.errors import ValidationFailed

WHOLE_MILESTONE = "_milestone"  # the single item of a milestone that lists no deliverables
MAX_EVIDENCE_PER_ITEM = 10
DECLARATION = ("I confirm this work meets the acceptance criteria agreed in the contract, "
               "and that I have the right to hand it over to the buyer.")

# host suffix -> (provider, kind). Kinds: DOCUMENT (a live, editable document), REPOSITORY (source code), WEBSITE.
_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("docs.google.com", "GOOGLE_DOCS", "DOCUMENT"),
    ("drive.google.com", "GOOGLE_DRIVE", "DOCUMENT"),
    ("notion.so", "NOTION", "DOCUMENT"),
    ("notion.site", "NOTION", "DOCUMENT"),
    ("figma.com", "FIGMA", "DOCUMENT"),
    ("sharepoint.com", "MICROSOFT_365", "DOCUMENT"),
    ("onedrive.live.com", "MICROSOFT_365", "DOCUMENT"),
    ("1drv.ms", "MICROSOFT_365", "DOCUMENT"),
    ("dropbox.com", "DROPBOX", "DOCUMENT"),
    ("airtable.com", "AIRTABLE", "DOCUMENT"),
    ("github.com", "GITHUB", "REPOSITORY"),
    ("gitlab.com", "GITLAB", "REPOSITORY"),
    ("bitbucket.org", "BITBUCKET", "REPOSITORY"),
)
_GOOGLE_DOCS = {"document": "GOOGLE_DOC", "spreadsheets": "GOOGLE_SHEET", "presentation": "GOOGLE_SLIDES", "forms": "GOOGLE_FORM"}
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


def deliverables_for(terms: dict, deliverable_keys: list[str], milestone_title: str, milestone_description: str) -> list[dict]:
    """What this milestone delivers, in contract order: [{key, title, acceptanceCriteria}]."""
    by_key = {d["key"]: d for d in terms.get("deliverables", [])}
    out = [{"key": k, "title": by_key[k].get("title") or k, "acceptanceCriteria": by_key[k].get("acceptanceCriteria") or ""}
           for k in deliverable_keys if k in by_key]
    return out or [{"key": WHOLE_MILESTONE, "title": milestone_title, "acceptanceCriteria": milestone_description}]


def link_record(url: str, label: str | None, version: str | None, now: datetime) -> dict:
    """A link the professional pasted, checked and recognised. Raises a plain-language error for unusable addresses."""
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host:
        raise ValidationFailed("Paste a full secure link starting with https://", code="INVALID_LINK")
    if parts.username or parts.password:
        raise ValidationFailed("Links must not contain a username or password. Share access with the buyer instead.",
                               code="INVALID_LINK")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValidationFailed("Use the site's name, not a numeric IP address", code="INVALID_LINK")
    if "." not in host or host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise ValidationFailed("This link only works on your own network. Share an address the buyer can open.",
                               code="INVALID_LINK")
    provider, kind = "WEBSITE", "WEBSITE"
    for suffix, name, k in _PROVIDERS:
        if host == suffix or host.endswith("." + suffix):
            provider, kind = name, k
            break
    if provider == "GOOGLE_DOCS":
        first = parts.path.strip("/").split("/")[0]
        provider = _GOOGLE_DOCS.get(first, "GOOGLE_DOCS")
    return {"id": uuid.uuid4().hex, "type": "LINK", "url": url, "host": host, "provider": provider, "kind": kind,
            "label": (label or "").strip()[:200], "version": (version or "").strip()[:100], "addedAt": now.isoformat()}


def file_record(stored: dict, now: datetime) -> dict:
    return {**stored, "id": uuid.uuid4().hex, "type": "FILE", "addedAt": now.isoformat()}


def _issue(code: str, message: str, key: str | None = None) -> dict:
    return {"code": code, "message": message, "deliverableKey": key}


def _fingerprint(item: dict) -> tuple:
    return ((item.get("note") or "").strip(), tuple(sorted(e["id"] for e in item.get("evidence", []))))


def check(deliverables: list[dict], items: dict, due: date | None, today: date, previous: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """Blockers (the send is refused) and warnings (shown, the professional may still send) for a draft.

    ``previous`` is the last submission's items when this is a resubmission after the buyer asked for changes."""
    blockers: list[dict] = []
    warnings: list[dict] = []
    for d in deliverables:
        item = items.get(d["key"]) or {}
        evidence = item.get("evidence", [])
        if not evidence:
            blockers.append(_issue("NO_EVIDENCE", f"{d['title']}: add a file or paste a link", d["key"]))
        for e in evidence:
            if e["type"] != "LINK":
                continue
            if e["kind"] == "DOCUMENT":
                warnings.append(_issue("LIVE_DOCUMENT", f"{d['title']}: make sure the buyer can open this link. A live document "
                                       "can change after you send it, so attach an exported copy if the exact version matters.", d["key"]))
            elif e["kind"] == "REPOSITORY" and not e.get("version"):
                warnings.append(_issue("NO_VERSION", f"{d['title']}: add the commit or tag you delivered, so later changes to the "
                                       "repository do not change what you delivered.", d["key"]))
    seen: dict[str, str] = {}
    for d in deliverables:
        for e in (items.get(d["key"]) or {}).get("evidence", []):
            if e["type"] != "FILE":
                continue
            if seen.get(e["sha256"], d["key"]) != d["key"]:
                warnings.append(_issue("SAME_FILE_TWICE", f"{e['name']} is attached to more than one deliverable", d["key"]))
            seen.setdefault(e["sha256"], d["key"])
    if due is not None and today > due:
        warnings.append(_issue("LATE", f"This is after the due date ({due.isoformat()}). Add a short explanation for the buyer."))
    if previous is not None:
        before = {i["deliverableKey"]: _fingerprint(i) for i in previous}
        if all(before.get(d["key"]) == _fingerprint(items.get(d["key"]) or {}) for d in deliverables):
            blockers.append(_issue("NO_CHANGES", "Nothing has changed since your last delivery. Update the items the buyer asked about."))
    return blockers, warnings


def frozen_items(deliverables: list[dict], items: dict, previous: list[dict] | None) -> list[dict]:
    """The items as sent: the criteria at the time, the note and evidence, and whether it is unchanged since last time."""
    before = {i["deliverableKey"]: _fingerprint(i) for i in previous or []}
    out = []
    for d in deliverables:
        item = items.get(d["key"]) or {}
        out.append({"deliverableKey": d["key"], "title": d["title"], "acceptanceCriteria": d["acceptanceCriteria"],
                    "note": (item.get("note") or "").strip(), "evidence": list(item.get("evidence", [])),
                    "carriedOver": previous is not None and before.get(d["key"]) == _fingerprint(item)})
    return out


def seed_from(previous: list[dict]) -> dict:
    """A new draft after the buyer asked for changes starts from the last delivery: nothing has to be uploaded again."""
    return {i["deliverableKey"]: {"note": i.get("note", ""), "evidence": list(i.get("evidence", []))} for i in previous}
