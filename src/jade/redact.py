"""Keeps secrets out of output: every token the toolkit loads is registered here, and text is scrubbed before it is
printed, logged or put in an error."""

from __future__ import annotations

import re
import threading

_lock = threading.Lock()
_secrets: set[str] = set()
NOT_SECRET = {"idempotency_key", "last_key", "key_name"}
_SECRETISH = re.compile(r"(?i)(authorization|token|secret|password|api[_-]?key|key)$")


def register(*values: str | None) -> None:
    with _lock:
        for v in values:
            if v and len(v) >= 6:
                _secrets.add(v)


def scrub(text: str) -> str:
    if not text:
        return text
    with _lock:
        ss = sorted(_secrets, key=len, reverse=True)
    for s in ss:
        if s in text:
            text = text.replace(s, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}", r"\1***", text)


def deep(v):
    """a copy of a JSON value with secret-looking keys and registered secrets hidden"""
    if isinstance(v, dict):
        return {k: ("***" if _SECRETISH.search(str(k)) and k not in NOT_SECRET and isinstance(x, str) and x else deep(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [deep(x) for x in v]
    if isinstance(v, str):
        return scrub(v)
    return v


class Secret(str):
    """a string that never shows itself in repr() or f'{x!r}'"""

    def __new__(cls, value: str):
        register(value)
        return super().__new__(cls, value)

    def __repr__(self) -> str:
        return "Secret('***')"

    def reveal(self) -> str:
        return str.__str__(self)
