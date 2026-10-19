"""Local scan API for the extension (127.0.0.1 only, random port, no network)."""
import base64
import http.client
import json
import socket

import pytest

from conftest import PAYROLL
from data_sentinel.browser_api import ScanAPI
from data_sentinel.destinations import categorize_host

TOKEN = "test-token-123"


@pytest.fixture
def api(engine):
    server = ScanAPI(engine, "alice", token=TOKEN, port=0)
    server.start()
    yield server
    server.stop()


def call(api, method, path, body=None, token=TOKEN, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=10)
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Sentinel-Token"] = token
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=data, headers=h)
    resp = conn.getresponse()
    out = resp.status, dict(resp.getheaders()), json.loads(resp.read() or b"{}")
    conn.close()
    return out


@pytest.mark.parametrize("host,expected", [
    ("drive.google.com", ("cloud", "unknown")), ("docs.google.com", ("cloud", "unknown")),
    ("www.dropbox.com", ("cloud", "unknown")), ("contoso-my.sharepoint.com", ("cloud", "unknown")),
    ("wetransfer.com", ("cloud", "unknown")), ("mega.nz", ("cloud", "unknown")),
    ("mail.google.com", ("email", "unknown")), ("outlook.office.com", ("email", "unknown")),
    ("web.whatsapp.com", ("messaging", "unknown")), ("web.telegram.org", ("messaging", "unknown")),
    ("app.slack.com", ("messaging", "unknown")), ("teams.microsoft.com", ("messaging", "unknown")),
    ("discord.com", ("messaging", "unknown")), ("chatgpt.com", ("genai", "unknown")),
    ("gemini.google.com", ("genai", "unknown")), ("claude.ai", ("genai", "unknown")),
    ("copilot.microsoft.com", ("genai", "unknown")), ("pastebin.com", ("paste_site", "unknown")),
    ("gist.github.com", ("paste_site", "unknown")), ("intranet.company.com", ("internal", "trusted")),
    ("company.com", ("internal", "trusted")), ("example.org", ("web", "unknown")),
    ("https://www.chatgpt.com/c/123", ("genai", "unknown")),
])
def test_destination_categories(host, expected):
    assert categorize_host(host) == expected


def test_health_needs_no_token_but_reports_it(api):
    status, headers, body = call(api, "GET", "/health", token=None)
    assert status == 200 and body["status"] == "ok" and "token_ok" not in body
    assert call(api, "GET", "/health")[2]["token_ok"] is True
    assert call(api, "GET", "/health", token="wrong")[2]["token_ok"] is False


def test_401_without_or_with_wrong_token(api):
    paste = {"kind": "paste", "host": "chatgpt.com", "text": "api_key = sk_live_51HxTestKeyOnly"}
    assert call(api, "POST", "/scan", paste, token=None)[0] == 401
    assert call(api, "POST", "/scan", paste, token="nope")[0] == 401


def test_secret_sent_to_whatsapp_is_blocked(api):
    status, _, body = call(api, "POST", "/scan", {"kind": "paste", "host": "web.whatsapp.com",
                                                  "text": "prod creds: password = Sup3rSecret!"})
    assert status == 200 and body["decision"] == "BLOCK" and body["enforce"] is True
    assert body["dest_type"] == "messaging" and body["sensitivity"] == "Restricted"
    assert body["message"] == ("Blocked by Data Sentinel: pasted text (Restricted) cannot be sent to "
                               "web.whatsapp.com.")
    assert "Sup3rSecret" not in json.dumps(body)


def test_api_key_pasted_into_chatgpt_is_blocked(api, db):
    status, _, body = call(api, "POST", "/scan", {"kind": "paste", "host": "chatgpt.com",
                                                  "text": "api_key = sk_live_51HxTestKeyOnly"})
    assert body["decision"] == "BLOCK" and body["dest_type"] == "genai"
    ev = db.one("SELECT channel, action_taken FROM transfer_events WHERE id = ?", (body["event_id"],))
    assert ev["channel"] == "browser" and ev["action_taken"] == "paste dropped in the browser"


def test_no_cors_headers(api):
    for method, path, body in [("GET", "/health", None), ("OPTIONS", "/scan", None),
                               ("POST", "/scan", {"kind": "paste", "host": "x.org", "text": "hello there everyone!"})]:
        _, headers, _ = call(api, method, path, body, headers={"Origin": "https://evil.example"})
        assert not any(h.lower().startswith("access-control-") for h in headers), (method, headers)


def test_harmless_paste_not_blocked(api):
    status, _, body = call(api, "POST", "/scan", {"kind": "paste", "host": "chatgpt.com",
                                                  "text": "Can you help me write a birthday poem for my cat?"})
    assert status == 200 and body["decision"] == "ALLOW" and body["message"] == ""


def test_upload_with_content(api):
    b64 = base64.b64encode(PAYROLL.encode()).decode()
    _, _, body = call(api, "POST", "/scan", {"kind": "upload", "host": "drive.google.com",
                                             "file": {"name": "payroll.csv", "size": len(PAYROLL), "content_b64": b64}})
    assert body["decision"] == "BLOCK"
    assert body["message"] == "Blocked by Data Sentinel: payroll.csv (Restricted) cannot be sent to drive.google.com."


def test_oversized_upload_judged_by_name_and_size(api):
    _, _, body = call(api, "POST", "/scan", {"kind": "upload", "host": "drive.google.com",
                                             "file": {"name": "customer_data_full.zip", "size": 250_000_000}})
    assert body["sensitivity"] == "Confidential"          # from the file name
    assert any("judged by file name and size" in r for r in body["reasons"])
    assert any("large file" in r for r in body["reasons"])
    assert body["decision"] == "BLOCK"


def test_413_when_request_too_large(api):
    with socket.create_connection(("127.0.0.1", api.port), timeout=10) as s:
        s.sendall((f"POST /scan HTTP/1.1\r\nHost: 127.0.0.1:{api.port}\r\nX-Sentinel-Token: {TOKEN}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {api.max_body + 1}\r\n\r\n").encode())
        reply = s.recv(4096).decode()
    assert reply.startswith("HTTP/1.0 413") or reply.startswith("HTTP/1.1 413")


def test_bad_host_header_rejected(api):
    status, _, _ = call(api, "GET", "/health", headers={"Host": "attacker.example:8765"})
    assert status == 403


def test_dry_run_lets_block_through(dry_engine):
    server = ScanAPI(dry_engine, "alice", token=TOKEN, port=0)
    server.start()
    try:
        _, _, body = call(server, "POST", "/scan", {"kind": "paste", "host": "pastebin.com",
                                                    "text": "AWS key AKIAABCDEFGHIJKLMNOP leaked"})
        assert body["decision"] == "BLOCK" and body["enforce"] is False and body["dry_run"] is True
    finally:
        server.stop()
