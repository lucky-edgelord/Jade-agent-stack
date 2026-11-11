"""One registry of commands, used by every surface: the CLI (`jade site build`), the REPL (`site build out=dist`), the
JSON-lines harness ({"cmd": "site.build", "args": {...}}), MCP (tool site_build) and HTTP (POST /v1/commands/site.build).
The payload shapes are the same everywhere; results are JSON values."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from . import compat
from .errors import JadeError

SCHEMA = "jade.v1"


@dataclasses.dataclass
class Param:
    name: str
    type: str = "str"  # str, int, float, bool, json, list
    help: str = ""
    default: Any = None
    required: bool = False
    positional: bool = False
    choices: tuple = ()
    secret: bool = False


@dataclasses.dataclass
class Command:
    name: str
    help: str
    params: list[Param]
    run: Callable[..., Any]
    surfaces: tuple = ("cli", "repl", "mcp", "http")
    mutates: bool = False
    example: str = ""


REGISTRY: dict[str, Command] = {}


def command(name: str, help: str, *params: Param, surfaces: tuple = ("cli", "repl", "mcp", "http"), mutates: bool = False, example: str = ""):
    def deco(fn):
        REGISTRY[name] = Command(name, help, list(params), fn, surfaces, mutates, example)
        return fn
    return deco


@dataclasses.dataclass
class Context:
    config: str | None = None
    yolo: bool = False
    accept_legacy: bool = False
    accept_file_secrets: bool | None = None
    force: bool = False
    interactive: bool = True
    ask: Callable[[str], bool] | None = None
    out: Callable[[str], None] = lambda s: print(s)
    surface: str = "cli"
    _h: Any = None

    def harness(self):
        if self._h is None:
            from .harness import Harness
            self._h = Harness.load(self.config, ask=self.ask if self.interactive else None, yolo=self.yolo, accept_legacy=self.accept_legacy,
                                   accept_file_secrets=self.accept_file_secrets)
        return self._h


def coerce(p: Param, v: Any) -> Any:
    if v is None:
        return None
    if p.type == "int":
        return int(v)
    if p.type == "float":
        return float(v)
    if p.type == "bool":
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "y", "on")
    if p.type == "json":
        if isinstance(v, str):
            if v == "-":
                v = sys.stdin.read()
            elif v.startswith("@"):
                v = Path(v[1:]).read_text()
            try:
                return json.loads(v) if v.strip() else {}
            except ValueError as e:
                raise JadeError(f"--{p.name}: not JSON ({e})", "JADE400") from None
        return v
    if p.type == "list":
        return v if isinstance(v, list) else [x.strip() for x in str(v).split(",") if x.strip()]
    return str(v)


AGENT_SURFACES = ("mcp", "http", "jsonl")
PROTECTED = ("approvals", "secrets.file", "targets.vault.accept_legacy", "playbooks.routes")


def person_only(ctx: "Context", what: str) -> None:
    """an agent must not widen its own permissions: over MCP, HTTP and JSON lines this needs a person"""
    if ctx.surface in AGENT_SURFACES:
        raise JadeError(f"{what} needs a person: run it in a terminal (`jade …`), not over {ctx.surface}", "JADE302")


def call(name: str, args: dict | None = None, ctx: Context | None = None) -> Any:
    """run a command by name with a dict of arguments"""
    c = REGISTRY.get(name) or REGISTRY.get(name.replace("_", ".").replace(" ", "."))
    if c is None:
        raise JadeError(f"no command {name!r} (commands: {', '.join(REGISTRY)})", "JADE405")
    ctx = ctx or Context(interactive=False)
    args = dict(args or {})
    kw = {}
    for p in c.params:
        v = args.pop(p.name, args.pop(p.name.replace("_", "-"), None))
        if v is None:
            if p.required:
                raise JadeError(f"{c.name}: {p.name} is required", "JADE400")
            v = p.default
        else:
            v = coerce(p, v)
        if p.choices and v is not None and v not in p.choices:
            raise JadeError(f"{c.name}: {p.name} must be one of {', '.join(map(str, p.choices))}", "JADE400")
        kw[p.name] = v
    if args:
        raise JadeError(f"{c.name}: unknown argument(s) {', '.join(args)} (arguments: {', '.join(p.name for p in c.params) or 'none'})", "JADE400")
    return c.run(ctx, **kw)


def envelope(ok: bool, data: Any = None, error: JadeError | None = None, command: str = "") -> dict:
    out: dict[str, Any] = {"schema": SCHEMA, "ok": ok, "command": command}
    if ok:
        out["data"] = data
    else:
        out["error"] = error.to_dict() if error else {"code": "JADE400", "message": "error"}
    return out


def describe(name: str | None = None) -> Any:
    """the command list for agents: name, help, parameters"""
    def one(c: Command) -> dict:
        return {"name": c.name, "help": c.help, "mutates": c.mutates,
                "params": [{"name": p.name, "type": p.type, "help": p.help, **({"required": True} if p.required else {}),
                            **({"default": p.default} if p.default not in (None, False, "", []) else {}), **({"choices": list(p.choices)} if p.choices else {})} for p in c.params],
                **({"example": c.example} if c.example else {})}
    if name:
        c = REGISTRY.get(name)
        if not c:
            raise JadeError(f"no command {name!r}", "JADE405")
        return one(c)
    return [one(c) for c in REGISTRY.values()]


P = Param


# ================= commands =================

@command("version", "The toolkit version and the versions it works with.")
def _version(ctx):
    return {"jade": compat.TOOLKIT, "python": sys.version.split()[0], "requires": {k: v[0] for k, v in compat.REQUIRES.items()}}


@command("doctor", "Check the config, secrets and every target: reachable, authenticated, compatible, no URL tokens.")
def _doctor(ctx):
    h = ctx.harness()
    st = h.status()
    if not st["ok"]:
        raise JadeError("; ".join(st["problems"]), "JADE500", data=st)
    return st


@command("config.show", "The configuration (it never holds secrets).")
def _config_show(ctx):
    from .config import Config
    c = Config.load(ctx.config)
    return {"path": str(c.path or ""), "config": c.redacted()}


@command("config.get", "One configuration value by dotted key, e.g. targets.base.url.", P("key", required=True, positional=True))
def _config_get(ctx, key):
    from .config import Config
    v = Config.load(ctx.config).get(key)
    if v is None:
        raise JadeError(f"{key} is not set", "JADE405")
    return v


@command("config.set", "Set a configuration value: KEY=VALUE (VALUE may be JSON).", P("assignment", required=True, positional=True, help="key=value"), mutates=True)
def _config_set(ctx, assignment):
    from .config import Config
    if "=" not in assignment:
        raise JadeError("use KEY=VALUE, e.g. targets.base.url=https://api.example.com", "JADE400")
    k, v = assignment.split("=", 1)
    if k.strip().startswith(PROTECTED) or k.strip() in ("targets", "") or k.strip().startswith("targets.") and k.strip().endswith(".url"):
        person_only(ctx, f"changing {k.strip()}")
    try:
        val = json.loads(v)
    except ValueError:
        val = v
    c = Config.load(ctx.config)
    c.set(k.strip(), val)
    return {"path": str(c.save()), "set": k.strip()}


@command("config.edit", "Open jade.config.yaml in $EDITOR, then check it.", surfaces=("cli",))
def _config_edit(ctx):
    import subprocess
    from .config import Config, find
    p = find() or Path("jade.config.yaml")
    if not p.exists():
        Config().save(p)
    subprocess.call([os.environ.get("EDITOR", "vi"), str(p)])
    Config.load(p)
    return {"path": str(p), "ok": True}


@command("secret.set", "Store a secret in the OS keyring. The value comes from --value, $JADE_SECRET_VALUE, or a hidden prompt.",
         P("name", required=True, positional=True), P("value", secret=True, help="avoid: shells keep history"), mutates=True)
def _secret_set(ctx, name, value):
    person_only(ctx, "storing a secret")
    from .secrets import Store
    value = value or os.environ.get("JADE_SECRET_VALUE")
    if not value:
        if not (sys.stdin and sys.stdin.isatty()):
            value = sys.stdin.readline().strip()
        else:
            import getpass
            value = getpass.getpass(f"{name}: ")
    if not value:
        raise JadeError("no value", "JADE400")
    st = Store(allow_file=bool(ctx.accept_file_secrets))
    return {"name": name, "stored_in": st.set(name, value)}


@command("secret.list", "The names of stored secrets (never their values).")
def _secret_list(ctx):
    from .secrets import Store
    st = Store(allow_file=bool(ctx.accept_file_secrets))
    return {"backend": st.backend, "names": st.names()}


@command("secret.rm", "Delete a stored secret.", P("name", required=True, positional=True), mutates=True)
def _secret_rm(ctx, name):
    person_only(ctx, "deleting a secret")
    from .secrets import Store
    return {"name": name, "deleted": Store(allow_file=bool(ctx.accept_file_secrets)).delete(name)}


# ---- vault ----
@command("vault.status", "Vault's status (header auth; refuses a Vault that accepts URL tokens).")
def _vault_status(ctx):
    return ctx.harness().call("vault", "status")


@command("vault.chat", "Send a message to Vault's agent and wait for the answer.", P("message", required=True, positional=True), P("session", help="a chat id, or new"),
         P("timeout", "float"), mutates=True)
def _vault_chat(ctx, message, session, timeout):
    return ctx.harness().call("vault", "chat", {"message": message, **({"session": session} if session else {})}, timeout=timeout)


@command("vault.flows", "Vault's flows.")
def _vault_flows(ctx):
    return ctx.harness().call("vault", "flows")


@command("vault.flow.run", "Run a Vault flow by name.", P("name", required=True, positional=True), P("input", "json", "JSON, -, or @file"), P("timeout", "float"), mutates=True)
def _vault_flow(ctx, name, input, timeout):
    return ctx.harness().call("vault", "flow", {"name": name, **({"input": input} if input is not None else {})}, timeout=timeout)


# ---- base ----
@command("base.tools", "The tools this Base token may use.", P("format", choices=("openai", "anthropic", "mcp"), help='the shape: openai, anthropic or mcp (default: with scope and destructive)'), P("names", "bool", "names only"))
def _base_tools(ctx, format, names):
    t = ctx.harness().base.tools(format)
    if names:
        return [x.get("name") or (x.get("function") or {}).get("name") for x in t]
    return t


@command("base.call", "Call a Base tool (approvals apply; mutations get an idempotency key).", P("tool", required=True, positional=True),
         P("args", "json", "JSON, -, or @file", default=None), P("idempotency_key", help="default: a new UUIDv7"), P("timeout", "float"), mutates=True,
         example='jade base call records_list --args \'{"collection":"posts"}\'')
def _base_call(ctx, tool, args, idempotency_key, timeout):
    h = ctx.harness()
    out = h.call("base", tool, args or {}, idempotency_key=idempotency_key, timeout=timeout)
    return {"result": out, "idempotency_key": h.base.last_key}


@command("base.audit", "The audit log: what agents did (and what was refused).", P("limit", "int", default=50, help='how many entries'), P("tool"))
def _base_audit(ctx, limit, tool):
    return ctx.harness().call("base", "audit_list", {"limit": limit, **({"tool": tool} if tool else {})})


@command("base.credential", "Mint a short-lived task credential (prints only its id, scopes and expiry).", P("task_id", required=True, positional=True),
         P("scopes", "list", default=["read"], help='the fewest scopes the task needs, comma-separated'), P("ttl", default="15m", help='how long it lasts: 15m, 2h (at most 24h)'), mutates=True)
def _base_cred(ctx, task_id, scopes, ttl):
    c = ctx.harness().base.mint(task_id, scopes, ttl)
    return {k: v for k, v in c.items() if k != "token"}


# ---- kit / ui ----
@command("kit.page", "Write a page that runs Jade Agent Kit in the browser.", P("out", required=True, positional=True), P("features", "list", default=["agent"], help='Kit features to load, comma-separated (agent, sqlite, bm25, …)'),
         P("ollama", help="Ollama host"), P("model"), P("title", default="Jade agent"), mutates=True)
def _kit_page(ctx, out, features, ollama, model, title):
    from .resources import kit
    r = kit.page(features, ollama=ollama, model=model, title=title, out=out)
    return {"out": out, "manifest": r["manifest"]}


@command("ui.chat", "Write a page with a chat: full-screen, inline or a floating widget.", P("out", required=True, positional=True),
         P("mount", default="full-screen", choices=("full-screen", "widget", "inline"), help='full-screen, inline, or widget (a floating button)'), P("preset", default="jade", help="a theme"), P("mode", default="auto", choices=("auto", "light", "dark"), help='light, dark, or auto (follows the system)'),
         P("base", help="a Jade Agent Base URL"), P("title", default="Chat"), mutates=True)
def _ui_chat(ctx, out, mount, preset, mode, base, title):
    from .resources import ui
    ui.chat(mount=mount, theme={"preset": preset, "mode": mode}, base=base, title=title, out=out)
    return {"out": out, "mount": mount, "theme": preset}


# ---- playbooks ----
def _vars(v):
    out = {}
    for x in v or []:
        k, _, val = str(x).partition("=")
        try:
            out[k] = json.loads(val)
        except ValueError:
            out[k] = val
    return out


@command("playbook.list", "Playbooks here (./, ./playbooks, ./examples) and whether each is approved.")
def _pb_list(ctx):
    from . import playbook
    out = []
    for name, p in playbook.discover().items():
        try:
            pb = playbook.load(p)
            out.append({"name": name, "path": str(p), "description": pb.data.get("metadata", {}).get("description", ""), "approved": playbook.approved(pb)})
        except JadeError as e:
            out.append({"name": name, "path": str(p), "error": e.message})
    return out


@command("playbook.check", "Validate a playbook: schema, expressions, targets, and tools and arguments against the live targets.", P("name", required=True, positional=True),
         P("offline", "bool", "do not contact targets"))
def _pb_check(ctx, name, offline):
    from . import playbook
    pb = playbook.load(name)
    return pb.check(None if offline else _maybe_harness(ctx))


@command("playbook.plan", "Every call a playbook would make, with arguments and idempotency keys. Makes no calls.", P("name", required=True, positional=True),
         P("var", "list", "k=v, repeatable"))
def _pb_plan(ctx, name, var):
    from . import playbook
    return playbook.load(name).plan(_vars(var))


@command("playbook.run", "Run a playbook (resumes an interrupted run with the same vars). Unattended runs need it approved.", P("name", required=True, positional=True),
         P("var", "list", "k=v, repeatable"), P("fresh", "bool", "start over instead of resuming"), mutates=True)
def _pb_run(ctx, name, var, fresh):
    from . import playbook
    pb = playbook.load(name)
    events = []
    for ev in pb.run(ctx.harness(), _vars(var), resume=not fresh, unattended=not ctx.interactive):
        events.append(ev)
        if ctx.surface == "cli" and ctx.interactive:
            ctx.out(_event_line(ev))
    last = events[-1] if events else {}
    if not last.get("ok"):
        raise JadeError(f"playbook {pb.name} failed", "JADE202", data={"events": events})
    return {"ok": True, "run": last.get("run"), "events": events}


def _event_line(ev: dict) -> str:
    e = ev["event"]
    if e == "task":
        return f"→ {ev['task']} ({ev['target']}.{ev['tool']})"
    if e == "ok":
        return f"  ✓ {ev['task']}" + ("" if ev.get("changed") else " (no change)")
    if e == "error":
        return f"  ✗ {ev['task']}: {ev['error']}"
    if e == "skip":
        return f"  · {ev['task']}: {ev['why']}"
    return f"[{e}] " + ", ".join(f"{k}={v}" for k, v in ev.items() if k not in ("event", "vars", "result"))


@command("playbook.approve", "Approve a playbook as it is now (its hash is signed; any edit needs a new approval).", P("name", required=True, positional=True), mutates=True)
def _pb_approve(ctx, name):
    person_only(ctx, "approving a playbook")
    from . import playbook
    return playbook.approve(playbook.load(name))


@command("playbook.revoke", "Withdraw a playbook's approval.", P("name", required=True, positional=True), mutates=True)
def _pb_revoke(ctx, name):
    from . import playbook
    return {"name": name, "revoked": playbook.revoke(name)}


@command("playbook.logs", "Runs of a playbook (or all) and the state of each task.", P("name", positional=True))
def _pb_logs(ctx, name):
    from . import playbook
    return playbook.runs(name)


# ---- sites ----
@command("site.templates", "Site templates (a spec can be just name, tagline and template).")
def _site_templates(ctx):
    from .site.spec import templates
    return templates()


@command("site.themes", "Themes for sites and pages.")
def _site_themes(ctx):
    from .site import themes
    return {n: themes.get(n)["description"] for n in themes.names()}


@command("site.sections", "The section library: one line each, or one section's parameters in full.", P("name", positional=True))
def _site_sections(ctx, name):
    from .site import sections
    return sections.describe(name)


@command("site.new", "Write a jade.site.yaml from a template.", P("name", required=True, positional=True), P("template", default="landing", help='a template (jade site templates)'), P("tagline", default="", help='one line under the name'),
         P("theme", help='a theme (jade site themes)'), P("dir", default=".", help='the folder for jade.site.yaml'), P("url", help='the public address of the site'), mutates=True)
def _site_new(ctx, name, template, tagline, theme, dir, url):
    from .site.spec import SPEC_NAME, Site, template as tpl
    tpl(template)
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / SPEC_NAME
    if p.exists():
        raise JadeError(f"{p} exists", "JADE400")
    spec = {"name": name, "tagline": tagline or f"{name}, built with Jade.", "template": template}
    if theme:
        spec["theme"] = theme
    if url:
        spec["url"] = url
    Site(**spec).save(p)
    return {"spec": str(p), "next": f"jade site build {dir}"}


def _site(dir):
    from .site.spec import Site
    return Site.load(dir or ".")


@command("site.check", "Check a site spec (and that it compiles).", P("dir", default=".", positional=True))
def _site_check(ctx, dir):
    return _site(dir).check()


@command("site.build", "Compile the site to static files.", P("dir", default=".", positional=True), P("out", default="dist", help='the output folder'), P("ui", help="UI/UX module URL"),
         P("kit", help="Kit module URL"), mutates=True)
def _site_build(ctx, dir, out, ui, kit):
    s = _site(dir)
    r = s.build(Path(dir or ".") / out if not Path(out).is_absolute() else out, ui=ui, kit=kit)
    return {"out": r["out"], "pages": r["pages"], "files": sorted(r["files"]), "bytes": r["bytes"], "warnings": r["warnings"]}


def _deploy_pb(dir):
    from .site import deploy
    from .site.compiler import compile_site
    s = _site(dir)
    e = s.expanded()
    from .site.spec import validate
    validate(e, s.dir)
    return e, deploy.playbook(e, compile_site(e, base_dir=s.dir)["files"], static_dir=s.dir / (e.get("static") or "static"))


@command("site.plan", "Every Base call a deploy would make (secrets shown as placeholders). Makes no calls.", P("dir", default=".", positional=True))
def _site_plan(ctx, dir):
    from .playbook.template import Unknown
    e, pb = _deploy_pb(dir)
    pl = pb.plan({"secrets": Unknown("secrets")})
    for c in pl["calls"]:
        if c["tool"] == "site_write" and "content" in c.get("args", {}):
            c["args"]["content"] = f"<{len(c['args']['content'])} characters>"
    return pl


@command("site.deploy", "Deploy the site to the Base target: settings, modules, collections, models, plans, billing, files.", P("dir", default=".", positional=True),
         P("yes", "bool", "approve this deploy (needed when nobody can be asked)"), mutates=True)
def _site_deploy(ctx, dir, yes):
    from . import playbook
    from .site import deploy
    e, pb = _deploy_pb(dir)
    secrets = deploy.secrets_from_env(e)
    if yes:
        person_only(ctx, "approving a deploy (--yes)")
        playbook.approve(pb)
    h = ctx.harness()
    events = []
    for ev in pb.run(h, {"secrets": secrets}, resume=True, unattended=not ctx.interactive):
        events.append(ev)
        if ctx.surface == "cli" and ctx.interactive:
            ctx.out(_event_line(ev))
    last = events[-1] if events else {}
    if not last.get("ok"):
        raise JadeError("the deploy failed", "JADE202", data={"events": events})
    url = h.config.target("base").get("url", "")
    return {"ok": True, "url": e.get("url") or url, "calls": last.get("calls"), "run": last.get("run")}


@command("site.preview", "Build and serve the site on localhost (UI/UX from the CDN unless --ui).", P("dir", default=".", positional=True), P("port", "int", default=8080, help='the local port'),
         P("ui", help='a UI/UX module URL (to preview a local build)'), surfaces=("cli",))
def _site_preview(ctx, dir, port, ui):
    import functools
    import http.server
    r = _site_build(ctx, dir, "dist", ui, None)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r["out"])
    ctx.out(f"Serving {r['out']} at http://127.0.0.1:{port}/ (Ctrl-C to stop)")
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return {"stopped": True}


# ---- agent ----
@command("agent.ask", "Ask an agent: on Vault (its agent), or on Base (a model from config.models using Base's tools, through approvals).",
         P("message", required=True, positional=True), P("target", default="vault", choices=("vault", "base"), help='vault (its agent) or base (a model here with Base tools)'), P("name", default="jade", help='the agent session name'), P("steps", "int", default=8, help='at most this many tool rounds'), mutates=True)
def _agent_ask(ctx, message, target, name, steps):
    from .agent import Agent
    return Agent(ctx.harness(), name, target=target, max_steps=steps).ask(message)


# ---- docs ----
@command("docs.topics", "Documentation topics.")
def _docs_topics(ctx):
    from . import docs
    return docs.topics()


@command("docs.show", "A docs topic, or one section: topic#heading.", P("ref", required=True, positional=True))
def _docs_show(ctx, ref):
    from . import docs
    return docs.show(ref)


@command("docs.search", "Search the docs; each hit has a ref for docs.show.", P("query", required=True, positional=True), P("limit", "int", default=8, help='how many results'))
def _docs_search(ctx, query, limit):
    from . import docs
    return docs.search(query, limit)


@command("docs.build", "Build the docs: HTML for people, Markdown + llms.txt + catalog.json for agents.", P("out", default="docs", positional=True),
         P("format", default="both", choices=("html", "md", "both"), help='html, md or both'), P("check", "bool", "fail if the committed output is stale"), surfaces=("cli",))
def _docs_build(ctx, out, format, check):
    from .docsbuild import build
    return build(Path(out), format=format, check=check)


@command("commands", "Every command with its parameters (for agents).", P("name", positional=True))
def _commands(ctx, name):
    return describe(name)


def _maybe_harness(ctx):
    try:
        h = ctx.harness()
        return h if h.config.target("base") else None
    except JadeError:
        return None


@command("site.template.save", "Keep this site's design as a template (theme, pages, sections, backend) to reuse: new sites become name + tagline + template.",
         P("name", required=True, positional=True), P("dir", default=".", help="the site folder"), P("about", default="", help="one line describing it"),
         P("project", "bool", "save in ./templates (shared with the project) instead of your own templates"), mutates=True,
         example="jade site template save house --about 'Our look: ocean theme, pricing, account'")
def _site_template_save(ctx, name, dir, about, project):
    from .site.spec import save_template
    s = _site(dir)
    full = s.expanded()
    full.pop("template", None)
    p = save_template(full, name, about=about, where="project" if project else "user", base_dir=Path(dir))
    return {"template": name, "path": str(p), "use": f"template: {name}"}
