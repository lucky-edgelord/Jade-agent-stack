"""`jade init`: seven steps that end with a working jade.config.yaml, or no change at all. Plain prompts (no arrow-key
menus, no colour needed), resumable (~/.config/jade/init-state.json), headless with --yes, --json or --answers FILE.
Each step can be skipped (--skip-<step>) or run alone (--only=<step>). It ends with one honest sentence: what works now
and what does not."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import NAME, Config, find, secret_name
from .errors import JadeError
from .secrets import Store, config_dir

STEPS = ("environment", "targets", "auth", "models", "permissions", "smoke", "write")
CAPS = {  # question → approval patterns (never booleans)
    "base_read": ("Let it read Base (collections, records, logs)?", "y", {"base.read": ["*"]}),
    "base_write": ("Let it create and change records?", "n", {"base.write": ["record_*:*"]}),
    "base_schema": ("Let it create and change collections (root-equivalent)?", "n", {"base.schema": {"allow": ["collection_create:*", "collection_update:*"], "deny": ["collection_delete:*"]}}),
    "base_site": ("Let it publish the website (site files)?", "n", {"base.site": ["site_*"]}),
    "vault_chat": ("Let it chat with Vault's agent?", "y", {"vault.chat": ["*"], "vault.status": ["*"], "vault.flows": ["*"]}),
    "vault_flow": ("Let it run Vault flows (any)?", "n", {"vault.flow": ["*"]}),
    "shell": ("Let playbooks run read-only shell commands (ls, cat, grep, find, date, echo)?", "n", {"shell": {"allow": ["ls", "cat", "grep", "find", "date", "echo"], "deny": ["rm", "curl", "wget", "sudo", "dd"]}}),
}


def _state_file() -> Path:
    return config_dir() / "init-state.json"


class IO:
    def __init__(self, ns: Any, answers: dict):
        self.ns, self.answers = ns, answers
        self.headless = bool(ns.yes or ns.json or ns.answers or getattr(ns, "no_input", False) or not sys.stdin.isatty())
        self.color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.lines: list[str] = []

    def say(self, s: str) -> None:
        self.lines.append(s)
        if not self.ns.json:
            print(s, file=sys.stderr)

    def ask(self, key: str, q: str, default: str = "") -> str:
        if key in self.answers:
            return str(self.answers[key])
        if self.headless:
            return default
        print(f"{q}" + (f" [{default}]" if default else "") + ": ", end="", file=sys.stderr, flush=True)
        a = sys.stdin.readline().strip()
        return a or default

    def yes(self, key: str, q: str, default: str = "n") -> bool:
        return self.ask(key, q + (" (Y/n)" if default == "y" else " (y/N)"), default).lower().startswith("y")

    def secret(self, key: str, q: str) -> str:
        if key in self.answers:
            return str(self.answers[key])
        env = os.environ.get("JADE_INIT_" + key.upper())
        if env:
            return env
        if self.headless:
            return ""
        import getpass
        return getpass.getpass(q + ": ")


def run(ns: Any, ctx: Any) -> dict:
    answers = json.loads(Path(ns.answers).read_text()) if ns.answers else {}
    io = IO(ns, answers)
    st_path = _state_file()
    state = {} if ns.restart or not st_path.exists() else json.loads(st_path.read_text())
    if ns.base_url:
        answers.setdefault("base_url", ns.base_url)
    if ns.vault_url:
        answers.setdefault("vault_url", ns.vault_url)
    if ns.target:
        answers.setdefault("target", ns.target)
    path = Path(ctx.config) if ctx.config else (find() or Path.cwd() / NAME)
    old = Config.load(path) if path.exists() else Config()
    cfg = Config(old.data, path)
    snapshot = path.read_text() if path.exists() else None
    allow_file = bool(ctx.accept_file_secrets or ns.insecure_plaintext)
    store = Store(allow_file=allow_file)
    report: dict[str, Any] = {"steps": {}, "works": [], "missing": []}
    steps = [s for s in STEPS if not getattr(ns, f"skip_{s}", False) and (not ns.only or s == ns.only or s == "write")]

    def done(step: str, info: Any) -> None:
        state[step] = info
        report["steps"][step] = info
        st_path.parent.mkdir(parents=True, exist_ok=True)
        st_path.write_text(json.dumps(state, indent=1))

    # 1 environment
    if "environment" in steps:
        info = {"python": sys.version.split()[0], "keyring": store.backend, "tty": sys.stdin.isatty(), "color": io.color,
                "columns": shutil.get_terminal_size((80, 24)).columns}
        if store.backend == "none":
            io.say("No OS keyring here. Secrets will not be saved unless you pass --accept-file-secrets (a 0600 file), "
                   "or set JADE_SECRET_<NAME> variables. jade.config.yaml never holds secrets.")
        done("environment", info)

    # 2 targets
    if "targets" in steps:
        t = io.ask("target", "What should jade connect to? base, vault, both, or kit (a browser-only page with Ollama)", state.get("targets", {}).get("target", "base"))
        if t not in ("base", "vault", "both", "kit"):
            raise JadeError(f"target: base, vault, both or kit, not {t!r}", "JADE400")
        info: dict[str, Any] = {"target": t}
        if t in ("base", "both"):
            url = io.ask("base_url", "Jade Agent Base URL", cfg.get("targets.base.url") or "http://127.0.0.1:8090").rstrip("/")
            cfg.set("targets.base", {**cfg.target("base"), "url": url, "token": secret_name(url)})
            info["base"] = url
        if t in ("vault", "both"):
            url = io.ask("vault_url", "Jade Vault API URL (Vault: Settings → Connect → API endpoint)", cfg.get("targets.vault.url") or "http://127.0.0.1:8787").rstrip("/")
            cfg.set("targets.vault", {**cfg.target("vault"), "url": url, "token": secret_name(url)})
            info["vault"] = url
        if t == "kit":
            cfg.set("targets.kit", {"ollama": io.ask("ollama", "Ollama host for the page", "https://ollama.com"), "model": io.ask("kit_model", "Model", "gpt-oss:120b")})
        # verify right away (headless runs may skip with --skip-auth when the servers are not up yet)
        from . import http
        for name in ("base", "vault"):
            if not cfg.target(name):
                continue
            url = cfg.target(name)["url"]
            try:
                http.request("GET", url + ("/api/health" if name == "base" else "/v1/health"), timeout=8, retries=1)
                info[f"{name}_reachable"] = True
            except JadeError as e:
                info[f"{name}_reachable"] = False
                hint = "Is `jab serve` running?" if name == "base" else "Vault is reachable only when its HTTP API is on: on the phone, Settings → Connect → API endpoint."
                if not io.headless:
                    _restore(path, snapshot)
                    raise JadeError(f"{name} at {url}: {e.message}. {hint}", "JADE200") from None
                report["missing"].append(f"{name} unreachable ({hint})")
        done("targets", info)

    # 3 auth
    if "auth" in steps:
        info = {}
        h = None
        for name in ("base", "vault"):
            t = cfg.target(name)
            if not t:
                continue
            tok = io.secret(f"{name}_token", f"{name.title()} token (input hidden)")
            if tok:
                try:
                    store.set(t["token"], tok)
                except JadeError:
                    os.environ["JADE_SECRET_" + "".join(c if c.isalnum() else "_" for c in t["token"]).upper()] = tok
                    report["missing"].append(f"{name} token not saved (no keyring; use --accept-file-secrets or JADE_SECRET_…)")
            from .harness import Harness
            h = Harness(cfg, accept_legacy=ctx.accept_legacy, accept_file_secrets=allow_file)
            try:
                if name == "vault":
                    if h.vault.legacy_auth():
                        if not ctx.accept_legacy:
                            _restore(path, snapshot)
                            raise JadeError(f"{t['url']} accepts tokens in URLs. Update Jade Vault (2.18.3+), or for diagnosis only pass --accept-legacy", "JADE102")
                        io.say("WARNING: this Vault accepts ?token= in URLs. Continuing only because of --accept-legacy.")
                        info["vault_legacy"] = True
                    h.vault.status()
                else:
                    h.base.server_info()
                info[name] = "ok"
            except JadeError as e:
                if e.code == "JADE102":
                    raise
                info[name] = e.code
                report["missing"].append(f"{name}: {e.message}")
        done("auth", info)

    # 4 models
    if "models" in steps and cfg.target("base") or ("models" in steps and answers.get("models_provider")):
        prov = io.ask("models_provider", "Model provider for the Base agent: ollama, ollama-cloud, openai, or none", (cfg.get("models") or {}).get("provider", "none"))
        if prov != "none":
            url = io.ask("models_url", "Its URL", {"ollama": "http://127.0.0.1:11434", "ollama-cloud": "https://ollama.com", "openai": "https://api.openai.com"}.get(prov, ""))
            m = {"provider": prov, "url": url, "fast": io.ask("models_fast", "Fast model", "llama3.2:3b" if prov == "ollama" else "gpt-oss:20b"),
                 "strong": io.ask("models_strong", "Strong model", "gpt-oss:120b")}
            key = io.secret("models_key", "API key (input hidden; empty for none)")
            if key:
                m["key"] = secret_name(url)
                try:
                    store.set(m["key"], key)
                except JadeError:
                    report["missing"].append("model key not saved")
            cfg.set("models", m)
        done("models", {"provider": prov})

    # 5 permissions (default read-only)
    if "permissions" in steps:
        rules: dict[str, Any] = {}
        for k, (q, d, r) in CAPS.items():
            if (k.startswith("base") and not cfg.target("base")) or (k.startswith("vault") and not cfg.target("vault")):
                continue
            if io.yes(k, q, d):
                rules.update(r)
        cfg.set("approvals", rules)
        done("permissions", {"approvals": list(rules)})

    # 6 smoke test: one round trip, printed redacted
    if "smoke" in steps:
        from .harness import Harness
        h = Harness(cfg, accept_legacy=ctx.accept_legacy, accept_file_secrets=allow_file, yolo=True, warn=lambda m: None)
        info = {}
        if cfg.target("base"):
            try:
                si = h.base.server_info()
                info["base"] = {"request": "POST /api/agent/tools/server_info", "response": {"version": si.get("version"), "modules": si.get("modules"), "scopes": si.get("scopes")}}
                report["works"].append(f"Base {si.get('version')} ({', '.join(si.get('scopes') or [])})")
            except JadeError as e:
                info["base"] = {"error": e.code}
                report["missing"].append(f"Base round trip: {e.message}")
        if cfg.target("vault"):
            try:
                r = h.vault.chat("Reply with the single word: ready", timeout=60)
                info["vault"] = {"request": "GET /v1/chat?message=…", "response": str(r)[:120]}
                report["works"].append("Vault chat")
            except JadeError as e:
                info["vault"] = {"error": e.code}
                report["missing"].append(f"Vault round trip: {e.message}")
        io.say(json.dumps(info, indent=1))
        if report["missing"] and not io.headless and not io.yes("keep_anyway", "The smoke test failed. Save the configuration anyway?", "n"):
            _restore(path, snapshot)
            raise JadeError("nothing was changed: " + "; ".join(report["missing"]), "JADE200")
        done("smoke", info)

    # 7 write
    p = cfg.save(path)
    Config.load(p)  # it must load back
    done("write", {"path": str(p)})
    works = ", ".join(report["works"]) or "the configuration file"
    missing = "; ".join(report["missing"])
    sentence = f"Works now: {works}." + (f" Not yet: {missing}." if missing else " Nothing is missing.") + " Next: jade doctor"
    io.say(sentence)
    return {"config": str(p), "works": report["works"], "missing": report["missing"], "summary": sentence, "steps": list(report["steps"])}


def _restore(path: Path, snapshot: str | None) -> None:
    """never leave a broken configuration: put back what was there"""
    if snapshot is None:
        return
    path.write_text(snapshot)
