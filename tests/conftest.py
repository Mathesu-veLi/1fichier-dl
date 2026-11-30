"""Shared fixtures: a tiny stand-in for the 1fichier HTTP API."""

from __future__ import annotations

import http.server
import threading
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse

import pytest


@dataclass
class MockState:
    payload: bytes = b"mock 1fichier payload\n" * 100
    filename: str = "test.bin"
    password: Optional[str] = None
    wait_minutes: int = 0
    range_requests: list[str] = field(default_factory=list)
    cookie_headers: list[str] = field(default_factory=list)


class MockFichierHandler(http.server.BaseHTTPRequestHandler):
    server_version = "MockFichier/1.0"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def _send(self, body: bytes, status: int = 200, headers: Optional[dict] = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _port(self) -> int:
        return self.server.server_address[1]

    def _info_page(self) -> bytes:
        state = self.server.state
        return (
            "<html><body>"
            "<div class='tiers'>"
            f"<span class='tier-name'>{state.filename}</span>"
            f"<span class='tier-feat'>{len(state.payload)} B</span>"
            "</div>"
            "</body></html>"
        ).encode()

    def _password_page(self, error: str = "") -> bytes:
        state = self.server.state
        notice = f"<div class='notice notice-alert'>{error}</div>" if error else ""
        return (
            "<html><body>"
            f"{notice}"
            "<form method='post'>"
            "<input type='password' name='pass' id='pass' />"
            "</form>"
            "</body></html>"
        ).encode()

    def _direct_page(self) -> bytes:
        state = self.server.state
        return (
            "<html><body>"
            "<div></div><div></div><div></div>"
            "<div><div></div><div>"
            f"<a href=\"http://127.0.0.1:{self._port()}/file/{state.filename}\">download</a>"
            "</div></div>"
            "</body></html>"
        ).encode()

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        state = self.server.state
        state.cookie_headers.append(self.headers.get("Cookie", ""))
        parsed = urlparse(self.path)

        if parsed.path.startswith("/file/"):
            payload = state.payload
            start = 0
            range_header = self.headers.get("Range", "")
            if range_header.startswith("bytes="):
                start = int(range_header.split("=", 1)[1].split("-", 1)[0])
                state.range_requests.append(range_header)

            body = payload[start:]
            headers = {
                "Content-Disposition": f'attachment; filename="{state.filename}"',
            }
            status = 200
            if start:
                status = 206
                headers["Content-Range"] = f"bytes {start}-{len(payload) - 1}/{len(payload)}"
            self._send(body, status, headers)
            return

        if state.password:
            self._send(self._password_page())
        else:
            self._send(self._info_page())

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        state = self.server.state
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode())
        supplied = form.get("pass", [""])[0]

        if state.password and supplied != state.password:
            error = "Incorrect password." if supplied else ""
            self._send(self._password_page(error))
            return

        if state.wait_minutes:
            body = (
                "<html><body>"
                "<div class='notice notice-alert'>"
                "Without subscription, you must wait between downloads. "
                f"You must wait {state.wait_minutes} minutes or subscribe."
                "</div>"
                f"<script>var ct = {state.wait_minutes}*60;</script>"
                "</body></html>"
            ).encode()
            self._send(body)
            return

        self._send(self._direct_page())


class MockFichierServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: MockState) -> None:
        super().__init__(("127.0.0.1", 0), MockFichierHandler)
        self.state = state

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?test"


@pytest.fixture
def fichier_server():
    state = MockState()
    server = MockFichierServer(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
