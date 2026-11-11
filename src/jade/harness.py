"""The harness: every SDK call and command goes through it, in this process (no daemon). It loads the config and
secrets, enforces approvals before a call leaves, gives mutations idempotency keys, mints task credentials, checks
versions against STACK.md, and routes a tool to the target that owns it.

    h = Harness.load()
    h.require("base.write", "record_create:bookings")
    with h.with_idempotency("0190…"):
        h.call("base", "record_create", {"collection": "bookings", "data": {...}})
    with h.task("provision-booking", scopes=["read", "write", "schema"]):
        ...                                        # Base calls use a 15-minute credential with just those scopes
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any, Callable, Iterator

from . import compat, http
from .approvals import Approvals, Decision, base_target
from .config import Config, secret_name
from .errors import JadeError
from .ids import uuid7
from .resources.base import BaseClient
from .resources.vault import VaultClient
from .secrets import Store


def tty_ask(q: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        raise JadeError(f"{q} (no terminal to ask; add an approval or pass --yolo)", "JADE300")
    print(q + " [y/N] ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip().lower() in ("y", "yes")


class Harness:
    def __init__(self, config: Config, *, ask: Callable[[str], bool] | None = None, yolo: bool = False, accept_legacy: bool = False,
                 accept_file_secrets: bool | None = None, warn: Callable[[str], None] | None = None):
        self.config = config
        self.ask = ask
        self.yolo = yolo
        self.accept_legacy = accept_legacy or bool(config.get("targets.vault.accept_legacy"))
        self.secrets = Store(allow_file=bool(config.get("secrets.file")) if accept_file_secrets is None else accept_file_secrets)
        self.approvals = Approvals(config.get("approvals") or {})
        self.warn = warn or (lambda m: http.eprint("warning: " + m))
        self._key: str | None = None
        self._task: dict | None = None
        self._base: BaseClient | None = None
        self._vault: VaultClient | None = None
        self.calls: list[dict] = []  # what left this process (for --json and tests)
        if yolo:
            self.warn("--yolo: approvals that nobody gave are allowed, and logged")

    @classmethod
    def load(cls, path: str | None = None, **kw: Any) -> "Harness":
        return cls(Config.load(path), **kw)

    # ---- targets ----
    def _token(self, target: str) -> str:
        t = self.config.target(target)
        if not t.get("url"):
            raise JadeError(f"no {target} target in jade.config.yaml (run `jade init`)", "JADE100")
        return self.secrets.get(t.get("token") or secret_name(t["url"]))  # type: ignore[return-value]

    @property
    def base(self) -> BaseClient:
        if self._base is None:
            t = self.config.target("base")
            self._base = BaseClient(t.get("url", ""), self._token("base"), timeout=t.get("timeout") or self.config.get("defaults.timeout", 30))
        if self._task and self._task.get("token"):
            return self._base.with_token(self._task["token"])
        return self._base

    @property
    def vault(self) -> VaultClient:
        if self._vault is None:
            t = self.config.target("vault")
            self._vault = VaultClient(t.get("url", ""), self._token("vault"), timeout=t.get("timeout") or self.config.get("defaults.timeout", 30),
                                      chat_timeout=self.config.get("defaults.chat_timeout", 300), accept_legacy=self.accept_legacy)
        return self._vault

    def targets(self) -> list[str]:
        return [k for k in ("base", "vault", "kit") if self.config.target(k)] + ["local"]

    # ---- approvals ----
    def require(self, capability: str, target: str = "*", *, host: str | None = None, destructive: bool = False) -> Decision:
        d = self.approvals.check(capability, target, host=host, destructive=destructive)
        self.approvals.enforce(d, ask=self.ask, yolo=self.yolo, task=(self._task or {}).get("task_id"))
        return d

    @contextlib.contextmanager
    def with_idempotency(self, key: str) -> Iterator[str]:
        old, self._key = self._key, key
        try:
            yield key
        finally:
            self._key = old

    @contextlib.contextmanager
    def task(self, task_id: str, scopes: list[str], ttl: str | None = None) -> Iterator[dict]:
        """a short-lived Base credential with only these scopes for the calls inside; revoked at the end"""
        ttl = ttl or (self.config.get("targets.base.credentials") or {}).get("ttl", "15m")
        cred = self.base.mint(task_id, scopes, ttl)
        old, self._task = self._task, {**cred, "task_id": task_id}
        try:
            yield {k: v for k, v in cred.items() if k != "token"}
        finally:
            self._task = old
            with contextlib.suppress(JadeError):
                self.base.revoke(cred["id"])

    # ---- calls ----
    def owners(self, tool: str) -> list[str]:
        """which configured targets have a tool"""
        out = []
        if self.config.target("base"):
            try:
                if self.base.tool(tool):
                    out.append("base")
            except JadeError:
                pass
        if self.config.target("vault") and tool in VAULT_TOOLS:
            out.append("vault")
        if tool in KIT_TOOLS:
            out.append("kit")
        return out

    def route(self, tool: str, target: str | None = None) -> str:
        if target:
            return target
        pref = (self.config.get("playbooks") or {}).get("routes", {}).get(tool) if isinstance(self.config.get("playbooks"), dict) else None
        if pref:
            return pref
        o = self.owners(tool)
        if not o:
            raise JadeError(f"no configured target has a tool named {tool!r}", "JADE403")
        if len(o) > 1:
            raise JadeError(f"{tool!r} is a tool of {', '.join(o)}: name the target (or set playbooks.routes.{tool})", "JADE404")
        return o[0]

    def call(self, target: str | None, tool: str, args: dict | None = None, *, idempotency_key: str | None = None, timeout: float | None = None) -> Any:
        target = self.route(tool, target)
        args = args or {}
        task = (self._task or {}).get("task_id")
        if target == "base":
            meta = self.base.tool(tool)
            if meta is None:
                raise JadeError(f"Base has no tool {tool!r} that this token may use (jade base tools)", "JADE403")
            read = meta.get("scope") == "read"
            self.require(f"base.{meta.get('scope')}", base_target(tool, args), destructive=bool(meta.get("destructive")))
            key = None if read else (idempotency_key or self._key or uuid7())
            out = self.base.call(tool, args, idempotency_key=key, timeout=timeout)
            self.calls.append({"target": "base", "tool": tool, "idempotency_key": key, "task": task})
            return out
        if target == "vault":
            if tool not in VAULT_TOOLS:
                raise JadeError(f"Vault's HTTP API has no {tool!r}; it has {', '.join(VAULT_TOOLS)}", "JADE403")
            what = args.get("name") or args.get("session") or "*"
            self.require(f"vault.{tool}", str(what))
            self.calls.append({"target": "vault", "tool": tool, "task": task})
            if tool == "chat":
                return self.vault.chat(args["message"], session=args.get("session"), timeout=timeout)
            if tool == "flow":
                return self.vault.flow(args["name"], args.get("input"), timeout=timeout)
            return getattr(self.vault, tool)()
        if target == "kit":
            from .resources import kit
            if tool != "page":
                raise JadeError("Kit runs in a browser; the toolkit can only write a page for it (tool: page)", "JADE403")
            self.require("kit.page", str(args.get("out", "*")))
            return kit.page(**{k: v for k, v in args.items() if k in ("features", "ollama", "model", "title", "out")})
        if target == "local":
            return self.local(args.get("command") or tool)
        raise JadeError(f"unknown target {target!r}", "JADE400")

    def local(self, command: str) -> dict:
        import shlex
        import subprocess
        words = shlex.split(command)
        if not words:
            raise JadeError("an empty command", "JADE400")
        self.require("shell", words[0])
        self.calls.append({"target": "local", "tool": "shell", "command": words[0]})
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
        return {"code": p.returncode, "stdout": p.stdout[-20000:], "stderr": p.stderr[-5000:]}

    # ---- status ----
    def status(self) -> dict:
        """reach every configured target, check versions and auth → {"ok", "targets": {...}, "problems": [...]}"""
        out: dict[str, Any] = {"ok": True, "config": str(self.config.path or ""), "secrets": self.secrets.backend, "targets": {}, "problems": []}

        def bad(name: str, e: Exception | str, level: str = "error") -> None:
            msg = str(e)
            out["targets"].setdefault(name, {})["error" if level == "error" else "warning"] = msg
            if level == "error":
                out["ok"] = False
                out["problems"].append(f"{name}: {msg}")

        if self.config.path is None:
            bad("config", JadeError("no jade.config.yaml", "JADE100"))
        if self.config.target("base"):
            try:
                v = self.base.version()
                lvl, msg = compat.check("base", v)
                out["targets"]["base"] = {"url": self.base.url, "version": v, "compat": lvl}
                if lvl == "refuse":
                    bad("base", JadeError(msg, "JADE203"))
                elif lvl == "warn":
                    bad("base", msg, "warning")
                out["targets"]["base"]["tools"] = len(self.base.tools())
            except JadeError as e:
                bad("base", e)
        if self.config.target("vault"):
            try:
                h = self.vault.health()
                out["targets"]["vault"] = {"url": self.vault.url, "api": h.get("api"), "query_token": h.get("query_token", "unknown")}
                if h.get("api") not in (1, None):
                    bad("vault", JadeError(f"Vault API {h.get('api')}; this toolkit speaks API 1", "JADE203"))
                if self.vault.legacy_auth():
                    if self.accept_legacy:
                        bad("vault", "accepts ?token= in URLs (allowed by --accept-legacy)", "warning")
                    else:
                        bad("vault", JadeError("accepts tokens in URLs", "JADE102"))
                else:
                    self.vault.status()
            except JadeError as e:
                bad("vault", e)
        return out


VAULT_TOOLS = ("chat", "flow", "status", "flows", "chats", "history")
KIT_TOOLS = ("page",)
