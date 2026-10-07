"""Document uploads (Architecture 8.x): the file is stored in blob storage, the database keeps only its key and hash.

Every upload is checked before anything is stored: the declared type must match the file's own bytes, and the
SHA-256 the browser computed must match what arrived. Files are content-addressed, so re-sending the same file
is harmless. Opening a stored file is always the caller's decision (access rules live in each domain) and is audited there.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Literal

from fastapi import Response
from pydantic import BaseModel, Field

from zoikorum.shared.errors import NotFound, ValidationFailed
from zoikorum.shared.storage import get_storage

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ContentType = Literal["application/pdf", "image/jpeg", "image/png", "text/csv",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]

_MAGIC = {"application/pdf": b"%PDF-", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n",
          DOCX: b"PK\x03\x04", XLSX: b"PK\x03\x04"}
_EXTENSIONS = {"application/pdf": (".pdf",), "image/jpeg": (".jpg", ".jpeg"), "image/png": (".png",), "text/csv": (".csv",),
               DOCX: (".docx",), XLSX: (".xlsx",)}


class UploadIn(BaseModel):
    """A document sent with a request: its bytes (base64) plus the fingerprint the browser computed."""

    name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=MAX_FILE_BYTES)
    contentType: ContentType
    dataBase64: str = Field(min_length=4, max_length=14 * 1024 * 1024)


class StoredFileOut(BaseModel):
    name: str
    sha256: str
    size: int
    contentType: str | None = None
    hasFile: bool = False  # False for records made before files were stored (fingerprint only)


def _looks_like(content_type: str, data: bytes) -> bool:
    if content_type == "text/csv":
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return data.startswith(_MAGIC[content_type])


def checked_bytes(f: UploadIn) -> bytes:
    """Decodes one upload and checks extension, type, size and fingerprint. Raises a plain-language error."""
    try:
        data = base64.b64decode(f.dataBase64, validate=True)
    except ValueError as exc:
        raise ValidationFailed(f"{f.name} could not be read. Please upload it again.", code="INVALID_FILE") from exc
    if len(data) != f.size or len(data) > MAX_FILE_BYTES:
        raise ValidationFailed(f"{f.name} must be a complete file under 10 MB", code="INVALID_FILE")
    if not f.name.lower().endswith(_EXTENSIONS[f.contentType]) or not _looks_like(f.contentType, data):
        raise ValidationFailed(f"{f.name} is not a supported file (PDF, Word, Excel, CSV, JPG or PNG)", code="INVALID_FILE_TYPE")
    if hashlib.sha256(data).hexdigest() != f.sha256:
        raise ValidationFailed(f"{f.name} changed during upload. Please upload it again.", code="FINGERPRINT_MISMATCH")
    return data


def store_uploads(prefix: str, files: list[UploadIn]) -> list[dict]:
    """Checks every file first, then stores them. Returns the records to keep in JSONB."""
    checked = [(f, checked_bytes(f)) for f in files]
    if sum(len(d) for _, d in checked) > MAX_TOTAL_BYTES:
        raise ValidationFailed("Files sent together must add up to less than 25 MB", code="UPLOAD_TOO_LARGE")
    out = []
    for f, data in checked:
        key = f"{prefix}/{f.sha256}"
        get_storage().put(key, data)
        out.append({"name": f.name, "sha256": f.sha256, "size": len(data), "contentType": f.contentType, "key": key})
    return out


def file_out(record: dict) -> StoredFileOut:
    return StoredFileOut(name=record["name"], sha256=record["sha256"], size=record["size"],
                         contentType=record.get("contentType"), hasFile=bool(record.get("key")))


def find_file(records: list[dict], sha256: str) -> dict:
    rec = next((r for r in records if r.get("sha256") == sha256), None)
    if rec is None:
        raise NotFound("File not found")
    if not rec.get("key"):
        raise NotFound("This file was recorded before uploads were stored. Ask for it to be uploaded again.", code="FILE_NOT_STORED")
    return rec


def read_file(record: dict) -> bytes:
    data = get_storage().get(record["key"])
    if data is None:
        raise NotFound("File not found")
    return data


def file_response(data: bytes, content_type: str | None, name: str) -> Response:
    """Inline, never cached, sandboxed, and no type sniffing."""
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:120] or "document"
    return Response(data, media_type=content_type or "application/octet-stream", headers={
        "Content-Disposition": f'inline; filename="{safe}"', "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
