"""Local scan API used by the browser extension.

Listens on 127.0.0.1 only.  POST /scan (needs X-Sentinel-Token)  and  GET /health.
* No CORS headers are ever sent, so ordinary web pages cannot read the API.
* The Host header must be 127.0.0.1/localhost (blocks DNS-rebinding tricks).
* Bodies larger than MAX_BODY get 413. Files above 20 MB arrive as name + size only and are
  judged without content - nothing is written to disk.

Request:  {"kind": "upload"|"drop"|"paste", "host": "chatgpt.com", "url": "...",
           "file": {"name": "a.csv", "size": 123, "content_b64": "..."}}   or   {"kind": "paste", "text": "..."}
Response: {"decision", "level", "score", "sensitivity", "reasons", "message", "enforce", ...}
"""
import base64
import binascii
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .destinations import categorize_host, normalize_host
from .engine import Payload

MAX_BODY = 28 * 1024 * 1024        # a 20 MB file is ~26.7 MB once base64-encoded


def load_or_create_token(path=None):
    path = str(path or config.TOKEN_PATH)
    if os.path.exists(path):
        with open(path) as fh:
            token = fh.read().strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    return token


def payload_from_request(req):
    kind = req.get("kind", "upload")
    if "text" in req and req.get("text") is not None:
        label = "dropped text" if kind == "drop" else "pasted text"
        return Payload.from_text(label, str(req["text"]))
    f = req.get("file") or {}
    name = os.path.basename(str(f.get("name") or "unnamed file")) or "unnamed file"
    size = int(f.get("size") or 0)
    content = f.get("content_b64")
    if content is None:
        mb = size / 1e6
        return Payload.name_only(name, size, f"file of {mb:.1f} MB sent as name and size only")
    try:
        data = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("content_b64 is not valid base64")
    return Payload.from_bytes(name, data)


class _Handler(BaseHTTPRequestHandler):
    server_version = "DataSentinel/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):          # keep the console for decisions
        pass

    # -------------------------------------------------------------- helpers
    def _send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost")

    def _token_ok(self):
        sent = self.headers.get("X-Sentinel-Token") or ""
        return bool(sent) and hmac.compare_digest(sent.encode(), self.server.api.token.encode())

    # -------------------------------------------------------------- routes
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if self.path.split("?")[0] == "/health":
            out = {"status": "ok", "service": "data-sentinel", "dry_run": self.server.api.engine.dry_run}
            if self.headers.get("X-Sentinel-Token") is not None:
                out["token_ok"] = self._token_ok()
            return self._send(200, out)
        return self._send(404, {"error": "not found"})

    def do_OPTIONS(self):                        # no CORS: preflights are simply refused
        self._send(405, {"error": "method not allowed"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if self.path.split("?")[0] != "/scan":
            return self._send(404, {"error": "not found"})
        if not self._token_ok():
            return self._send(401, {"error": "missing or wrong X-Sentinel-Token"})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._send(411, {"error": "Content-Length required"})
        if length > self.server.api.max_body:
            self.close_connection = True
            return self._send(413, {"error": f"request too large (max {self.server.api.max_body} bytes); "
                                             "send files above 20 MB as name + size only"})
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("JSON object expected")
            payload = payload_from_request(req)
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        try:
            result = self.server.api.scan(req, payload)
        except Exception as exc:                 # report, never crash the server thread
            return self._send(500, {"error": f"scan failed: {type(exc).__name__}"})
        return self._send(200, result)


class ScanAPI:
    def __init__(self, engine, user, token=None, host=config.API_HOST, port=config.API_PORT, role="employee",
                 max_body=MAX_BODY, on_decision=None):
        self.engine = engine
        self.user = user
        self.role = role
        self.token = token or load_or_create_token()
        self.max_body = max_body
        self.on_decision = on_decision
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.api = self
        self.thread = None

    @property
    def port(self):
        return self.httpd.server_address[1]

    def scan(self, req, payload):
        host = normalize_host(req.get("host") or req.get("url") or "unknown")
        dest_type, trust = categorize_host(host)
        channel = "browser"
        d = self.engine.process(self.user, payload, host or "unknown", dest_type, channel, role=self.role, trust=trust)
        action = None
        kind = req.get("kind", "upload")
        if d.enforce:
            action = f"{kind} dropped in the browser"
        elif d.decision == "BLOCK":
            action = f"dry-run: {kind} allowed through"
        if action:
            self.engine.record_response(d.event_id, action)
        if self.on_decision:
            self.on_decision(d, action, host)
        out = d.to_dict()
        out.update({"destination": host, "message": d.user_message(host), "kind": kind})
        return out

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="browser-api")
        self.thread.start()
        return self.thread

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
