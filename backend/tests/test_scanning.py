"""Every upload is scanned for malware before it is stored; an infected file is refused, and so is every file while the
scanner cannot be reached (fail closed). A small stand-in speaks the clamd INSTREAM protocol."""

from __future__ import annotations

import base64
import hashlib
import socketserver
import struct
import threading

import pytest

from test_professional import new_pro
from zoikorum.config import get_settings
from zoikorum.shared import scanning
from zoikorum.shared.errors import ServiceUnavailable, ValidationFailed
from zoikorum.shared.uploads import UploadIn, store_uploads

# The standard anti-virus test file (harmless; every scanner reports it as Eicar-Test-Signature).
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class _Clamd(socketserver.BaseRequestHandler):
    def handle(self):
        command = b""
        while not command.endswith(b"\0"):
            command += self.request.recv(1)
        if command == b"zPING\0":
            self.request.sendall(b"PONG\0")
            return
        data = b""
        while True:
            (size,) = struct.unpack("!I", self.request.recv(4, socketserver.socket.MSG_WAITALL))
            if not size:
                break
            while size:
                part = self.request.recv(size)
                data, size = data + part, size - len(part)
        self.server.seen.append(len(data))
        self.request.sendall(b"stream: Eicar-Test-Signature FOUND\0" if EICAR in data else b"stream: OK\0")


@pytest.fixture
def clamd(monkeypatch):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Clamd)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = get_settings()
    monkeypatch.setattr(s, "malware_scanner", "clamav")
    monkeypatch.setattr(s, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(s, "clamav_port", server.server_address[1])
    yield server
    server.shutdown()
    server.server_close()


def upload(data: bytes, name="report.pdf") -> UploadIn:
    return UploadIn(name=name, sha256=hashlib.sha256(data).hexdigest(), size=len(data), contentType="application/pdf",
                    dataBase64=base64.b64encode(data).decode())


@pytest.mark.unit
def test_clean_files_pass_and_infected_ones_are_refused_before_anything_is_stored(clamd, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    assert scanning.ping()
    clean = upload(b"%PDF-1.4 quarterly figures")
    infected = upload(b"%PDF-1.4 " + EICAR, name="invoice.pdf")
    with pytest.raises(ValidationFailed) as blocked:
        store_uploads("tests/scan", [clean, infected])
    assert blocked.value.code == "FILE_INFECTED" and "invoice.pdf" in str(blocked.value) and "Eicar" in str(blocked.value)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]  # the clean file was not kept either
    assert store_uploads("tests/scan", [clean])[0]["sha256"] == clean.sha256


@pytest.mark.unit
def test_uploads_are_refused_while_the_scanner_is_down(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "malware_scanner", "clamav")
    monkeypatch.setattr(s, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(s, "clamav_port", 1)  # nothing listens here
    with pytest.raises(ServiceUnavailable) as down:
        scanning.scan(b"%PDF-1.4", "report.pdf")
    assert down.value.code == "SCANNER_UNAVAILABLE"
    assert scanning.ping() is False


async def test_an_infected_profile_photo_is_refused(client, make_user, clamd):
    u, _ = await new_pro(client, make_user)
    photo = b"\x89PNG\r\n\x1a\n" + EICAR
    r = await client.put("/v1/professionals/me/photo", headers=u.h,
                         json={"contentType": "image/png", "dataBase64": base64.b64encode(photo).decode()})
    assert r.status_code == 422 and r.json()["code"] == "FILE_INFECTED"
    assert clamd.seen == [len(photo)]
