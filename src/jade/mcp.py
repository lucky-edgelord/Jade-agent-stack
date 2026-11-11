"""`jade mcp`: the commands as MCP tools over stdio (JSON-RPC 2.0, one message per line), for any MCP client.
Tool names use _ for . (site_build, docs_search, playbook_run). Nothing here asks a person: approvals in
jade.config.yaml decide, and playbooks must be approved to run."""

from __future__ import annotations

import json
import sys
from typing import Any

from . import commands, compat
from .errors import JadeError
from .redact import deep

PROTOCOL = "2025-06-18"
TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "json": "object", "list": "array"}


def tools() -> list[dict]:
    out = []
    for c in commands.REGISTRY.values():
        if "mcp" not in c.surfaces:
            continue
        props = {}
        for p in c.params:
            if p.secret:
                continue
            s: dict[str, Any] = {"type": TYPES[p.type], "description": p.help or p.name}
            if p.type == "list":
                s["items"] = {"type": "string"}
            if p.type == "json":
                s = {"description": p.help or p.name}
            if p.choices:
                s["enum"] = list(p.choices)
            if p.default not in (None, False, "", []):
                s["default"] = p.default
            props[p.name] = s
        out.append({"name": c.name.replace(".", "_"), "description": c.help, "inputSchema": {"type": "object", "properties": props,
                    "required": [p.name for p in c.params if p.required]}, "annotations": {"readOnlyHint": not c.mutates}})
    return out


def handle(req: dict, ctx: commands.Context) -> dict | None:
    rid = req.get("id")
    m = req.get("method", "")
    if rid is None:
        return None
    ok = lambda r: {"jsonrpc": "2.0", "id": rid, "result": r}
    if m == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "jade-agent-stack", "version": compat.TOOLKIT},
                   "instructions": "Build sites (site_templates, site_new, site_build, site_plan, site_deploy), run playbooks (playbook_list, playbook_plan, playbook_run), "
                                   "call Base and Vault, and read the docs (docs_search, docs_show). Start with docs_show start."})
    if m == "ping":
        return ok({})
    if m == "tools/list":
        return ok({"tools": tools()})
    if m == "tools/call":
        p = req.get("params") or {}
        name = str(p.get("name", "")).replace("_", ".")
        # names with underscores in parts (none today) would need a map; resolve against the registry
        cand = [c for c in commands.REGISTRY if c.replace(".", "_") == p.get("name")]
        name = cand[0] if cand else name
        try:
            data = commands.call(name, p.get("arguments") or {}, ctx)
            text = data if isinstance(data, str) else json.dumps(deep(data), indent=1, default=str)
            return ok({"content": [{"type": "text", "text": text}], "structuredContent": deep(data) if isinstance(data, dict) else {"result": deep(data)}})
        except JadeError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True, "structuredContent": {"error": e.to_dict()}})
    if m in ("resources/list", "prompts/list"):
        return ok({m.split("/")[0]: []})
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {m}"}}


def serve_stdio(ctx: commands.Context) -> None:
    ctx.surface, ctx.interactive, ctx.ask = "mcp", False, None
    out = sys.stdout
    sys.stdout = sys.stderr  # nothing but protocol on stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            out.flush()
            continue
        reqs = req if isinstance(req, list) else [req]
        res = [r for r in (handle(x, ctx) for x in reqs) if r is not None]
        if res:
            out.write(json.dumps(res if isinstance(req, list) else res[0], default=str) + "\n")
            out.flush()
