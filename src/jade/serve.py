"""`jade serve`: playbooks and commands over HTTP. Loopback by default (127.0.0.1:9765); anywhere else needs --token,
which clients send as Authorization: Bearer <token> (never in the URL). Same payloads as the CLI's --json.

    GET  /healthz
    GET  /v1/playbooks
    POST /v1/playbooks/{name}/run      {"vars": {...}, "fresh": false}
    GET  /v1/commands                  (the list)
    POST /v1/commands/{name}           {...arguments}
    GET  /v1/docs/search?q=…   GET /v1/docs/{topic}   (the docs browser)
"""

from __future__ import annotations

import hmac
import json
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import commands
from .errors import JadeError
from .redact import deep, register


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def make_server(host: str, port: int, token: str | None, ctx: commands.Context) -> ThreadingHTTPServer:
    if not _loopback(host) and not token:
        raise JadeError(f"serving on {host} needs --token (clients send Authorization: Bearer <token>)", "JADE302")
    if token:
        register(token)
    ctx.surface, ctx.interactive, ctx.ask = "http", False, None

    class H(BaseHTTPRequestHandler):
        server_version = "jade-serve"

        def log_message(self, *a: Any) -> None:
            pass

        def send(self, code: int, obj: Any) -> None:
            b = json.dumps(deep(obj), default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def authed(self) -> bool:
            q = parse_qs(urlparse(self.path).query)
            if "token" in q or "access_token" in q:
                self.send(400, commands.envelope(False, error=JadeError("tokens in URLs are refused; send Authorization: Bearer", "JADE102")))
                return False
            if not token:
                return True
            a = self.headers.get("Authorization", "")
            if a.lower().startswith("bearer ") and hmac.compare_digest(a[7:].strip().encode(), token.encode()):
                return True
            self.send(401, commands.envelope(False, error=JadeError("missing or wrong token", "JADE101")))
            return False

        def body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            j = json.loads(self.rfile.read(min(n, 32 << 20)) or b"{}")
            if not isinstance(j, dict):
                raise JadeError("the body must be a JSON object", "JADE400")
            return j

        def run(self, name: str, args: dict) -> None:
            try:
                data = commands.call(name, args, ctx)
                self.send(200, commands.envelope(True, data, command=name))
            except JadeError as e:
                self.send({1: 400, 2: 502, 3: 403}.get(e.exit_code, 400) if e.code != "JADE405" else 404, commands.envelope(False, error=e, command=name))

        def do_GET(self) -> None:
            u = urlparse(self.path)
            if u.path == "/healthz":
                return self.send(200, {"ok": True, "app": "jade-agent-stack"})
            if not self.authed():
                return
            parts = [unquote(x) for x in u.path.strip("/").split("/")]
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if parts == ["v1", "playbooks"]:
                return self.run("playbook.list", {})
            if parts == ["v1", "commands"]:
                return self.run("commands", {})
            if parts[:3] == ["v1", "docs", "search"]:
                return self.run("docs.search", {"query": q.get("q", ""), **({"limit": q["limit"]} if "limit" in q else {})})
            if parts == ["v1", "docs"]:
                return self.run("docs.topics", {})
            if parts[:2] == ["v1", "docs"] and len(parts) == 3:
                return self.run("docs.show", {"ref": parts[2] + (("#" + q["section"]) if q.get("section") else "")})
            self.send(404, commands.envelope(False, error=JadeError(f"no route {u.path}", "JADE405")))

        def do_POST(self) -> None:
            if not self.authed():
                return
            parts = [unquote(x) for x in urlparse(self.path).path.strip("/").split("/")]
            try:
                b = self.body()
            except (ValueError, JadeError) as e:
                return self.send(400, commands.envelope(False, error=JadeError(f"bad body: {e}", "JADE400")))
            if len(parts) == 4 and parts[:2] == ["v1", "playbooks"] and parts[3] == "run":
                v = b.get("vars") or {}
                return self.run("playbook.run", {"name": parts[2], "var": [f"{k}={json.dumps(x)}" for k, x in v.items()], "fresh": bool(b.get("fresh"))})
            if len(parts) == 3 and parts[:2] == ["v1", "commands"]:
                c = commands.REGISTRY.get(parts[2])
                if not c or "http" not in c.surfaces:
                    return self.send(404, commands.envelope(False, error=JadeError(f"no command {parts[2]}", "JADE405")))
                return self.run(parts[2], b)
            self.send(404, commands.envelope(False, error=JadeError("no route", "JADE405")))

    return ThreadingHTTPServer((host, port), H)


def serve(host: str, port: int, token: str | None, ctx: commands.Context) -> dict:
    srv = make_server(host, port, token, ctx)
    import sys
    print(f"jade serve on http://{host}:{port} (Ctrl-C to stop)", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return {"stopped": True}
