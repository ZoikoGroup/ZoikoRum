"""Test uploads: small but real files with matching type and fingerprint (the server checks both)."""

from __future__ import annotations

import base64
import hashlib


def upload(name: str, body: bytes = b"content", content_type: str = "application/pdf") -> dict:
    prefix = {"application/pdf": b"%PDF-1.4\n", "image/png": b"\x89PNG\r\n\x1a\n"}.get(content_type, b"")
    data = prefix + body
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "contentType": content_type,
            "dataBase64": base64.b64encode(data).decode()}


def raw(item: dict) -> bytes:
    return base64.b64decode(item["dataBase64"])
