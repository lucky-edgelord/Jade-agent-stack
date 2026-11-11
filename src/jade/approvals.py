"""Scoped approvals: what the toolkit may do, by capability and target pattern. Deny wins. Enforced in this process
before any call leaves it, whatever a server would allow.

    approvals:
      base.read: ["*"]                         # allow: patterns on the target
      base.write: ["record_*:bookings"]        # <tool>:<collection or name>
      base.schema: {allow: ["collection_create:*"], deny: ["collection_delete:*"]}
      vault.flow: ["Daily digest"]
      shell: {allow: [ls, cat, grep, find], deny: [rm, curl, wget]}
      http_request: {allow_hosts: [api.example.com], deny_hosts: ["*"]}

Capability keys may be patterns too ("base.*"). A call no rule covers needs a person to confirm (or --yolo).
Destructive calls need confirmation even when allowed, unless their rule says confirm: false.
Every decision that a person or --yolo made is appended to ~/.local/state/jade/approvals.log."""

from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .errors import SafetyError
from .redact import deep
from .secrets import state_dir


@dataclass
class Decision:
    allowed: bool | None  # True allowed, False denied, None: nobody said (ask)
    capability: str
    target: str
    rule: str = ""
    confirm: bool = False  # a person must still confirm (destructive)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "capability": self.capability, "target": self.target, "rule": self.rule, "confirm": self.confirm}


def _match(pats, value: str) -> str | None:
    for p in pats or []:
        if fnmatch.fnmatchcase(value, str(p)):
            return str(p)
    return None


@dataclass
class Approvals:
    rules: dict = field(default_factory=dict)
    log_path: Path | None = None

    def check(self, capability: str, target: str = "*", *, host: str | None = None, destructive: bool = False) -> Decision:
        allowed: bool | None = None
        why = ""
        confirm = destructive
        for key, rule in self.rules.items():
            if not fnmatch.fnmatchcase(capability, key):
                continue
            if isinstance(rule, list):
                rule = {"allow": rule}
            m = _match(rule.get("deny"), target) or (host and _match(rule.get("deny_hosts"), host))
            if m:
                return Decision(False, capability, target, f"{key}: deny {m}")
            m = _match(rule.get("allow"), target) or (host and _match(rule.get("allow_hosts"), host))
            if m and allowed is None:
                allowed, why = True, f"{key}: allow {m}"
                if rule.get("confirm") is False:
                    confirm = False
                elif rule.get("confirm") is True:
                    confirm = True
        return Decision(allowed, capability, target, why, confirm and allowed is not False)

    def record(self, d: Decision, *, how: str, task: str | None = None, scope: str | None = None) -> None:
        p = self.log_path or state_dir() / "approvals.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(deep({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "what": d.capability, "target": d.target,
                                     "how": how, "task": task, "scope": scope, "rule": d.rule})) + "\n")

    def enforce(self, d: Decision, *, ask: Callable[[str], bool] | None, yolo: bool = False, task: str | None = None) -> None:
        """raise unless allowed; a person (ask) or --yolo can allow what no rule covers, and confirm what is destructive"""
        if d.allowed is False:
            raise SafetyError(f"{d.capability} on {d.target} is denied ({d.rule})", "JADE301", data=d.to_dict())
        if d.allowed and not d.confirm:
            return
        q = f"{'Destructive: ' if d.confirm else ''}allow {d.capability} on {d.target}?"
        if yolo:
            self.record(d, how="yolo", task=task)
            return
        if ask is None:
            raise SafetyError(f"{d.capability} on {d.target} needs " + ("confirmation (destructive)" if d.confirm else "an approval in jade.config.yaml"),
                              "JADE302" if d.confirm else "JADE300", data=d.to_dict())
        if not ask(q):
            self.record(d, how="refused", task=task)
            raise SafetyError(f"{d.capability} on {d.target}: not confirmed", "JADE302", data=d.to_dict())
        self.record(d, how="interactive", task=task)


def base_target(tool: str, args: dict | None) -> str:
    """<tool>:<the thing it acts on> for a Base tool call"""
    a = args or {}
    obj = a.get("collection") or a.get("name") or a.get("path") or a.get("id") or ""
    return f"{tool}:{obj}" if obj else tool
