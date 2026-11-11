"""Secrets live in the OS keyring (service "jade"), never in jade.config.yaml. Without a keyring, a 0600 file is used
only when allowed (--accept-file-secrets, or secrets.file: true). JADE_SECRET_<NAME> in the environment overrides
both (for CI), with the name upper-cased and non-alphanumerics turned into _."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .errors import JadeError
from .redact import Secret, register

SERVICE = "jade"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "jade"


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "jade"


def _env(name: str) -> str:
    return "JADE_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def _keyring():
    if os.environ.get("JADE_NO_KEYRING"):
        return None
    try:
        import keyring  # type: ignore
        from keyring.backends import fail  # type: ignore

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


class Store:
    def __init__(self, allow_file: bool = False):
        self.kr = _keyring()
        self.allow_file = allow_file
        self.file = config_dir() / "secrets.json"

    @property
    def backend(self) -> str:
        return "keyring" if self.kr else ("file" if self.allow_file else "none")

    def _read_file(self) -> dict:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {}

    def _write_file(self, d: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
        os.chmod(self.file, 0o600)

    def _index(self) -> set[str]:
        p = config_dir() / "secret-names.json"
        try:
            return set(json.loads(p.read_text()))
        except (OSError, ValueError):
            return set()

    def _save_index(self, names: set[str]) -> None:
        p = config_dir() / "secret-names.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(names)))

    def get(self, name: str, *, required: bool = True) -> Secret | None:
        v = os.environ.get(_env(name))
        if not v and self.kr:
            v = self.kr.get_password(SERVICE, name)
        if not v and self.allow_file:
            v = self._read_file().get(name)
        if not v:
            if required:
                raise JadeError(f"no secret named {name!r} ({self.backend} store; or set {_env(name)})", "JADE105")
            return None
        register(v)
        return Secret(v)

    def set(self, name: str, value: str) -> str:
        register(value)
        if self.kr:
            self.kr.set_password(SERVICE, name, value)
        elif self.allow_file:
            d = self._read_file()
            d[name] = value
            self._write_file(d)
        else:
            raise JadeError("no OS keyring is available", "JADE104")
        self._save_index(self._index() | {name})
        return self.backend

    def delete(self, name: str) -> bool:
        found = False
        if self.kr:
            try:
                self.kr.delete_password(SERVICE, name)
                found = True
            except Exception:
                pass
        if self.allow_file:
            d = self._read_file()
            if name in d:
                del d[name]
                self._write_file(d)
                found = True
        self._save_index(self._index() - {name})
        return found

    def names(self) -> list[str]:
        """the names (never the values) of stored secrets"""
        n = self._index()
        if self.allow_file:
            n |= set(self._read_file())
        n |= {k[len("JADE_SECRET_"):].lower() for k in os.environ if k.startswith("JADE_SECRET_")}
        return sorted(n)
