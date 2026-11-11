"""jade.config.yaml: found by walking up from the working directory (or JADE_CONFIG). It holds targets, models and
approvals; never secrets (those live in the OS keyring, see jade.secrets).

    version: 1
    targets:
      base:  {url: https://api.example.com, token: jade.api.example.com, credentials: {ttl: 15m}}
      vault: {url: http://127.0.0.1:8787, token: jade.127.0.0.1}
      kit:   {ollama: https://ollama.com, model: gpt-oss:120b}
    models: {provider: ollama, url: http://127.0.0.1:11434, fast: llama3.2:3b, strong: gpt-oss:120b}
    approvals:
      base.read: ["*"]
      base.write: ["record_*:bookings"]
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .errors import ConfigError, JadeError

NAME = "jade.config.yaml"
TARGETS = ("base", "vault", "kit", "local")
KNOWN = {"version", "targets", "models", "approvals", "defaults", "secrets", "playbooks", "site"}
TARGET_KEYS = {
    "base": {"url", "token", "credentials", "timeout"},
    "vault": {"url", "token", "timeout", "accept_legacy"},
    "kit": {"ollama", "model", "features", "cdn"},
    "local": {"shell"},
}
DEFAULTS: dict[str, Any] = {"version": 1, "targets": {}, "models": {}, "approvals": {}, "defaults": {"timeout": 30, "chat_timeout": 300}, "secrets": {"file": False}}


def find(start: str | os.PathLike | None = None) -> Path | None:
    """JADE_CONFIG, else the nearest jade.config.yaml from start (default: the working directory) upward"""
    env = os.environ.get("JADE_CONFIG")
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise ConfigError(f"JADE_CONFIG points to {p}, which does not exist", "JADE100")
        return p
    d = Path(start or os.getcwd()).resolve()
    for p in (d, *d.parents):
        if (p / NAME).is_file():
            return p / NAME
    return None


def secret_name(url: str) -> str:
    """the keyring name for a target's token: jade.<host>"""
    host = urlparse(url).hostname or url
    return f"jade.{host}"


class Config:
    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.path = path
        self.data = merge(copy.deepcopy(DEFAULTS), data or {})
        validate(self.data)

    @classmethod
    def load(cls, path: str | os.PathLike | None = None, *, required: bool = False) -> "Config":
        p = Path(path) if path else find()
        if p is None:
            if required:
                raise ConfigError(f"no {NAME} here or above, and JADE_CONFIG is not set", "JADE100")
            return cls()
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"{p}: not valid YAML: {e}") from None
        if not isinstance(data, dict):
            raise ConfigError(f"{p}: the top level must be a mapping")
        try:
            return cls(data, p)
        except JadeError as e:
            raise ConfigError(f"{p}: {e.message}") from None

    # dotted access: "targets.base.url"
    def get(self, key: str, default: Any = None) -> Any:
        v: Any = self.data
        for k in key.split("."):
            if not isinstance(v, dict) or k not in v:
                return default
            v = v[k]
        return v

    def set(self, key: str, value: Any) -> None:
        ks = key.split(".")
        if ks[0] not in KNOWN:
            raise ConfigError(f"unknown section {ks[0]!r} (sections: {', '.join(sorted(KNOWN))})")
        trial = copy.deepcopy(self.data)
        d = trial
        for k in ks[:-1]:
            d = d.setdefault(k, {})
            if not isinstance(d, dict):
                raise ConfigError(f"{key}: {k} is not a mapping")
        d[ks[-1]] = value
        validate(trial)
        self.data = trial

    def target(self, name: str) -> dict:
        return self.data["targets"].get(name) or {}

    def save(self, path: str | os.PathLike | None = None) -> Path:
        p = Path(path or self.path or NAME)
        validate(self.data)
        clean = {k: v for k, v in self.data.items() if v not in ({}, None) or k in ("version", "targets")}
        tmp = p.with_suffix(".tmp")
        tmp.write_text("# Jade Agent Stack configuration. No secrets here: they are in the OS keyring (jade secret list).\n"
                       + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True))
        os.replace(tmp, p)
        self.path = p
        return p

    def redacted(self) -> dict:
        return copy.deepcopy(self.data)  # holds secret names only, never values


def merge(a: dict, b: dict) -> dict:
    for k, v in (b or {}).items():
        a[k] = merge(a.get(k) or {}, v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a


def validate(d: dict) -> None:
    unknown = set(d) - KNOWN
    if unknown:
        raise ConfigError(f"unknown key(s) {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(KNOWN))})")
    if d.get("version", 1) != 1:
        raise ConfigError(f"version {d.get('version')!r}: this toolkit reads version 1")
    t = d.get("targets") or {}
    if not isinstance(t, dict):
        raise ConfigError("targets must be a mapping")
    for name, v in t.items():
        if name not in TARGETS:
            raise ConfigError(f"targets.{name}: unknown target (targets: {', '.join(TARGETS)})")
        if not isinstance(v, dict):
            raise ConfigError(f"targets.{name} must be a mapping")
        bad = set(v) - TARGET_KEYS[name]
        if bad:
            raise ConfigError(f"targets.{name}: unknown key(s) {', '.join(sorted(bad))} (allowed: {', '.join(sorted(TARGET_KEYS[name]))})")
        if "url" in v:
            u = urlparse(str(v["url"]))
            if u.scheme not in ("http", "https") or not u.netloc:
                raise ConfigError(f"targets.{name}.url must be an http(s) URL, not {v['url']!r}")
            if u.query and "token" in u.query:
                raise ConfigError(f"targets.{name}.url carries a token in its query: remove it (tokens go in the keyring)", "JADE102")
    for k, v in (d.get("approvals") or {}).items():
        if isinstance(v, bool):
            raise ConfigError(f"approvals.{k}: a bare true/false is not allowed; list what is allowed, e.g. {k}: [\"/notes/*\"]")
        if not isinstance(v, (list, dict)):
            raise ConfigError(f"approvals.{k}: a list of patterns, or a mapping with allow/deny (allow_hosts/deny_hosts)")
        if isinstance(v, dict):
            bad = set(v) - {"allow", "deny", "allow_hosts", "deny_hosts", "confirm"}
            if bad:
                raise ConfigError(f"approvals.{k}: unknown key(s) {', '.join(sorted(bad))}")
    for k, v in (d.get("defaults") or {}).items():
        if k in ("timeout", "chat_timeout") and not (isinstance(v, (int, float)) and v > 0):
            raise ConfigError(f"defaults.{k} must be a positive number of seconds")
