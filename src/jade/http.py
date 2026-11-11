"""A small JSON-over-HTTP client on the standard library: header-only auth, timeouts, retries for reads only, and a
verbose log with the Authorization header and every registered secret redacted."""

from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .errors import AuthError, JadeError, RemoteError
from .redact import scrub

VERBOSE: Callable[[str], None] | None = None  # set by --verbose: receives redacted lines


def log(line: str) -> None:
    if VERBOSE:
        VERBOSE(scrub(line))


class Response:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except ValueError:
            return None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def request(method: str, url: str, *, token: str | None = None, body: Any = None, headers: dict | None = None,
            timeout: float = 30, retries: int = 0, raw: bool = False) -> Response:
    """one HTTP call. Retries (with backoff) only when retries > 0: callers pass retries only for reads."""
    if "?token=" in url or "&token=" in url:
        raise JadeError("refusing to put a token in a URL", "JADE102")
    h = {"Accept": "application/json", "User-Agent": "jade-agent-stack"}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    attempt = 0
    while True:
        attempt += 1
        log(f"→ {method} {url}" + (f" key={h['Idempotency-Key']}" if "Idempotency-Key" in h else ""))
        t0 = time.monotonic()
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
        except urllib.error.HTTPError as e:
            res = Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())
        except (socket.timeout, TimeoutError):
            if attempt <= retries:
                time.sleep(min(4, 0.3 * 2 ** attempt))
                continue
            raise JadeError(f"{method} {url} took longer than {timeout:g}s", "JADE204") from None
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            if attempt <= retries:
                time.sleep(min(4, 0.3 * 2 ** attempt))
                continue
            raise JadeError(f"cannot reach {url}: {scrub(str(getattr(e, 'reason', e)))}", "JADE200") from None
        log(f"← {res.status} {method} {url} {int((time.monotonic() - t0) * 1000)}ms")
        if res.status >= 500 and attempt <= retries:
            time.sleep(min(4, 0.3 * 2 ** attempt))
            continue
        if raw or res.status < 400:
            return res
        raise error_for(res, url)


def error_for(res: Response, url: str) -> JadeError:
    j = res.json()
    msg = ""
    code = None
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            msg, code = str(e.get("message") or ""), e.get("code")
        else:
            msg = str(e or j.get("message") or "")
        code = code or j.get("code")
    msg = scrub(msg or res.text[:300] or f"HTTP {res.status}")
    if code == "credential_refused":
        return RemoteError(msg, "JADE103", status=res.status)
    if code == "query_token_refused":
        return RemoteError(msg, "JADE102", status=res.status)
    if res.status == 401:
        return AuthError(f"{url}: {msg}")
    if res.status == 422 and "idempotency" in msg.lower():
        return RemoteError(msg, "JADE205", status=422)
    return RemoteError(f"{res.status}: {msg}", status=res.status)


def eprint(*a: Any) -> None:
    print(*(scrub(str(x)) for x in a), file=sys.stderr)
