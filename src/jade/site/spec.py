"""The site spec (jade.site.yaml) and the Site builder. A template fills in pages and backend defaults, so a spec can be
three lines:

    name: Acme AI
    tagline: Embeddings for every app.
    template: saas
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..errors import SiteError
from . import sections, themes

SPEC_NAME = "jade.site.yaml"
TEMPLATES_DIR = Path(__file__).with_name("templates")
TOP = {"name", "tagline", "description", "theme", "template", "url", "lang", "logo", "favicon", "cdn", "backend", "pages", "head", "static"}
BACKEND = {"url", "modules", "rate_limits", "auth", "collections", "providers", "models", "plans", "billing"}
RULES = {"anyone": "", "users": '@request.auth.id != ""', "owner": "@request.auth.id = user", "admin": None}
FIELD_TYPES = {"text", "email", "url", "number", "bool", "date", "json", "editor", "select", "file", "relation", "textarea", "checkbox"}


def template_dirs() -> list[Path]:
    """where templates come from, first wins: ./templates, your own (~/.config/jade/templates), then the built-in ones"""
    from ..secrets import config_dir
    return [Path.cwd() / "templates", config_dir() / "templates", TEMPLATES_DIR]


def templates() -> dict[str, str]:
    """template name → its one-line description (yours first, then the built-in ones)"""
    out: dict[str, str] = {}
    for d in template_dirs():
        for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
            if p.stem in out:
                continue
            try:
                t = yaml.safe_load(p.read_text()) or {}
            except yaml.YAMLError:
                continue
            out[p.stem] = (t.get("about", "") + ("" if d == TEMPLATES_DIR else f" ({'project' if d.name == 'templates' and d.parent == Path.cwd() else 'yours'})")).strip()
    return out


def template(name: str, base_dir: Path | None = None) -> dict:
    """a template by name, or by path (./brand/site.yaml), relative to the spec"""
    if name.endswith((".yaml", ".yml")) or "/" in name:
        p = (base_dir or Path.cwd()) / name
    else:
        p = next((d / f"{name}.yaml" for d in template_dirs() if (d / f"{name}.yaml").exists()), TEMPLATES_DIR / f"{name}.yaml")
    if not p.exists():
        raise SiteError(f"unknown template {name!r} (templates: {', '.join(templates())})")
    d = yaml.safe_load(p.read_text()) or {}
    d.pop("about", None)
    if d.get("template"):  # a template may build on another
        parent = d.pop("template")
        d = expand({**{"name": "_"}, **d, "template": parent}, base_dir=p.parent)
        d.pop("name", None)
        d.pop("template", None)
    return d


def save_template(spec: dict, name: str, *, about: str = "", where: str = "user", base_dir: Path | None = None) -> Path:
    """keep a settled design: the spec minus what is particular to one site (name, tagline, url, description)"""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise SiteError("a template name: lower-case letters, digits, - and _")
    from ..secrets import config_dir
    d = (base_dir or Path.cwd()) / "templates" if where == "project" else config_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    t = {k: v for k, v in spec.items() if k not in ("name", "tagline", "url", "description", "logo", "favicon")}
    t = {"about": about or f"Saved from {spec.get('name', 'a site')}", **t}
    p = d / f"{name}.yaml"
    p.write_text(yaml.safe_dump(t, sort_keys=False, allow_unicode=True))
    return p


def merge_named(a: list, b: list, key: str = "name") -> list:
    out = [copy.deepcopy(x) for x in a or []]
    for x in b or []:
        k = x.get(key) if isinstance(x, dict) else None
        for i, y in enumerate(out):
            if k is not None and isinstance(y, dict) and y.get(key) == k:
                out[i] = {**y, **x}
                break
        else:
            out.append(copy.deepcopy(x))
    return out


def expand(spec: dict, base_dir: Path | None = None) -> dict:
    """apply the template, normalise pages and sections"""
    s = copy.deepcopy(spec)
    if s.get("template"):
        t = template(s["template"], base_dir)
        s["pages"] = merge_named(t.get("pages", []), s.get("pages", []), "path")
        tb, sb = t.get("backend") or {}, s.get("backend") or {}
        b = {**tb, **{k: v for k, v in sb.items() if not isinstance(v, list)}}
        for k in ("collections", "providers", "models", "plans"):
            if k in tb or k in sb:
                b[k] = merge_named(tb.get(k, []), sb.get(k, []))
        if "modules" in tb or "modules" in sb:
            b["modules"] = list(dict.fromkeys((tb.get("modules") or []) + (sb.get("modules") or [])))
        if b:
            s["backend"] = b
        for k, v in t.items():
            if k not in ("pages", "backend"):
                s.setdefault(k, v)
    s.setdefault("pages", [{"path": "/", "title": "Home", "sections": ["nav", "hero", "footer"]}])
    for p in s["pages"]:
        p["path"] = "/" + str(p.get("path", "/")).strip("/") if str(p.get("path", "/")).strip("/") else "/"
        p["sections"] = [{"type": x} if isinstance(x, str) else x for x in p.get("sections") or []]
    return s


def validate(s: dict, base_dir: Path | None = None) -> list[str]:
    """→ warnings; raises SiteError for what cannot be built"""
    warn: list[str] = []
    bad = set(s) - TOP
    if bad:
        raise SiteError(f"unknown key(s) {', '.join(sorted(bad))} (keys: {', '.join(sorted(TOP))})")
    if not s.get("name"):
        raise SiteError("name is required")
    th = s.get("theme") or "jade"
    tn = th.get("name", "jade") if isinstance(th, dict) else th
    if tn not in themes.names():
        raise SiteError(f"theme {tn!r} is not one of {', '.join(themes.names())}")
    b = s.get("backend") or {}
    bad = set(b) - BACKEND
    if bad:
        raise SiteError(f"backend: unknown key(s) {', '.join(sorted(bad))} (keys: {', '.join(sorted(BACKEND))})")
    for c in b.get("collections") or []:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(c.get("name", ""))):
            raise SiteError(f"backend.collections: a name of letters, digits and _, not {c.get('name')!r}")
        for f in fields(c):
            if f["type"] not in FIELD_TYPES:
                raise SiteError(f"backend.collections.{c['name']}: field {f['name']}: type {f['type']!r} (types: {', '.join(sorted(FIELD_TYPES))})")
        for r in ("list", "view", "create", "update", "delete"):
            v = c.get(r)
            if isinstance(v, str) and v in RULES:
                continue
            if v is not None and not isinstance(v, str):
                raise SiteError(f"backend.collections.{c['name']}.{r}: anyone, users, owner, admin, or a PocketBase rule")
    for k in ("providers",):
        for p in b.get(k) or []:
            if p.get("api_key"):
                raise SiteError(f"backend.{k}.{p.get('name')}: put the key in an environment variable and name it with api_key_env")
    if (b.get("billing") or {}).get("secret_key"):
        raise SiteError("backend.billing: name the environment variable with secret_key_env; never the key itself")
    for pv in (b.get("auth") or {}).get("providers") or []:
        if pv.get("client_secret"):
            raise SiteError(f"backend.auth.providers.{pv.get('name')}: use client_secret_env, never the secret itself")
    paths = set()
    for p in s.get("pages") or []:
        if p["path"] in paths:
            raise SiteError(f"two pages at {p['path']}")
        paths.add(p["path"])
        for i, sec in enumerate(p["sections"]):
            ty = sec.get("type")
            if ty not in sections.REGISTRY:
                raise SiteError(f"page {p['path']}: section {i}: unknown type {ty!r} (sections: {', '.join(sections.REGISTRY)})")
            known = set(sections.REGISTRY[ty].params) | {"type", "id", "class"}
            unk = set(sec) - known
            if unk:
                raise SiteError(f"page {p['path']}: {ty}: unknown parameter(s) {', '.join(sorted(unk))} (parameters: {', '.join(sorted(known))})")
            for k, prm in sections.REGISTRY[ty].params.items():
                if prm.required and sec.get(k) in (None, "", []) and not (ty == "markdown"):
                    warn.append(f"page {p['path']}: {ty}: {k} is empty")
            if ty == "markdown" and sec.get("file") and base_dir and not (base_dir / sec["file"]).exists():
                raise SiteError(f"page {p['path']}: markdown file {sec['file']} not found")
            if ty in ("form", "records") and sec.get("collection") and sec["collection"] not in {c.get("name") for c in b.get("collections") or []}:
                warn.append(f"page {p['path']}: {ty}: collection {sec['collection']!r} is not in backend.collections (it must exist on the server)")
    return warn


def fields(c: dict) -> list[dict]:
    f = c.get("fields") or []
    if isinstance(f, str):
        f = [x.strip() for x in f.split(",") if x.strip()]
    return [sections.parse_field(x) for x in f]


class Site:
    """build a site in code:

        site = Site("Acme AI", tagline="Embeddings for every app.", theme="ocean")
        site.page("/", "Home").add("nav").add("hero").add("pricing").add("footer")
        site.collection("waitlist", "email:email!", create="anyone")
        site.build("dist")
    """

    def __init__(self, name: str = "", **kw: Any):
        self.spec: dict = {"name": name, **kw} if name else dict(kw)
        self.dir = Path(kw.pop("base_dir", None) or os.getcwd())

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Site":
        p = Path(path or SPEC_NAME)
        if p.is_dir():
            p = p / SPEC_NAME
        if not p.exists():
            raise SiteError(f"no {p} (make one: jade site new)", "JADE405")
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as e:
            raise SiteError(f"{p}: not valid YAML: {e}") from None
        s = cls(**data)
        s.dir = p.parent.resolve()
        s.path = p
        return s

    def page(self, path: str, title: str = "", **kw: Any) -> "Page":
        pages = self.spec.setdefault("pages", [])
        for p in pages:
            if p.get("path") == path:
                p.update({"title": title or p.get("title"), **kw})
                return Page(p)
        p = {"path": path, "title": title, "sections": [], **kw}
        pages.append(p)
        return Page(p)

    def collection(self, name: str, fields: str | list, **rules: str) -> "Site":
        b = self.spec.setdefault("backend", {})
        b["collections"] = merge_named(b.get("collections", []), [{"name": name, "fields": fields, **rules}])
        return self

    def backend(self, **kw: Any) -> "Site":
        self.spec.setdefault("backend", {}).update(kw)
        return self

    def expanded(self) -> dict:
        return expand(self.spec, self.dir)

    def check(self) -> dict:
        s = self.expanded()
        w = validate(s, self.dir)
        from .compiler import compile_site
        out = compile_site(s, base_dir=self.dir, write=None)
        return {"ok": True, "pages": [p["path"] for p in s["pages"]], "warnings": w + out["warnings"]}

    def build(self, out: str | os.PathLike = "dist", **kw: Any) -> dict:
        from .compiler import compile_site
        s = self.expanded()
        w = validate(s, self.dir)
        r = compile_site(s, base_dir=self.dir, write=Path(out), **kw)
        r["warnings"] = w + r["warnings"]
        return r

    def save(self, path: str | os.PathLike = SPEC_NAME) -> Path:
        p = Path(path)
        p.write_text(yaml.safe_dump(self.spec, sort_keys=False, allow_unicode=True))
        return p


class Page:
    def __init__(self, p: dict):
        self.p = p

    def add(self, type: str, **params: Any) -> "Page":
        if type not in sections.REGISTRY:
            raise SiteError(f"unknown section {type!r} (sections: {', '.join(sections.REGISTRY)})")
        self.p["sections"].append({"type": type, **params})
        return self
