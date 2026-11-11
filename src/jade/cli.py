"""The `jade` command line. Every command comes from jade.commands (the same ones the REPL, MCP and HTTP use).
Exit codes: 0 ok, 1 user error, 2 remote error, 3 refused for safety. --json prints {"schema": "jade.v1", "ok", "data"|"error"}."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from . import commands, http
from .commands import REGISTRY, Context, envelope
from .errors import JadeError
from .redact import deep, scrub
from .secrets import state_dir

GLOBAL = [
    ("--json", "print one JSON object (schema jade.v1)"),
    ("--verbose", "show HTTP calls (Authorization and secrets redacted)"),
    ("--yolo", "allow what no approval covers, and destructive calls, without asking (logged)"),
    ("--accept-legacy", "diagnosis only: talk to a Vault that accepts ?token= in URLs"),
    ("--accept-file-secrets", "without an OS keyring, keep secrets in a 0600 file"),
    ("--force", "go on after a failed `jade doctor`"),
    ("--no-input", "never ask; fail instead"),
]
TOUCHES_TARGETS = ("vault.", "base.", "agent.", "playbook.run", "site.deploy")
EXTRA = {"init": "Set up jade.config.yaml step by step (resumable).", "serve": "Serve playbooks and commands over HTTP (127.0.0.1:9765).",
         "mcp": "Serve the commands as MCP tools over stdio.", "repl": "An interactive shell for the commands (--jsonl for programs).",
         "completion": "Print shell completion: bash, zsh or fish.", "wizard": "The same as init."}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jade", description="Jade Agent Stack: Vault, Base, Kit and UI/UX from one command line. `jade docs search <words>` finds help.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="a jade.config.yaml (default: found upward from here, or $JADE_CONFIG)")
    for f, h in GLOBAL:
        ap.add_argument(f, action="store_true", help=h)
    sub = ap.add_subparsers(dest="_cmd", metavar="command")
    tree: dict[str, Any] = {}
    for name, c in REGISTRY.items():
        if "cli" not in c.surfaces:
            continue
        parts = name.split(".")
        node, parsers = tree, sub
        for i, part in enumerate(parts):
            key = ".".join(parts[: i + 1])
            if key not in node:
                last = i == len(parts) - 1
                p = parsers.add_parser(part, help=c.help if last else f"{part} commands", description=c.help if last else None)
                node[key] = {"parser": p, "sub": None}
                if not last:
                    node[key]["sub"] = p.add_subparsers(dest=f"_{key}", metavar="command")
            entry = node[key]
            if i == len(parts) - 1:
                _add_params(entry["parser"], c)
            else:
                if entry["sub"] is None:
                    entry["sub"] = entry["parser"].add_subparsers(dest=f"_{key}", metavar="command")
                parsers = entry["sub"]
    for name, h in EXTRA.items():
        p = sub.add_parser(name, help=h, description=h)
        if name in ("init", "wizard"):
            p.add_argument("--yes", action="store_true", help="accept every default")
            p.add_argument("--answers", help="a JSON file of answers (headless)")
            p.add_argument("--only", help="run one step")
            for s in ("environment", "targets", "auth", "models", "permissions", "smoke", "write"):
                p.add_argument(f"--skip-{s}", action="store_true", help=f"skip the {s} step")
            p.add_argument("--base-url"); p.add_argument("--vault-url"); p.add_argument("--target", choices=("base", "vault", "both", "kit"))
            p.add_argument("--insecure-plaintext", action="store_true", help="the same as --accept-file-secrets")
            p.add_argument("--restart", action="store_true", help="forget earlier answers")
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=9765)
            p.add_argument("--token", help="required off loopback: clients send Authorization: Bearer <token>")
        if name == "repl":
            p.add_argument("--jsonl", action="store_true", help="read JSON lines, write JSON lines")
        if name == "completion":
            p.add_argument("shell", choices=("bash", "zsh", "fish"))
    return ap


def _add_params(p: argparse.ArgumentParser, c: commands.Command) -> None:
    for prm in c.params:
        kw: dict[str, Any] = {"help": prm.help + (f" (default {prm.default})" if prm.default not in (None, False, "", []) else "")}
        if prm.choices:
            kw["choices"] = prm.choices
        if prm.positional:
            if not prm.required:
                kw["nargs"] = "?"
                kw["default"] = None
            p.add_argument(prm.name, **kw)
            continue
        flag = "--" + prm.name.replace("_", "-")
        if prm.type == "bool":
            p.add_argument(flag, dest=prm.name, action="store_true", **kw)
        elif prm.name == "var":
            p.add_argument(flag, dest=prm.name, action="append", **kw)
        else:
            p.add_argument(flag, dest=prm.name, **kw)


def _cmd_name(ns: argparse.Namespace) -> str | None:
    if not ns._cmd:
        return None
    name = ns._cmd
    while True:
        nxt = getattr(ns, f"_{name}", None)
        if not nxt:
            return name
        name = f"{name}.{nxt}"


def show(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data) and len(data[0]) <= 6 and all(not isinstance(v, (dict, list)) for x in data for v in x.values()):
        keys = list(dict.fromkeys(k for x in data for k in x))
        w = {k: min(48, max(len(k), *(len(str(x.get(k, ""))) for x in data))) for k in keys}
        rows = ["  ".join(k.ljust(w[k]) for k in keys)] + ["  ".join(str(x.get(k, ""))[: w[k]].ljust(w[k]) for k in keys) for x in data]
        return "\n".join(r.rstrip() for r in rows)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120).rstrip()


def _doctor_file() -> Path:
    return state_dir() / "doctor.json"


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    # global flags may come anywhere: jade base tools --json
    argv = list(sys.argv[1:] if argv is None else argv)
    flags = {f for f, _ in GLOBAL}
    front, rest, i = [], [], 0
    while i < len(argv):
        x = argv[i]
        if x in flags:
            front.append(x)
        elif x == "--config" and i + 1 < len(argv):
            front += [x, argv[i + 1]]
            i += 1
        elif x.startswith("--config="):
            front.append(x)
        else:
            rest.append(x)
        i += 1
    ns = ap.parse_args(front + rest)
    if ns.verbose:
        http.VERBOSE = lambda line: print(line, file=sys.stderr)
    interactive = not ns.no_input and not ns.json and sys.stdin.isatty()
    from .harness import tty_ask
    ctx = Context(config=ns.config, yolo=ns.yolo, accept_legacy=ns.accept_legacy, accept_file_secrets=ns.accept_file_secrets or getattr(ns, "insecure_plaintext", False) or None,
                  force=ns.force, interactive=interactive, ask=tty_ask if interactive else None, surface="cli")
    name = _cmd_name(ns)
    if not name:
        ap.print_help()
        return 1
    try:
        if name in ("init", "wizard"):
            from .wizard import run as wizard
            data = wizard(ns, ctx)
        elif name == "serve":
            from .serve import serve
            data = serve(ns.host, ns.port, ns.token, ctx)
        elif name == "mcp":
            from .mcp import serve_stdio
            serve_stdio(ctx)
            return 0
        elif name == "repl":
            from .repl import run as repl
            return repl(ctx, jsonl=ns.jsonl)
        elif name == "completion":
            print(completion(ns.shell))
            return 0
        elif name not in REGISTRY:  # a group without a subcommand
            ap.parse_args([*name.split("."), "--help"])
            return 1
        else:
            if name.startswith(TOUCHES_TARGETS) and not ns.force:
                try:
                    last = json.loads(_doctor_file().read_text())
                    if not last.get("ok"):
                        raise JadeError(f"the last `jade doctor` failed ({'; '.join(last.get('problems', []))[:300]})", "JADE500")
                except (OSError, ValueError):
                    pass
            c = REGISTRY[name]
            args = {p.name: getattr(ns, p.name) for p in c.params if getattr(ns, p.name, None) is not None}
            try:
                data = commands.call(name, args, ctx)
            finally:
                if name == "doctor":
                    _record_doctor(ctx)
    except JadeError as e:
        if ns.json:
            print(json.dumps(deep(envelope(False, error=e, command=name or "")), default=str))
        else:
            print(scrub(str(e)), file=sys.stderr)
            if e.data.get("problems") and len(e.data["problems"]) > 1:
                for p in e.data["problems"]:
                    print("  - " + scrub(p), file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    if ns.json:
        print(json.dumps(deep(envelope(True, data, command=name)), default=str))
    elif data is not None and not (name in ("playbook.run", "site.deploy") and interactive):
        print(scrub(show(deep(data))))
    elif data is not None:
        print("done")
    return 0


def _record_doctor(ctx: Context) -> None:
    try:
        st = ctx.harness().status() if ctx._h else None
    except JadeError as e:
        st = {"ok": False, "problems": [e.message]}
    if st is None:
        return
    p = _doctor_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ok": st["ok"], "problems": st.get("problems", []), "time": time.time()}))


def completion(shell: str) -> str:
    names = sorted({n.split(".")[0] for n in REGISTRY} | set(EXTRA))
    subs = {}
    for n in REGISTRY:
        parts = n.split(".")
        for i in range(1, len(parts)):
            subs.setdefault(" ".join(parts[:i]), set()).add(parts[i])
    if shell == "bash":
        cases = "\n".join(f'    "{k}") opts="{" ".join(sorted(v))}";;' for k, v in subs.items())
        return f"""# bash completion for jade: eval "$(jade completion bash)"
_jade() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}" path="${{COMP_WORDS[*]:1:COMP_CWORD-1}}" opts="{' '.join(names)}"
  case "$path" in
{cases}
  esac
  COMPREPLY=( $(compgen -W "$opts --json --verbose --help" -- "$cur") )
}}
complete -F _jade jade"""
    if shell == "zsh":
        return "# zsh completion for jade: eval \"$(jade completion zsh)\"\nautoload -U bashcompinit && bashcompinit\n" + completion("bash")
    lines = [f"complete -c jade -f -n '__fish_use_subcommand' -a '{' '.join(names)}'"]
    for k, v in subs.items():
        lines.append(f"complete -c jade -f -n '__fish_seen_subcommand_from {k.split()[-1]}' -a '{' '.join(sorted(v))}'")
    return "# fish completion for jade: jade completion fish | source\n" + "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
