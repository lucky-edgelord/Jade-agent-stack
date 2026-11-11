"""What this toolkit works with (STACK.md is generated from this). Major mismatch: refuse. Older minor: warn."""

from __future__ import annotations

import re

TOOLKIT = "0.1.0"
# repo → (minimum version, repository, interface)
REQUIRES = {
    "base": ("0.6.0", "lucky-edgelord/jade-agent-base", "REST /api/agent/tools, MCP /api/agent/mcp, /api/agent/credentials"),
    "vault": ("2.18.3", "lucky-edgelord/jade-vault", "HTTP API /v1 (api 1), header-only auth"),
    "kit": ("3.1.0", "lucky-edgelord/Jade-agent-kit", "JS embed (ES module from a CDN)"),
    "ui": ("1.2.0", "lucky-edgelord/Jade-agent-ui-ux", "web components (ES module from a CDN)"),
}
# what generated pages load
CDN = {
    "kit": "https://cdn.jsdelivr.net/gh/lucky-edgelord/Jade-agent-kit@v3.1.0/dist/jade-agent-kit.js",
    "ui": "https://cdn.jsdelivr.net/gh/lucky-edgelord/Jade-agent-ui-ux@v1.2.0/dist/jade-ui.js",
}


def parse(v: str) -> tuple[int, int, int]:
    m = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v or ""))
    if not m:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in m.groups())  # type: ignore[return-value]


def check(repo: str, version: str) -> tuple[str, str]:
    """→ ("ok" | "warn" | "refuse", message)"""
    need = REQUIRES[repo][0]
    have, want = parse(version), parse(need)
    if have == (0, 0, 0):
        return "warn", f"{repo}: version unknown; this toolkit expects {need} or later in {want[0]}.x"
    if have[0] != want[0]:
        return "refuse", f"{repo} {version} is outside {want[0]}.x (this toolkit needs {need} or later in {want[0]}.x)"
    if have < want:
        return "warn", f"{repo} {version} is older than {need}; some features are missing"
    return "ok", f"{repo} {version}"
