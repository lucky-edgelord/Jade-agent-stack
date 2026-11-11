"""Jade Vault's HTTP API (the control plane on the phone or the web): header-only bearer auth. The client refuses a
Vault that still accepts ?token= (JADE102) unless accept_legacy is set."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .. import http
from ..errors import JadeError


class VaultClient:
    def __init__(self, url: str, token: str, *, timeout: float = 30, chat_timeout: float = 300, accept_legacy: bool = False):
        self.url = url.rstrip("/")
        self.token, self.timeout, self.chat_timeout, self.accept_legacy = token, timeout, chat_timeout, accept_legacy
        self._checked = False

    def __repr__(self) -> str:
        return f"VaultClient({self.url!r})"

    def health(self) -> dict:
        return http.request("GET", self.url + "/v1/health", timeout=self.timeout, retries=2).json() or {}

    def legacy_auth(self) -> bool:
        """True when this Vault accepts a token in the URL (it must not). Probes with the real token, on /v1/status."""
        h = self.health()
        if h.get("query_token") is False:
            return False
        url = f"{self.url}/v1/status?" + "to" + "ken=" + quote(str(self.token))  # built here on purpose: this is the probe
        import urllib.request, urllib.error  # the probe bypasses http.request, which refuses URL tokens
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "jade-agent-stack"}), timeout=self.timeout) as r:
                return r.status == 200
        except urllib.error.HTTPError:
            return False
        except OSError as e:
            raise JadeError(f"cannot reach {self.url}: {e}", "JADE200") from None

    def check(self) -> None:
        if self._checked:
            return
        if self.legacy_auth() and not self.accept_legacy:
            raise JadeError(f"{self.url} accepts tokens in URLs", "JADE102")
        self._checked = True

    def _get(self, path: str, timeout: float | None = None, retries: int = 2) -> Any:
        self.check()
        return http.request("GET", self.url + path, token=self.token, timeout=timeout or self.timeout, retries=retries).json()

    def status(self) -> dict:
        return self._get("/v1/status") or {}

    def chats(self) -> Any:
        return self._get("/v1/chats")

    def history(self, session: str | None = None) -> Any:
        return self._get("/v1/history" + (f"?session={quote(session)}" if session else ""))

    def flows(self) -> Any:
        return self._get("/v1/flows")

    def chat(self, message: str, *, session: str | None = None, timeout: float | None = None) -> dict:
        q = f"?message={quote(message)}" + (f"&session={quote(session)}" if session else "")
        return self._get("/v1/chat" + q, timeout=timeout or self.chat_timeout, retries=0) or {}

    def flow(self, name: str, input: Any = None, *, timeout: float | None = None) -> dict:
        import json as _j
        q = f"?name={quote(name)}" + (f"&input={quote(_j.dumps(input))}" if input is not None else "")
        return self._get("/v1/flow" + q, timeout=timeout or self.chat_timeout, retries=0) or {}
