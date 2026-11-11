"""The playbook engine: load and validate, check against the targets' real tool lists, plan, run (resumable), approve."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets as _secrets
import time
from pathlib import Path
from typing import Any, Iterator

import yaml

from ..errors import JadeError, PlaybookError, SafetyError
from ..ids import uuid7
from ..redact import deep
from ..secrets import config_dir, state_dir
from . import template

API = "jade/v1"
TARGETS = ("vault", "base", "kit", "local")
FAIL_MODES = ("stop", "continue", "rollback")
STRATEGIES = ("key", "content-hash", "none")
VAULT_READS = ("status", "flows", "chats", "history")
TASK_KEYS = {"name", "target", "tool", "args", "command", "register", "retries", "delay", "until", "when", "undo",
             "idempotency_key", "fail_mode", "block", "rescue", "always", "timeout"}

# the JSON Schema committed as schema/playbook.v1.json (tests keep them in step)
_TASK_REF = {"$ref": "#/$defs/task"}
SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://lucky-edgelord.github.io/jade-agent-stack/schema/playbook.v1.json",
    "title": "Jade Agent Stack playbook (jade/v1)",
    "type": "object", "additionalProperties": False, "required": ["apiVersion", "kind", "metadata", "spec"],
    "properties": {
        "apiVersion": {"const": API}, "kind": {"const": "Playbook"},
        "metadata": {"type": "object", "additionalProperties": False, "properties": {
            "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]*$"}, "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}}}},
        "spec": {"type": "object", "additionalProperties": False, "required": ["tasks"], "properties": {
            "targets": {"type": "array", "items": {"enum": list(TARGETS)}, "uniqueItems": True},
            "timeout": {"type": ["string", "number"], "description": "the whole run, e.g. 120s, 5m"},
            "vars": {"type": "object"},
            "scopes": {"type": "array", "items": {"enum": ["read", "write", "schema", "hooks", "site", "settings", "gateway", "billing"]},
                       "description": "Base scopes for the run's short-lived task credential"},
            "schedule": {"type": "string", "description": "when Vault should run it, e.g. \"every weekday at 9am\" (Vault only)"},
            "defaults": {"type": "object", "additionalProperties": False, "properties": {
                "fail_mode": {"enum": list(FAIL_MODES)}, "idempotent_strategy": {"enum": list(STRATEGIES)}}},
            "tasks": {"type": "array", "minItems": 1, "items": _TASK_REF}}}},
    "$defs": {"task": {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string"}, "target": {"enum": list(TARGETS)}, "tool": {"type": "string"}, "args": {"type": "object"},
        "command": {"type": "string", "description": "local target: a shell command (approvals.shell)"},
        "register": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
        "retries": {"type": "integer", "minimum": 0, "maximum": 10}, "delay": {"type": "number", "minimum": 0},
        "until": {"type": "string"}, "when": {"type": "string"}, "timeout": {"type": ["string", "number"]},
        "undo": {"type": "object", "additionalProperties": False, "properties": {"target": {"enum": list(TARGETS)}, "tool": {"type": "string"}, "args": {"type": "object"}, "command": {"type": "string"}}},
        "idempotency_key": {"type": "string"}, "fail_mode": {"enum": list(FAIL_MODES)},
        "block": {"type": "array", "items": _TASK_REF}, "rescue": {"type": "array", "items": _TASK_REF}, "always": {"type": "array", "items": _TASK_REF}}}},
}


def seconds(v: Any, default: float) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*", str(v))
    if not m:
        raise PlaybookError(f"a duration like 30s, 5m or 1h, not {v!r}")
    return float(m.group(1)) * {"ms": 0.001, "s": 1, None: 1, "m": 60, "h": 3600}[m.group(2)]


def _sha(*parts: Any) -> str:
    return hashlib.sha256("|".join(json.dumps(p, sort_keys=True, default=str) for p in parts).encode()).hexdigest()


class Playbook:
    def __init__(self, data: dict, path: Path | None = None, text: str | None = None):
        self.data, self.path = data, path
        self.text = text if text is not None else yaml.safe_dump(data, sort_keys=False)
        self.validate()
        md = data.get("metadata") or {}
        self.name: str = md.get("name") or (path.name.removesuffix(".playbook.yaml").removesuffix(".yaml") if path else "playbook")
        self.spec: dict = data["spec"]
        self.vars: dict = dict(self.spec.get("vars") or {})
        self.defaults: dict = {"fail_mode": "stop", "idempotent_strategy": "key", **(self.spec.get("defaults") or {})}

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    # ---------- structure ----------
    def validate(self) -> None:
        d = self.data
        if not isinstance(d, dict):
            raise PlaybookError("a playbook is a mapping")
        _keys(d, SCHEMA["properties"], "")
        for k in SCHEMA["required"]:
            if k not in d:
                raise PlaybookError(f"missing {k}")
        if d["apiVersion"] != API:
            raise PlaybookError(f"apiVersion must be {API}")
        if d["kind"] != "Playbook":
            raise PlaybookError("kind must be Playbook")
        _keys(d.get("metadata") or {}, SCHEMA["properties"]["metadata"]["properties"], "metadata")
        name = (d.get("metadata") or {}).get("name")
        if name is not None and not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(name)):
            raise PlaybookError("metadata.name: lower-case letters, digits, . _ -")
        spec = d["spec"]
        if not isinstance(spec, dict):
            raise PlaybookError("spec must be a mapping")
        sp = SCHEMA["properties"]["spec"]["properties"]
        _keys(spec, sp, "spec")
        for t in spec.get("targets") or []:
            if t not in TARGETS:
                raise PlaybookError(f"spec.targets: unknown target {t!r} (targets: {', '.join(TARGETS)})")
        for k, allowed in (("fail_mode", FAIL_MODES), ("idempotent_strategy", STRATEGIES)):
            v = (spec.get("defaults") or {}).get(k)
            if v is not None and v not in allowed:
                raise PlaybookError(f"spec.defaults.{k}: one of {', '.join(allowed)}")
        _keys(spec.get("defaults") or {}, sp["defaults"]["properties"], "spec.defaults")
        for s in spec.get("scopes") or []:
            if s not in sp["scopes"]["items"]["enum"]:
                raise PlaybookError(f"spec.scopes: unknown scope {s!r}")
        if spec.get("timeout") is not None:
            seconds(spec["timeout"], 0)
        if not isinstance(spec.get("tasks"), list) or not spec["tasks"]:
            raise PlaybookError("spec.tasks: a list of at least one task")
        if spec.get("schedule") and "vault" not in (spec.get("targets") or []):
            raise PlaybookError("spec.schedule needs the vault target: Base has no scheduler (by design); Vault runs schedules")
        for path, t in self.walk():
            self._task(path, t)

    def _task(self, path: str, t: Any) -> None:
        if not isinstance(t, dict):
            raise PlaybookError(f"{path}: a task is a mapping")
        bad = set(t) - TASK_KEYS
        if bad:
            raise PlaybookError(f"{path}: unknown key(s) {', '.join(sorted(bad))} (keys: {', '.join(sorted(TASK_KEYS))})")
        kinds = [k for k in ("tool", "command", "block") if k in t]
        if len(kinds) != 1:
            raise PlaybookError(f"{path}: a task has exactly one of tool, command or block")
        if ("rescue" in t or "always" in t) and "block" not in t:
            raise PlaybookError(f"{path}: rescue and always go with a block")
        if "command" in t and t.get("target", "local") != "local":
            raise PlaybookError(f"{path}: command runs on the local target")
        if t.get("target") is not None and t["target"] not in TARGETS:
            raise PlaybookError(f"{path}.target: one of {', '.join(TARGETS)}")
        if t.get("target") and self.data["spec"].get("targets") and t["target"] not in self.data["spec"]["targets"]:
            raise PlaybookError(f"{path}.target: {t['target']} is not in spec.targets")
        if "args" in t and not isinstance(t["args"], dict):
            raise PlaybookError(f"{path}.args must be a mapping")
        if t.get("fail_mode") is not None and t["fail_mode"] not in FAIL_MODES:
            raise PlaybookError(f"{path}.fail_mode: one of {', '.join(FAIL_MODES)}")
        if "register" in t and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(t["register"])):
            raise PlaybookError(f"{path}.register: a name like created")
        if "retries" in t and not (isinstance(t["retries"], int) and 0 <= t["retries"] <= 10):
            raise PlaybookError(f"{path}.retries: 0 to 10")
        if "undo" in t:
            if not isinstance(t["undo"], dict) or set(t["undo"]) - {"target", "tool", "args", "command"} or not ({"tool", "command"} & set(t["undo"])):
                raise PlaybookError(f"{path}.undo: {{tool, args, target}} or {{command}}")
        for k in ("when", "until"):
            if k in t:
                if not isinstance(t[k], str):
                    raise PlaybookError(f"{path}.{k} must be an expression string")
                src = t[k].strip()
                src = template.EXPR.fullmatch(src).group(1) if template.EXPR.fullmatch(src) else src
                template.tokens(src)
        for k in ("block", "rescue", "always"):
            if k in t and (not isinstance(t[k], list) or not t[k]):
                raise PlaybookError(f"{path}.{k}: a list of tasks")

    def walk(self, tasks: list | None = None, prefix: str = "tasks") -> Iterator[tuple[str, dict]]:
        for i, t in enumerate(tasks if tasks is not None else self.data["spec"]["tasks"]):
            p = f"{prefix}[{i}]"
            yield p, t
            if isinstance(t, dict):
                for k in ("block", "rescue", "always"):
                    if isinstance(t.get(k), list):
                        yield from self.walk(t[k], f"{p}.{k}")

    def targets(self) -> list[str]:
        return list(self.data["spec"].get("targets") or TARGETS)

    def target_of(self, t: dict, harness: Any = None) -> str:
        if "command" in t:
            return "local"
        if t.get("target"):
            return t["target"]
        allowed = self.targets()
        owners = [x for x in (harness.owners(t["tool"]) if harness else _static_owners(t["tool"])) if x in allowed]
        if not owners:
            raise PlaybookError(f"no allowed target ({', '.join(allowed)}) has a tool named {t['tool']!r}", "JADE403")
        if len(owners) > 1:
            raise PlaybookError(f"{t['tool']!r} is a tool of {', '.join(owners)}: set target", "JADE404")
        return owners[0]

    def mutating(self, t: dict, target: str, registry: dict | None) -> bool:
        if target == "base":
            meta = (registry or {}).get(t["tool"])
            if meta is None and registry is None:  # offline: the read tools this toolkit knows
                return not _base_read_name(t["tool"])
            return not (meta and meta.get("scope") == "read")
        if target == "vault":
            return t["tool"] not in VAULT_READS
        return True

    # ---------- check ----------
    def check(self, harness: Any = None, *, registry: dict | None = None) -> dict:
        """schema, expressions, targets, tools and arguments (against the target's real tool list when it can be read)"""
        problems: list[str] = []
        registry = registry if registry is not None else _registry(harness)
        known = set(self.vars) | {"vars", "run", "item"}
        for path, t in self.walk():
            if "register" in t:
                known.add(t["register"])
        for path, t in self.walk():
            if "block" in t:
                continue
            for k in ("args", "when", "until", "command", "idempotency_key"):
                for n in template.names(t.get(k) if k != "when" and k != "until" else _wrap(t.get(k))):
                    if n not in known:
                        problems.append(f"{path}.{k}: {{{{ {n} }}}} is not a var or a registered result")
            try:
                target = self.target_of(t, harness)
            except JadeError as e:
                problems.append(f"{path}: {e.message}")
                continue
            if target == "base" and registry is not None:
                meta = registry.get(t["tool"])
                if meta is None:
                    problems.append(f"{path}: Base has no tool {t['tool']!r} for this token")
                else:
                    problems += [f"{path}.args: {p}" for p in _check_args(meta.get("parameters") or {}, t.get("args") or {})]
            if target == "vault" and t["tool"] not in ("chat", "flow", *VAULT_READS):
                problems.append(f"{path}: Vault's HTTP API has no {t['tool']!r} (it has chat, flow, {', '.join(VAULT_READS)}); "
                                "Vault-only tools such as ui_render or notify run inside a Vault flow: call the flow")
            if target == "kit" and t["tool"] != "page":
                problems.append(f"{path}: Kit runs in a browser; the toolkit can only write its page (tool: page)")
            fm = t.get("fail_mode") or self.defaults["fail_mode"]
            if fm == "rollback" and self.mutating(t, target, registry) and "undo" not in t:
                problems.append(f"{path}: fail_mode rollback needs an undo for every mutating task")
        if problems:
            raise PlaybookError("; ".join(problems), data={"problems": problems})
        return {"ok": True, "name": self.name, "hash": self.hash, "tasks": sum(1 for _ in self.walk()), "checked_tools": registry is not None}

    # ---------- plan ----------
    def plan(self, variables: dict | None = None, *, registry: dict | None = None) -> dict:
        """every call the run would make, with rendered arguments and idempotency keys; makes no calls"""
        v = {**self.vars, **(variables or {})}
        ctx = {**v, "vars": v, "run": {"id": "<run id>"}}
        for _, t in self.walk():
            if "register" in t:
                ctx[t["register"]] = template.Unknown(t["register"])
        calls = []
        for path, t in self.walk():
            if "block" in t:
                continue
            target = self.target_of(t)
            args = template.render(copy.deepcopy(t.get("args") or {}), ctx)
            calls.append(_jsonable({"task": t.get("name") or path, "path": path, "target": target, "tool": t.get("tool") or "shell",
                                    **({"command": template.render(t["command"], ctx)} if "command" in t else {"args": args}),
                                    "idempotency_key": self.key(path, t, v, args) if self.mutating(t, target, registry) else None,
                                    "when": t.get("when"), "section": "rescue" if ".rescue[" in path else "always" if ".always[" in path else "main"}))
        out = _jsonable({"playbook": self.name, "hash": self.hash, "vars": {k: x for k, x in v.items() if k != "secrets"}, "calls": calls})
        if self.spec.get("schedule"):
            out["schedule"] = {"target": "vault", "when": self.spec["schedule"], "vault": f"Schedule tab → New → '{self.spec['schedule']}' → run playbook {self.name}"}
        return out

    def key(self, path: str, t: dict, variables: dict, args: Any) -> str:
        if t.get("idempotency_key"):
            return str(template.render(t["idempotency_key"], {**variables, "vars": variables}))
        strat = self.defaults["idempotent_strategy"]
        if strat == "content-hash":
            return _sha(self.name, path, _jsonable(args))[:40]
        if strat == "none":
            return uuid7()
        return _sha(self.name, path, _sha(_public(variables)))[:40]

    # ---------- run ----------
    def run(self, harness: Any, variables: dict | None = None, *, resume: bool = True, unattended: bool | None = None) -> Iterator[dict]:
        """run, yielding step events. A run with the same vars resumes: tasks that finished are not run again."""
        v = {**self.vars, **(variables or {})}
        unattended = harness.ask is None if unattended is None else unattended
        registry = _registry(harness)
        self.check(harness, registry=registry)
        if any(self.mutating(t, self.target_of(t, harness), registry) for _, t in self.walk() if "block" not in t):
            if not approved(self):
                if unattended or harness.ask is None:
                    raise SafetyError(f"playbook {self.name} changes things and is not approved (or changed since)", "JADE303")
                if not harness.ask(f"Run playbook {self.name}? It is not approved (jade playbook approve {self.name})."):
                    raise SafetyError(f"playbook {self.name}: not confirmed", "JADE303")
        state = RunState.open(self, v, fresh=not resume)
        yield {"event": "start", "playbook": self.name, "run": state.id, "resumed": state.resumed, "vars": deep(_public(v))}
        deadline = time.monotonic() + seconds(self.spec.get("timeout"), 3600)
        ctx = {**v, "vars": v, "run": {"id": state.id}}
        for name, rec in state.data["tasks"].items():  # registered results of finished tasks
            if rec.get("register") and rec.get("status") == "completed":
                ctx[rec["register"]] = rec["result"]
        done: list[tuple[str, dict, Any]] = []
        state.set_status("in_progress")
        scopes = self.spec.get("scopes")
        use_cred = bool(scopes) and harness.config.target("base") and (harness.config.get("targets.base.credentials") or {}).get("enabled", True)
        try:
            if use_cred:
                with harness.task(f"playbook:{self.name}:{state.id}", scopes) as cred:
                    yield {"event": "credential", "task_id": cred.get("task_id"), "scopes": cred.get("scopes"), "expires": cred.get("expires")}
                    ok = yield from self._tasks(harness, self.spec["tasks"], "tasks", ctx, v, state, registry, done, deadline)
            else:
                ok = yield from self._tasks(harness, self.spec["tasks"], "tasks", ctx, v, state, registry, done, deadline)
        except KeyboardInterrupt:
            state.set_status("interrupted")
            yield {"event": "interrupted", "run": state.id}
            raise
        except SafetyError as e:
            state.set_status("refused")
            yield {"event": "refused", "error": e.to_dict()}
            raise
        except JadeError as e:
            if e.code == "JADE103":
                state.set_status("refused")
                yield {"event": "refused", "error": e.to_dict()}
            raise
        state.set_status("completed" if ok else "failed")
        yield {"event": "done", "ok": ok, "run": state.id, "status": state.data["status"], "calls": len(done)}

    def _tasks(self, h: Any, tasks: list, prefix: str, ctx: dict, v: dict, state: "RunState", registry: dict | None,
               done: list, deadline: float) -> Iterator[dict]:
        ok_all = True
        for i, t in enumerate(tasks):
            path = f"{prefix}[{i}]"
            label = t.get("name") or path
            if time.monotonic() > deadline:
                raise JadeError(f"playbook {self.name} ran past its timeout", "JADE204")
            if "when" in t:
                if not _truthy(template.render(_wrap(t["when"]), ctx)):
                    yield {"event": "skip", "task": label, "why": "when is false"}
                    continue
            if "block" in t:
                ok = yield from self._tasks(h, t["block"], path + ".block", ctx, v, state, registry, done, deadline)
                if not ok and "rescue" in t:
                    yield {"event": "rescue", "task": label}
                    ok = yield from self._tasks(h, t["rescue"], path + ".rescue", ctx, v, state, registry, done, deadline)
                if "always" in t:
                    yield from self._tasks(h, t["always"], path + ".always", ctx, v, state, registry, done, deadline)
                if not ok:
                    ok_all = False
                    if (t.get("fail_mode") or self.defaults["fail_mode"]) != "continue":
                        return False
                continue
            prev = state.data["tasks"].get(path)
            if prev and prev.get("status") == "completed":
                if t.get("register"):
                    ctx[t["register"]] = prev["result"]
                yield {"event": "skip", "task": label, "why": "finished in an earlier attempt of this run"}
                continue
            target = self.target_of(t, h)
            args = template.render(copy.deepcopy(t.get("args") or {}), ctx)
            mut = self.mutating(t, target, registry)
            key = self.key(path, t, v, args) if mut else None
            state.task(path, status="in_progress", key=key, register=t.get("register"))
            yield {"event": "task", "task": label, "target": target, "tool": t.get("tool") or "shell", "idempotency_key": key}
            res = self._call(h, t, target, args, key, ctx)
            tries = int(t.get("retries", 0))
            while tries > 0 and (not res["ok"] or ("until" in t and not _truthy(template.render(_wrap(t["until"]), {**ctx, **({t["register"]: res} if t.get("register") else {}), "result": res})))):
                tries -= 1
                time.sleep(float(t.get("delay", 1)))
                yield {"event": "retry", "task": label, "left": tries}
                res = self._call(h, t, target, args, key, ctx)
            if t.get("register"):
                ctx[t["register"]] = res
            state.task(path, status="completed" if res["ok"] else "failed", result=res)
            if res["ok"]:
                done.append((path, t, res))
                yield {"event": "ok", "task": label, "changed": res["changed"], "result": deep(res["result"])}
                continue
            fm = t.get("fail_mode") or self.defaults["fail_mode"]
            yield {"event": "error", "task": label, "error": res["error"], "fail_mode": fm}
            if fm == "continue":  # expected to fail sometimes (e.g. "is it there?"): the run goes on and stays ok
                continue
            ok_all = False
            if fm == "rollback":
                for p2, t2, r2 in reversed(done):
                    if "undo" in t2:
                        u = t2["undo"]
                        uargs = template.render(copy.deepcopy(u.get("args") or {}), ctx)
                        ut = "local" if "command" in u else (u.get("target") or self.target_of(t2, h))
                        ur = self._call(h, {**u, "name": f"undo {p2}"}, ut, uargs, self.key(p2 + ".undo", u, v, uargs), ctx)
                        state.task(p2, status="rolled_back")
                        yield {"event": "rollback", "task": t2.get("name") or p2, "ok": ur["ok"], "error": ur["error"]}
            return False
        return ok_all

    def _call(self, h: Any, t: dict, target: str, args: dict, key: str | None, ctx: dict) -> dict:
        try:
            if "command" in t:
                out = h.local(str(template.render(t["command"], ctx)))
                ok = out["code"] == 0
                return {"ok": ok, "changed": True, "result": out, "error": None if ok else (out["stderr"] or f"exit {out['code']}")[-500:]}
            out = h.call(target, t["tool"], args, idempotency_key=key, timeout=seconds(t.get("timeout"), 0) or None)
            changed = target != "vault" or t["tool"] not in VAULT_READS
            if target == "base":
                changed = not h.base.is_read(t["tool"])
            return {"ok": True, "changed": changed, "result": out, "error": None}
        except SafetyError:
            raise
        except JadeError as e:
            if e.code in ("JADE103", "JADE102", "JADE101"):
                raise  # stop: a refused credential is not retried
            return {"ok": False, "changed": False, "result": None, "error": str(e.message)}


# ---------- runs (resumable state) ----------
class RunState:
    def __init__(self, path: Path, data: dict, resumed: bool):
        self.path, self.data, self.resumed = path, data, resumed

    @property
    def id(self) -> str:
        return self.data["id"]

    @classmethod
    def open(cls, pb: Playbook, variables: dict, *, fresh: bool = False) -> "RunState":
        d = state_dir() / "runs"
        d.mkdir(parents=True, exist_ok=True)
        vh = _sha(_public(variables))[:12]
        p = d / f"{pb.name}-{vh}.json"
        if p.exists() and not fresh:
            data = json.loads(p.read_text())
            if data.get("hash") == pb.hash and data.get("status") in ("in_progress", "interrupted", "failed", "refused", "resumable"):
                data["status"] = "resumable"
                return cls(p, data, True)
        data = {"id": uuid7(), "playbook": pb.name, "hash": pb.hash, "vars_hash": vh, "status": "not_started", "started": _now(), "tasks": {}}
        s = cls(p, data, False)
        s.save()
        return s

    def task(self, path: str, **kw: Any) -> None:
        self.data["tasks"].setdefault(path, {}).update(_jsonable(deep(kw)) if "result" in kw else kw)
        self.save()

    def set_status(self, s: str) -> None:
        self.data["status"] = s
        self.data["updated"] = _now()
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, default=str))
        os.replace(tmp, self.path)


def runs(name: str | None = None) -> list[dict]:
    d = state_dir() / "runs"
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            j = json.loads(p.read_text())
        except ValueError:
            continue
        if name is None or j.get("playbook") == name:
            out.append({k: j.get(k) for k in ("id", "playbook", "status", "started", "updated")} | {"tasks": {k: v.get("status") for k, v in j.get("tasks", {}).items()}})
    return out


# ---------- approval (hash-bound) ----------
def _key() -> bytes:
    p = config_dir() / "approval.key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(_secrets.token_hex(32))
    return p.read_text().strip().encode()


def _approvals_file() -> Path:
    return state_dir() / "playbook-approvals.json"


def _read_approvals() -> dict:
    try:
        return json.loads(_approvals_file().read_text())
    except (OSError, ValueError):
        return {}


def _sig(name: str, h: str) -> str:
    return hmac.new(_key(), f"{name}|{h}".encode(), hashlib.sha256).hexdigest()


def approve(pb: Playbook) -> dict:
    a = _read_approvals()
    a[pb.name] = {"hash": pb.hash, "path": str(pb.path or ""), "approved": _now(), "sig": _sig(pb.name, pb.hash)}
    _approvals_file().parent.mkdir(parents=True, exist_ok=True)
    _approvals_file().write_text(json.dumps(a, indent=1))
    from ..approvals import Approvals, Decision
    Approvals().record(Decision(True, "playbook.approve", pb.name), how="interactive", scope=pb.hash[:16])
    return {"approved": pb.name, "hash": pb.hash}


def revoke(name: str) -> bool:
    a = _read_approvals()
    if name not in a:
        return False
    del a[name]
    _approvals_file().write_text(json.dumps(a, indent=1))
    return True


def approved(pb: Playbook) -> bool:
    a = _read_approvals().get(pb.name)
    return bool(a and a.get("hash") == pb.hash and hmac.compare_digest(a.get("sig", ""), _sig(pb.name, pb.hash)))


# ---------- loading ----------
def load(path: str | os.PathLike) -> Playbook:
    p = Path(path)
    if not p.exists():
        found = discover().get(str(path))
        if not found:
            raise PlaybookError(f"no playbook {path!r} (jade playbook list)", "JADE405")
        p = found
    text = p.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PlaybookError(f"{p}: not valid YAML: {e}") from None
    try:
        return Playbook(data, p, text)
    except PlaybookError as e:
        raise PlaybookError(f"{p}: {e.message}", data=e.data) from None


def discover(root: str | os.PathLike | None = None) -> dict[str, Path]:
    """playbooks by name: *.playbook.yaml in ./, ./playbooks and ./examples (and the config's playbooks.dirs)"""
    base = Path(root or os.getcwd())
    out: dict[str, Path] = {}
    for d in (base, base / "playbooks", base / "examples"):
        for p in sorted(d.glob("*.playbook.yaml")) if d.is_dir() else []:
            try:
                name = (yaml.safe_load(p.read_text()) or {}).get("metadata", {}).get("name") or p.name.removesuffix(".playbook.yaml")
            except Exception:
                name = p.name.removesuffix(".playbook.yaml")
            out.setdefault(name, p)
    return out


# ---------- helpers ----------
def _keys(d: dict, allowed: dict, where: str) -> None:
    bad = set(d) - set(allowed)
    if bad:
        raise PlaybookError(f"{where or 'top level'}: unknown key(s) {', '.join(sorted(bad))} (allowed: {', '.join(sorted(allowed))})")


def _wrap(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    return s if "{{" in s else "{{ " + s + " }}"


def _truthy(v: Any) -> bool:
    return bool(v) and not isinstance(v, template.Unknown)


def _public(v: dict) -> dict:
    """vars without secrets (they never shape keys, hashes or logs)"""
    return {k: x for k, x in v.items() if k != "secrets"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jsonable(v: Any) -> Any:
    return json.loads(json.dumps(v, default=lambda x: f"<{x.text}>" if isinstance(x, template.Unknown) else str(x)))


def _static_owners(tool: str) -> list[str]:
    from ..harness import KIT_TOOLS, VAULT_TOOLS
    o = []
    if tool in VAULT_TOOLS:
        o.append("vault")
    if tool in KIT_TOOLS:
        o.append("kit")
    if not o:
        o.append("base")  # without a connection, unknown tools are taken to be Base's (check verifies)
    return o


def _base_read_name(tool: str) -> bool:
    return tool in ("server_info", "auth_providers", "audit_list", "logs_list") or tool.endswith(("_list", "_get", "_info", "_read", "_usage"))


def _registry(harness: Any) -> dict | None:
    if harness is None or not harness.config.target("base"):
        return None
    try:
        return {t["name"]: t for t in harness.base.tools()}
    except JadeError:
        return None


def _check_args(schema: dict, args: dict) -> list[str]:
    """required arguments, unknown arguments and simple types (expressions are checked when they run)"""
    props = schema.get("properties") or {}
    out = [f"needs {r!r}" for r in schema.get("required") or [] if r not in args]
    types = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}
    for k, v in args.items():
        if k not in props:
            out.append(f"unknown argument {k!r} (arguments: {', '.join(sorted(props))})")
            continue
        ty = props[k].get("type")
        if (isinstance(v, str) and "{{" in v) or v is None:
            continue
        if isinstance(ty, str) and ty in types and not isinstance(v, types[ty]):
            out.append(f"{k!r} should be {ty}")
    return out
