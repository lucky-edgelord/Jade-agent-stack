"""Shared test helpers: an isolated HOME/state, a fake Base and a fake Vault (stdlib http.server), and running the CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
TOKEN = "jab_test_SECRET_token_0123456789"
REAL_HOME = os.environ.get("HOME", "")  # before isolate() swaps it (Playwright keeps its browsers under it)


def isolate(tc) -> Path:
    """a temp HOME, XDG dirs, working directory; no keyring"""
    d = Path(tempfile.mkdtemp(prefix="jade-test-"))
    old = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "JADE_CONFIG", "JADE_NO_KEYRING")}
    os.environ.update({"HOME": str(d), "XDG_CONFIG_HOME": str(d / "cfg"), "XDG_STATE_HOME": str(d / "state"), "JADE_NO_KEYRING": "1"})
    os.environ.pop("JADE_CONFIG", None)
    cwd = os.getcwd()
    os.chdir(d)

    def restore():
        os.chdir(cwd)
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    tc.addCleanup(restore)
    return d


class Fake:
    """a programmable HTTP server: routes[(method, path)] = fn(query, body, headers) -> (status, json)"""

    def __init__(self):
        self.routes = {}
        self.log = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self, m):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null") if n else None
                fake.log.append({"method": m, "path": u.path, "query": u.query, "headers": dict(self.headers), "body": body})
                fn = fake.routes.get((m, u.path)) or fake.routes.get((m, "*"))
                st, obj, hdr = 404, {"error": "no route"}, {}
                if fn:
                    r = fn({k: v[0] for k, v in parse_qs(u.query).items()}, body, self.headers)
                    st, obj = r[0], r[1]
                    hdr = r[2] if len(r) > 2 else {}
                b = json.dumps(obj).encode()
                self.send_response(st)
                self.send_header("Content-Type", "application/json")
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def fake_base(tools=None) -> Fake:
    f = Fake()
    tools = tools or [
        {"name": "server_info", "scope": "read", "destructive": False, "parameters": {"type": "object", "properties": {}}},
        {"name": "records_list", "scope": "read", "destructive": False, "parameters": {"type": "object", "properties": {"collection": {"type": "string"}}, "required": ["collection"]}},
        {"name": "record_create", "scope": "write", "destructive": False, "parameters": {"type": "object", "properties": {"collection": {"type": "string"}, "data": {"type": "object"}}, "required": ["collection"]}},
        {"name": "collection_delete", "scope": "schema", "destructive": True, "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "confirm": {"type": "string"}}}},
    ]
    seen = {}

    def auth(h):
        return h.get("Authorization") == f"Bearer {TOKEN}"

    def tool(q, b, h, name):
        if not auth(h):
            return 401, {"error": "bad token"}
        k = h.get("Idempotency-Key")
        if k and k in seen:
            return 200, seen[k], {"Idempotent-Replayed": "true"}
        out = {"result": {"server_info": {"version": "0.6.0", "scopes": ["read", "write"], "modules": []}, "records_list": {"items": [], "total": 0},
                          "record_create": {"id": "r1", **((b or {}).get("data") or {})}}.get(name, {"ok": True})}
        if k:
            seen[k] = out
        return 200, out

    f.routes[("GET", "/api/health")] = lambda q, b, h: (200, {"message": "API is healthy."})
    f.routes[("GET", "/api/agent/tools")] = lambda q, b, h: (200, tools) if auth(h) else (401, {"error": "no"})
    for t in tools:
        f.routes[("POST", f"/api/agent/tools/{t['name']}")] = (lambda n: lambda q, b, h: tool(q, b, h, n))(t["name"])
    return f


def fake_vault(legacy: bool) -> Fake:
    f = Fake()
    f.routes[("GET", "/v1/health")] = lambda q, b, h: (200, {"ok": True, "app": "jade-vault", "api": 1, **({} if legacy else {"query_token": False})})

    def status(q, b, h):
        if "token" in q:
            return (200, {"ok": True}) if legacy and q["token"] == TOKEN else (400, {"ok": False, "error": {"code": "query_token_refused", "message": "no"}})
        return (200, {"ok": True, "busy": False}) if h.get("Authorization") == f"Bearer {TOKEN}" else (401, {"ok": False, "error": {"code": "unauthorized", "message": "no"}})
    f.routes[("GET", "/v1/status")] = status
    f.routes[("GET", "/v1/chat")] = lambda q, b, h: (200, {"ok": True, "reply": "ready"}) if h.get("Authorization") == f"Bearer {TOKEN}" else (401, {})
    return f


def jade(*args, env=None, input=None, cwd=None):
    """run the CLI in a subprocess → (code, stdout, stderr)"""
    e = {**os.environ, **(env or {}), "PYTHONPATH": str(ROOT / "src")}
    p = subprocess.run([sys.executable, "-m", "jade.cli", *args], capture_output=True, text=True, env=e, input=input, cwd=cwd, timeout=120)
    return p.returncode, p.stdout, p.stderr


def write_config(d: Path, base: str | None = None, vault: str | None = None, approvals: dict | None = None) -> Path:
    import yaml
    t = {}
    if base:
        t["base"] = {"url": base, "token": "base"}
    if vault:
        t["vault"] = {"url": vault, "token": "vault"}
    p = d / "jade.config.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "targets": t, "approvals": approvals or {"base.read": ["*"]}}))
    return p
