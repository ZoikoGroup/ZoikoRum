"""Malware scanning of every file people upload, before it is stored (request and proposal attachments, delivered work,
dispute and verification evidence, message files, profile photos).

ZK_MALWARE_SCANNER=clamav sends each file to a ClamAV daemon (clamd, INSTREAM over TCP: ZK_CLAMAV_HOST, ZK_CLAMAV_PORT).
A file with a known signature is refused with a plain message; if the scanner cannot be reached the upload is refused
too (fail closed: nothing unscanned is stored). ``none`` (development only) skips scanning; production refuses it.
"""

from __future__ import annotations

import logging
import socket
import struct

from zoikorum.config import get_settings
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed

log = logging.getLogger("zoikorum.scanning")
CHUNK = 64 * 1024


def _clamd(command: bytes, data: bytes | None = None, timeout: float = 30.0) -> str:
    s = get_settings()
    with socket.create_connection((s.clamav_host, s.clamav_port), timeout=timeout) as conn:
        conn.sendall(b"z" + command + b"\0")
        if data is not None:
            for i in range(0, len(data), CHUNK):
                part = data[i:i + CHUNK]
                conn.sendall(struct.pack("!I", len(part)) + part)
            conn.sendall(struct.pack("!I", 0))
        reply = b""
        while not reply.endswith(b"\0"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            reply += chunk
    return reply.rstrip(b"\0").decode("utf-8", "replace").strip()


def ping() -> bool:
    try:
        return _clamd(b"PING", timeout=5.0) == "PONG"
    except OSError:
        return False


def scan(data: bytes, name: str) -> None:
    """Raises FILE_INFECTED (422) for a file with a known malware signature, SCANNER_UNAVAILABLE (503) when the file
    cannot be checked. Returns quietly for a clean file."""
    if get_settings().malware_scanner != "clamav":
        return
    try:
        reply = _clamd(b"INSTREAM", data)
    except OSError as exc:
        log.error("malware scanner unreachable: %s", type(exc).__name__)
        raise ServiceUnavailable("Files cannot be checked for viruses right now, so nothing was uploaded. "
                                 "Please try again in a few minutes.", code="SCANNER_UNAVAILABLE") from exc
    if reply.endswith("FOUND"):
        signature = reply.removeprefix("stream:").removesuffix("FOUND").strip()
        log.warning("upload blocked: malware signature %s (%d bytes)", signature, len(data))
        raise ValidationFailed(f"{name} was blocked because it contains malware ({signature}). Nothing was uploaded. "
                               "Please check your computer and upload a clean copy.", code="FILE_INFECTED")
    if not reply.endswith("OK"):  # e.g. "INSTREAM size limit exceeded. ERROR"
        log.error("malware scanner could not check a file: %s", reply[:200])
        raise ServiceUnavailable(f"{name} could not be checked for viruses, so it was not uploaded. Please try again "
                                 "or send a smaller file.", code="SCANNER_UNAVAILABLE")
