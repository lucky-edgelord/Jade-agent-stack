"""A Streamable-HTTP MCP client (JSON answers): initialize, tools/list, tools/call with an idempotency key in _meta,
batches, structured errors and timeouts."""

from __future__ import annotations

from typing import Any

from .. import http
from ..errors import JadeError, RemoteError
from ..ids import uuid7

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


class MCPClient:
    def __init__(self, url: str, token: str | None = None, *, timeout: float = 30):
        self.url, self.token, self.timeout = url, token, timeout
        self.session: str | None = None
        self.protocol: str | None = None
        self.server: dict = {}
        self._id = 0

    def _post(self, payload: Any, timeout: float | None = None) -> Any:
        h = {"Accept": "application/json, text/event-stream"}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        r = http.request("POST", self.url, token=self.token, body=payload, headers=h, timeout=timeout or self.timeout, raw=True)
        if r.status == 403:
            raise http.error_for(r, self.url)
        if r.status == 401:
            raise http.error_for(r, self.url)
        if r.status == 202:
            return None
        if r.status >= 400:
            raise http.error_for(r, self.url)
        if "mcp-session-id" in r.headers:
            self.session = r.headers["mcp-session-id"]
        return r.json()

    def rpc(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> Any:
        self._id += 1
        j = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, **({"params": params} if params is not None else {})}, timeout)
        if not isinstance(j, dict):
            raise JadeError(f"{method}: the server did not answer JSON-RPC", "JADE201")
        if "error" in j:
            e = j["error"] or {}
            raise RemoteError(f"{method}: {e.get('message')} ({e.get('code')})", data={"rpc_code": e.get("code")})
        return j.get("result")

    def initialize(self) -> dict:
        r = self.rpc("initialize", {"protocolVersion": PROTOCOLS[0], "capabilities": {}, "clientInfo": {"name": "jade-agent-stack", "version": "0.1.0"}})
        v = (r or {}).get("protocolVersion")
        if v not in PROTOCOLS:
            raise JadeError(f"the server speaks MCP {v!r}; this client speaks {', '.join(PROTOCOLS)}", "JADE201")
        self.protocol, self.server = v, r or {}
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.server

    def tools(self) -> list[dict]:
        if not self.protocol:
            self.initialize()
        return (self.rpc("tools/list") or {}).get("tools", [])

    def call(self, name: str, args: dict | None = None, *, idempotency_key: str | None = None, read: bool = False, timeout: float | None = None) -> dict:
        """→ {"ok", "result", "text", "replayed", "error"}"""
        if not self.protocol:
            self.initialize()
        meta = {} if read else {"idempotency_key": idempotency_key or uuid7()}
        r = self.rpc("tools/call", {"name": name, "arguments": args or {}, **({"_meta": meta} if meta else {})}, timeout=timeout) or {}
        text = "".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        sc = r.get("structuredContent")
        out = sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
        return {"ok": not r.get("isError"), "result": out, "text": text, "replayed": bool((r.get("_meta") or {}).get("replayed")),
                "error": text if r.get("isError") else None, "idempotency_key": meta.get("idempotency_key")}

    def batch(self, calls: list[tuple[str, dict | None]]) -> list[Any]:
        if not self.protocol:
            self.initialize()
        reqs = []
        for name, args in calls:
            self._id += 1
            reqs.append({"jsonrpc": "2.0", "id": self._id, "method": name, **({"params": args} if args is not None else {})})
        out = self._post(reqs) or []
        by = {x.get("id"): x for x in out if isinstance(x, dict)}
        return [by.get(r["id"], {}).get("result", by.get(r["id"], {}).get("error")) for r in reqs]
