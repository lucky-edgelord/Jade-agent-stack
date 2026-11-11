"""Jade Agent Base over REST: tools, task credentials, the audit log. (MCP: jade.resources.mcp.)"""

from __future__ import annotations

from typing import Any

from .. import http
from ..errors import JadeError, RemoteError
from ..ids import uuid7


class BaseClient:
    def __init__(self, url: str, token: str, *, timeout: float = 30):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._tools: dict[str, dict] | None = None
        self.last_key: str | None = None

    def __repr__(self) -> str:
        return f"BaseClient({self.url!r})"

    def health(self, *, timeout: float | None = None) -> dict:
        return http.request("GET", self.url + "/api/health", timeout=timeout or self.timeout, retries=2).json() or {}

    def tools(self, format: str | None = None, *, timeout: float | None = None) -> list[dict]:
        """the tools this token may use: format None (with scope and destructive), openai, anthropic or mcp"""
        q = f"?format={format}" if format else ""
        return http.request("GET", f"{self.url}/api/agent/tools{q}", token=self.token, timeout=timeout or self.timeout, retries=2).json() or []

    def tool(self, name: str) -> dict | None:
        if self._tools is None:
            self._tools = {t["name"]: t for t in self.tools()}
        return self._tools.get(name)

    def is_read(self, name: str) -> bool:
        t = self.tool(name)
        return bool(t and t.get("scope") == "read")

    def call(self, name: str, args: dict | None = None, *, idempotency_key: str | None = None, timeout: float | None = None) -> Any:
        """run a tool. Reads retry; mutations do not, and always carry an idempotency key (a UUIDv7 when not given)."""
        read = self.is_read(name)
        h = {}
        if not read:
            idempotency_key = idempotency_key or uuid7()
            h["Idempotency-Key"] = idempotency_key
        self.last_key = idempotency_key
        r = http.request("POST", f"{self.url}/api/agent/tools/{name}", token=self.token, body=args or {}, headers=h,
                         timeout=timeout or self.timeout, retries=2 if read else 0)
        j = r.json() or {}
        return j.get("result")

    def server_info(self) -> dict:
        return self.call("server_info") or {}

    def version(self) -> str:
        return str(self.server_info().get("version", ""))

    def audit(self, *, limit: int = 50, tool: str | None = None) -> list[dict]:
        r = self.call("audit_list", {"limit": limit, **({"tool": tool} if tool else {})})
        return r if isinstance(r, list) else (r or {}).get("items", r) or []

    # task credentials (Base 0.6+)
    def mint(self, task_id: str, scopes: list[str], ttl: str = "15m") -> dict:
        try:
            return http.request("POST", self.url + "/api/agent/credentials", token=self.token,
                                body={"task_id": task_id, "scopes": scopes, "ttl": ttl}, timeout=self.timeout).json()
        except RemoteError as e:
            if e.status == 404:
                raise JadeError("this Base has no task credentials (it is older than 0.6)", "JADE203") from None
            raise

    def revoke(self, credential_id: str) -> None:
        http.request("POST", f"{self.url}/api/agent/credentials/{credential_id}/revoke", token=self.token, timeout=self.timeout)

    def with_token(self, token: str) -> "BaseClient":
        c = BaseClient(self.url, token, timeout=self.timeout)
        c._tools = self._tools
        return c
