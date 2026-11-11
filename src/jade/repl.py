"""The REPL: the commands, typed. `jade repl` for people, `jade repl --jsonl` for programs (one JSON request per line,
one JSON answer per line), and the wizard harness an agent can drive over a pipe.

    jade> site templates
    jade> site new "Acme" template=saas
    jade> docs search idempotency
    jade> help site.build

JSON lines: {"id": 1, "cmd": "docs.search", "args": {"query": "approvals"}} → {"id": 1, "schema": "jade.v1", "ok": true, "data": [...]}"""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from . import commands
from .cli import show
from .errors import JadeError
from .redact import deep, scrub

HELP = """Type a command and its arguments: positional values, then key=value (values may be JSON).
  commands                 every command          help <command>     one command
  docs topics | docs show <topic#heading> | docs search <words>
  site templates | site new <name> template=saas | site build | site plan | site deploy
  playbook list | playbook plan <name> | playbook run <name> var=k=v
  base tools names=true | base call <tool> args={...}      quit"""


def parse(line: str) -> tuple[str, dict]:
    words = shlex.split(line)
    names = set(commands.REGISTRY)
    name, i = "", 0
    for j in range(len(words), 0, -1):
        cand = ".".join(words[:j])
        if cand in names:
            name, i = cand, j
            break
    if not name:
        raise JadeError(f"unknown command {' '.join(words[:2])!r} (type: commands)", "JADE405")
    c = commands.REGISTRY[name]
    pos = [p for p in c.params if p.positional]
    args: dict[str, Any] = {}
    for w in words[i:]:
        if "=" in w and w.split("=", 1)[0].replace("_", "").replace("-", "").isalnum() and w.split("=", 1)[0] in {p.name for p in c.params} | {p.name.replace("_", "-") for p in c.params}:
            k, v = w.split("=", 1)
            k = k.replace("-", "_")
            if k == "var":
                args.setdefault("var", []).append(v)
                continue
            try:
                args[k] = json.loads(v) if v[:1] in "[{\"" or v in ("true", "false", "null") or v.replace(".", "", 1).isdigit() else v
            except ValueError:
                args[k] = v
        elif pos:
            args[pos.pop(0).name] = w
        else:
            raise JadeError(f"{name}: what is {w!r}? (arguments: {', '.join(p.name for p in c.params)})", "JADE400")
    return name, args


def run(ctx: commands.Context, jsonl: bool = False) -> int:
    ctx.surface = "jsonl" if jsonl else "repl"
    if jsonl:
        ctx.interactive = False
        ctx.ask = None
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            rid = None
            try:
                req = json.loads(line)
                rid = req.get("id")
                data = commands.call(req["cmd"], req.get("args") or {}, ctx)
                out = commands.envelope(True, data, command=req["cmd"])
            except JadeError as e:
                out = commands.envelope(False, error=e)
            except (ValueError, KeyError, TypeError) as e:
                out = commands.envelope(False, error=JadeError(f"bad request: {e}", "JADE400"))
            if rid is not None:
                out["id"] = rid
            sys.stdout.write(json.dumps(deep(out), default=str) + "\n")
            sys.stdout.flush()
        return 0
    print("Jade Agent Stack. Type help, or a command (e.g. docs topics). Ctrl-D to leave.", file=sys.stderr)
    while True:
        try:
            line = input("jade> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line in ("help", "?"):
            print(HELP)
            continue
        if line.startswith("help "):
            try:
                print(show(commands.describe(line[5:].strip().replace(" ", "."))))
            except JadeError as e:
                print(e)
            continue
        try:
            name, args = parse(line)
            data = commands.call(name, args, ctx)
            if data is not None:
                print(scrub(show(deep(data))))
        except JadeError as e:
            print(scrub(str(e)))
