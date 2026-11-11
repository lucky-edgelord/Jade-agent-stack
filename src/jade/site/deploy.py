"""Deploying a site is a playbook: the site spec becomes Base tool calls (settings, modules, rate limits, sign-in
providers, collections, providers, models, plans, billing, then the files), run through the harness with approvals,
idempotency keys and a short-lived task credential. `jade site plan` shows every call without making one.

Secrets come only from environment variables the spec names (api_key_env, secret_key_env, client_secret_env); they are
sent write-only and never printed."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from ..errors import SiteError
from ..playbook import template
from ..playbook.engine import Playbook
from ..redact import register
from . import sections
from .spec import RULES, fields

TYPE = {"textarea": "text", "checkbox": "bool", "editor": "editor"}


def _field(f: dict) -> dict:
    out = {"name": f["name"], "type": TYPE.get(f["type"], f["type"])}
    if f.get("required"):
        out["required"] = True
    if out["type"] == "file":
        out["maxSelect"] = 1
    return out


def _rule(v: Any) -> Any:
    if v is None:
        return None
    return RULES.get(v, v) if isinstance(v, str) else v


def env_names(s: dict) -> list[str]:
    b = s.get("backend") or {}
    names = [p["api_key_env"] for p in b.get("providers") or [] if p.get("api_key_env")]
    bl = b.get("billing") or {}
    names += [bl[k] for k in ("secret_key_env", "webhook_secret_env") if bl.get(k)]
    for p in (b.get("auth") or {}).get("providers") or []:
        names += [p[k] for k in ("client_id_env", "client_secret_env") if p.get(k)]
    return names


def secrets_from_env(s: dict) -> dict:
    out, missing = {}, []
    for n in env_names(s):
        v = os.environ.get(n)
        if not v:
            missing.append(n)
        else:
            register(v)
            out[n] = v
    if missing:
        raise SiteError(f"set these environment variables before deploying: {', '.join(missing)}", "JADE105")
    return out


def playbook(s: dict, files: dict[str, str], *, static_dir: Path | None = None, name: str | None = None) -> Playbook:
    """the deploy playbook for an expanded spec and its compiled files"""
    if s.get("demo"):
        raise SiteError("this is a demo site (demo: true): its backend is pretend, in the browser. Remove demo: true to deploy it to a Jade Agent Base")
    b = s.get("backend") or {}
    tasks: list[dict] = []
    scopes = {"read", "site"}
    if s.get("url"):
        scopes.add("settings")
        tasks.append({"name": "Public URL", "tool": "settings_update", "args": {"set": {"meta": {"appURL": s["url"].rstrip("/"), "appName": s["name"]}}}})
    for m in b.get("modules") or []:
        scopes.add("settings")
        scopes.add(m)
        tasks.append({"name": f"Module {m}", "tool": "module_enable", "args": {"name": m}})
    rl = b.get("rate_limits")
    if rl:
        scopes.add("settings")
        args = {"enabled": True, "defaults": True} if rl is True else {"enabled": True, **({"rules": rl["rules"]} if isinstance(rl, dict) and rl.get("rules") else {"defaults": True})}
        tasks.append({"name": "Rate limits", "tool": "rate_limits", "args": args})
    auth = b.get("auth") or {}
    for p in auth.get("providers") or []:
        scopes.add("settings")
        a = {"name": p["name"], **({"display_name": p["display_name"]} if p.get("display_name") else {})}
        a["client_id"] = "{{ secrets." + p["client_id_env"] + " }}" if p.get("client_id_env") else p.get("client_id", "")
        if p.get("client_secret_env"):
            a["client_secret"] = "{{ secrets." + p["client_secret_env"] + " }}"
        for k in ("auth_url", "token_url", "user_info_url"):
            if p.get(k):
                a[k] = p[k]
        if "password" in auth:
            a["password"] = bool(auth["password"])
        tasks.append({"name": f"Sign in with {p['name']}", "tool": "auth_provider_set", "args": a})
    for c in b.get("collections") or []:
        scopes.add("schema")
        fs = [_field(f) for f in fields(c)]
        if "owner" in [c.get(r) for r in ("list", "view", "create", "update", "delete")] and not any(f["name"] == "user" for f in fs):
            fs.append({"name": "user", "type": "relation", "collectionId": "users", "maxSelect": 1})
        rules = {f"{r}Rule": _rule(c.get(r)) for r in ("list", "view", "create", "update", "delete") if c.get(r) is not None}
        reg = f"col_{c['name']}"
        tasks.append({"name": f"Is {c['name']} there", "tool": "collection_get", "args": {"name": c["name"]}, "register": reg, "fail_mode": "continue"})
        tasks.append({"name": f"Create {c['name']}", "tool": "collection_create", "args": {"name": c["name"], "fields": fs, **{k: v for k, v in rules.items() if v is not None}}, "when": f"not {reg}.ok"})
        if rules:
            tasks.append({"name": f"Rules of {c['name']}", "tool": "collection_update", "args": {"name": c["name"], "set": rules}, "when": f"{reg}.ok"})
    for p in b.get("providers") or []:
        a = {k: p[k] for k in ("name", "type", "base_url", "timeout", "enabled") if k in p}
        if p.get("api_key_env"):
            a["api_key"] = "{{ secrets." + p["api_key_env"] + " }}"
        tasks.append({"name": f"Provider {p['name']}", "tool": "provider_set", "args": a})
    for m in b.get("models") or []:
        tasks.append({"name": f"Model {m['name']}", "tool": "model_set", "args": {k: m[k] for k in ("name", "provider", "upstream", "kind", "price_in", "price_out", "price_call", "enabled", "description", "context") if k in m}})
    for p in b.get("plans") or []:
        tasks.append({"name": f"Plan {p['name']}", "tool": "plan_set", "args": {k: p[k] for k in ("name", "description", "price_month", "monthly_tokens", "monthly_budget", "rpm", "default", "active") if k in p}})
    bl = b.get("billing") or {}
    if bl:
        a = {"currency": bl.get("currency", "usd")}
        if bl.get("secret_key_env"):
            a["secret_key"] = "{{ secrets." + bl["secret_key_env"] + " }}"
        if bl.get("webhook_secret_env"):
            a["webhook_secret"] = "{{ secrets." + bl["webhook_secret_env"] + " }}"
        for k in ("success_url", "cancel_url", "return_url"):
            if bl.get(k):
                a[k] = bl[k]
        tasks.append({"name": "Stripe", "tool": "billing_setup", "args": a})
        for p in bl.get("publish") or []:
            tasks.append({"name": f"Sell {p}", "tool": "plan_publish", "args": {"plan": p}})
    for rel in sorted(files):
        tasks.append({"name": f"Write {rel}", "tool": "site_write", "args": {"path": rel, "content": template.raw(files[rel])}})
    if static_dir and static_dir.is_dir():
        for f in sorted(static_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(static_dir).as_posix()
                data = f.read_bytes()
                try:
                    a = {"path": rel, "content": template.raw(data.decode("utf-8"))}
                except UnicodeDecodeError:
                    a = {"path": rel, "base64": base64.b64encode(data).decode()}
                tasks.append({"name": f"Write {rel}", "tool": "site_write", "args": a})
    for t in tasks:
        t.setdefault("target", "base")
    spec = {"targets": ["base"], "scopes": sorted(scopes & {"read", "write", "schema", "hooks", "site", "settings", "gateway", "billing"}),
            "defaults": {"fail_mode": "stop", "idempotent_strategy": "content-hash"}, "tasks": tasks or [{"tool": "server_info"}],
            "vars": {"secrets": {}}}
    nm = name or "deploy-" + (sections.re.sub(r"[^a-z0-9]+", "-", s["name"].lower()).strip("-") or "site")
    return Playbook({"apiVersion": "jade/v1", "kind": "Playbook", "metadata": {"name": nm, "description": f"Deploy {s['name']} to Jade Agent Base"}, "spec": spec})
