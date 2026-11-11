"""The documentation browser: the Markdown docs that ship inside the package, for agents (and people in a terminal).

    jade.docs.topics()                 → [{"topic", "title", "summary"}]
    jade.docs.show("playbooks#targets") → the text of one topic, or one section of it
    jade.docs.search("idempotency")    → [{"ref", "title", "snippet", "score"}]

The same pages are the source of the HTML site (docs/ on GitHub Pages) and of llms.txt."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import yaml

from .errors import JadeError
from .site.markdown import slug

DIR = Path(__file__).with_name("docs")
WORD = re.compile(r"[a-z0-9_]+")


def _split(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            return yaml.safe_load(text[4:end]) or {}, text[end + 5:]
    return {}, text


@lru_cache(maxsize=1)
def _pages() -> dict[str, dict]:
    out = {}
    for p in sorted(DIR.glob("*.md")):
        meta, body = _split(p.read_text())
        out[p.stem] = {"topic": p.stem, "meta": meta, "body": body, "sections": _sections(body)}
    for name, (meta, body) in generated().items():
        out[name] = {"topic": name, "meta": meta, "body": body, "sections": _sections(body)}
    return out


def _cell(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def generated() -> dict[str, tuple[dict, str]]:
    """reference pages made from the code itself, so they cannot drift: commands, errors, sections, themes, schema"""
    import json as _json

    from . import commands, compat, errors
    from .playbook.engine import SCHEMA
    from .site import sections, themes
    m = lambda title, summary, order: {"title": title, "summary": summary, "applies_to": "stack", "audience": "both", "since": "0.1.0", "order": order, "generated": True}
    cmd = ["# Commands", "", "Every command, on every surface (CLI `jade a b`, REPL `a b`, JSON lines `a.b`, MCP `a_b`, HTTP `POST /v1/commands/a.b`).", ""]
    for c in commands.REGISTRY.values():
        cmd += [f"## {c.name}", "", c.help, "", f"`jade {c.name.replace('.', ' ')}`" + (" (CLI only)" if c.surfaces == ("cli",) else ""), ""]
        if c.params:
            cmd += ["| Parameter | Type | Default | Meaning |", "| --- | --- | --- | --- |"]
            cmd += [f"| `{p.name}`{' (positional)' if p.positional else ''}{' required' if p.required else ''} | {p.type}{' (' + ', '.join(map(str, p.choices)) + ')' if p.choices else ''} | "
                    f"{'' if p.default in (None, False, '', []) else '`' + _cell(p.default) + '`'} | {_cell(p.help)} |" for p in c.params]
            cmd.append("")
        if c.example:
            cmd += ["```sh", c.example, "```", ""]
    err = ["# Errors", "", "Stable codes. `str(error)` gives the message and the remediation. Exit codes: 0 ok, 1 user error, 2 remote error, 3 refused for safety.", "",
           "| Code | Meaning | Exit | Remediation |", "| --- | --- | --- | --- |"]
    for code, (meaning, fix) in errors.CODES.items():
        err.append(f"| `{code}` | {meaning} | {errors.JadeError('', code).exit_code} | {_cell(fix)} |")
    sec = ["# Sections", "", "The building blocks of a page. In a spec: `- hero` or `- {type: hero, title: …}`. Every section also takes `id` and `class`.", ""]
    for s in sections.REGISTRY.values():
        sec += [f"## {s.name}", "", s.doc, ""]
        if s.params:
            sec += ["| Parameter | Type | Default | Meaning |", "| --- | --- | --- | --- |"]
            sec += [f"| `{k}`{' required' if p.required else ''} | {p.type} | {'' if p.default in (None, [], {}) else '`' + _cell(_json.dumps(p.default)) + '`'} | {_cell(p.doc)} |" for k, p in s.params.items()]
            sec.append("")
        if s.needs:
            sec += [f"Needs the backend modules: {', '.join(s.needs)}.", ""]
        if s.example:
            sec += ["```yaml", "- " + _json.dumps(s.example), "```", ""]
    th = ["# Themes", "", "| Theme | Font | Description |", "| --- | --- | --- |"]
    for n in themes.names():
        t = themes.get(n)
        th.append(f"| `{n}` | {t['font']} | {_cell(t['description'])} |")
    sch = ["# Playbook schema", "", "`apiVersion: jade/v1`, `kind: Playbook`. Unknown keys are errors. The file is `schema/playbook.v1.json`.", "",
           "```json", _json.dumps(SCHEMA, indent=1), "```"]
    st = ["# Stack versions", "", f"Jade Agent Stack {compat.TOOLKIT} works with:", "", "| Repository | Minimum | Interface |", "| --- | --- | --- |"]
    st += [f"| {repo} (`{v[1]}`) | {v[0]} | {v[2]} |" for repo, v in compat.REQUIRES.items()]
    st += ["", "Major mismatch: refused. Older minor: a warning. Pages load:", ""] + [f"- {k}: `{u}`" for k, u in compat.CDN.items()]
    return {"commands": (m("Commands", "Every command and its parameters, generated from the code.", 90), "\n".join(cmd)),
            "errors": (m("Errors", "Every error code, its meaning, exit code and remediation.", 91), "\n".join(err)),
            "sections": (m("Section reference", "Every page section and its parameters.", 92), "\n".join(sec)),
            "themes": (m("Themes", "The themes for sites and pages.", 93), "\n".join(th)),
            "playbook-schema": (m("Playbook schema", "The JSON Schema of playbooks.", 94), "\n".join(sch)),
            "versions": (m("Stack versions", "Which versions of the four repositories this toolkit works with.", 95), "\n".join(st))}


def _sections(body: str) -> list[dict]:
    secs, cur = [], {"id": "", "title": "", "level": 1, "lines": []}
    fence = False
    for line in body.splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"(#{1,4})\s+(.*)", line)
        if m:
            secs.append(cur)
            cur = {"id": slug(m.group(2)), "title": m.group(2).strip(), "level": len(m.group(1)), "lines": [line]}
        else:
            cur["lines"].append(line)
    secs.append(cur)
    return [{**s, "text": "\n".join(s["lines"]).strip()} for s in secs if s["lines"] and "\n".join(s["lines"]).strip()]


def topics() -> list[dict]:
    order = {"start": 0, "agents": 1}
    pages = sorted(_pages().values(), key=lambda p: (order.get(p["topic"], 5), p["meta"].get("order", 50), p["topic"]))
    return [{"topic": p["topic"], "title": p["meta"].get("title", p["topic"]), "summary": p["meta"].get("summary", ""),
             "applies_to": p["meta"].get("applies_to", "stack"), "audience": p["meta"].get("audience", "both")} for p in pages]


def headings(topic: str) -> list[dict]:
    p = _get(topic)
    return [{"ref": f"{topic}#{s['id']}", "title": s["title"], "level": s["level"]} for s in p["sections"] if s["id"]]


def _get(topic: str) -> dict:
    p = _pages().get(topic)
    if not p:
        close = [t for t in _pages() if topic.lower() in t or t in topic.lower()]
        raise JadeError(f"no docs topic {topic!r}" + (f" (did you mean {', '.join(close)}?)" if close else f" (topics: {', '.join(_pages())})"), "JADE405")
    return p


def show(ref: str) -> str:
    """'topic' → the page; 'topic#heading' → that section with its subsections"""
    topic, _, sec = ref.partition("#")
    p = _get(topic.strip())
    if not sec:
        return p["body"].strip()
    sid = slug(sec)
    for i, s in enumerate(p["sections"]):
        if s["id"] == sid or s["title"].lower() == sec.lower():
            out = [s["text"]]
            for t in p["sections"][i + 1:]:
                if t["level"] <= s["level"]:
                    break
                out.append(t["text"])
            return "\n\n".join(out)
    raise JadeError(f"{topic} has no section {sec!r} (sections: {', '.join(h['ref'].split('#')[1] for h in headings(topic))})", "JADE405")


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict], dict[str, int]]:
    docs, df = [], {}
    for p in _pages().values():
        for s in p["sections"]:
            words = WORD.findall((s["title"] + " ") * 3 + s["text"].lower())
            tf: dict[str, int] = {}
            for w in words:
                tf[w] = tf.get(w, 0) + 1
            docs.append({"ref": f"{p['topic']}#{s['id']}" if s["id"] else p["topic"], "title": s["title"] or p["meta"].get("title", p["topic"]),
                         "text": s["text"], "tf": tf, "len": len(words)})
            for w in tf:
                df[w] = df.get(w, 0) + 1
    return docs, df


def search(query: str, limit: int = 8) -> list[dict]:
    """sections ranked by BM25, each with a snippet around the first match"""
    docs, df = _index()
    terms = WORD.findall(query.lower())
    if not terms:
        return []
    n = len(docs)
    avg = sum(d["len"] for d in docs) / max(1, n)
    scored = []
    for d in docs:
        s = 0.0
        for t in terms:
            f = d["tf"].get(t, 0) + sum(v for k, v in d["tf"].items() if len(t) > 3 and k.startswith(t) and k != t) * 0.5
            if f:
                idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * d["len"] / avg))
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [{"ref": d["ref"], "title": d["title"], "score": round(s, 2), "snippet": _snippet(d["text"], terms)} for s, d in scored[:limit]]


def _snippet(text: str, terms: list[str], width: int = 180) -> str:
    plain = re.sub(r"\s+", " ", re.sub(r"[#`*|>]", "", text)).strip()
    low = plain.lower()
    pos = min([i for i in (low.find(t) for t in terms) if i >= 0] or [0])
    start = max(0, pos - width // 3)
    s = plain[start:start + width]
    return ("…" if start else "") + s + ("…" if start + width < len(plain) else "")


def all_pages() -> dict[str, dict]:
    """for the docs build: topic → {meta, body}"""
    return {k: {"meta": v["meta"], "body": v["body"]} for k, v in _pages().items()}
