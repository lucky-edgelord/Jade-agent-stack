"""The playbook expression language: a small, documented subset of Jinja. No attribute calls, no imports, no I/O.

    {{ name }}  {{ created.result.id }}  {{ items.0 }}  {{ "text" }}  {{ 3 }}  {{ true }}
    {{ x | default("y") }}  | lower | upper | json | length | string | int | trim
    {{ a == b }}  !=  <  <=  >  >=  and  or  not  ( … )  in

{% raw %} … {% endraw %} keeps its text as it is (for content that contains braces, like a web page).
A string that is a single {{ … }} gives the value itself (a dict stays a dict); otherwise the parts are joined as text.
An unknown name is an error, unless | default() is used."""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import PlaybookError

EXPR = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.S)
RAW = re.compile(r"\{%\s*raw\s*%\}(.*?)\{%\s*endraw\s*%\}", re.S)


def raw(text: str) -> str:
    """wrap text so it is never templated"""
    if "{{" not in text and "{%" not in text:
        return text
    return "".join("{% raw %}" + part + "{% endraw %}" if part else "" for part in text.split("{% endraw %}")).replace("{% endraw %}{% raw %}", "{% endraw %}{{ '{% endraw %}' }}{% raw %}") if "{% endraw %}" in text else "{% raw %}" + text + "{% endraw %}"
TOKEN = re.compile(r'\s*(?:(\d+\.\d+|\d+)|("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|(==|!=|<=|>=|<|>|\(|\)|\||,)|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*))')
FILTERS = {
    "lower": lambda v: str(v).lower(), "upper": lambda v: str(v).upper(), "trim": lambda v: str(v).strip(),
    "json": lambda v: json.dumps(v, sort_keys=True), "length": lambda v: len(v), "string": lambda v: "" if v is None else str(v),
    "int": lambda v: int(float(v)),
}


class Missing:
    def __init__(self, name: str):
        self.name = name


class Unknown:
    """a value that is not known until the playbook runs (used by plan)"""

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return f"<{self.text}>"


def tokens(s: str) -> list[tuple[str, Any]]:
    out, i = [], 0
    while i < len(s):
        if s[i:].strip() == "":
            break
        m = TOKEN.match(s, i)
        if not m or m.end() == i:
            raise PlaybookError(f"cannot read {s!r} at {s[i:i + 12]!r}")
        num, st, op, name = m.groups()
        if num is not None:
            out.append(("v", float(num) if "." in num else int(num)))
        elif st is not None:
            out.append(("v", json.loads('"' + st[1:-1].replace('\\"', '"').replace('"', '\\"') + '"') if st[0] == "'" else json.loads(st)))
        elif op is not None:
            out.append(("op", op))
        elif name in ("and", "or", "not", "in"):
            out.append(("op", name))
        elif name in ("true", "True"):
            out.append(("v", True))
        elif name in ("false", "False"):
            out.append(("v", False))
        elif name in ("none", "None", "null"):
            out.append(("v", None))
        else:
            out.append(("name", name))
        i = m.end()
    return out


def lookup(ctx: dict, name: str) -> Any:
    v: Any = ctx
    for k in name.split("."):
        if isinstance(v, Unknown):
            return Unknown(name)
        if isinstance(v, dict) and k in v:
            v = v[k]
        elif isinstance(v, list) and k.isdigit() and int(k) < len(v):
            v = v[int(k)]
        else:
            return Missing(name)
    return v


class Parser:
    def __init__(self, toks: list, ctx: dict, src: str):
        self.t, self.i, self.ctx, self.src = toks, 0, ctx, src

    def peek(self) -> tuple[str, Any] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, op: str | None = None) -> tuple[str, Any]:
        tk = self.peek()
        if tk is None or (op and tk != ("op", op)):
            raise PlaybookError(f"in {{{{ {self.src} }}}}: expected {op or 'more'}")
        self.i += 1
        return tk

    def done(self, v: Any) -> Any:
        if self.peek() is not None:
            raise PlaybookError(f"in {{{{ {self.src} }}}}: unexpected {self.peek()[1]!r}")  # type: ignore[index]
        if isinstance(v, Missing):
            raise PlaybookError(f"{{{{ {self.src} }}}}: {v.name!r} is not defined (vars, registered results, or | default(…))")
        return v

    def expr(self) -> Any:
        v = self.and_()
        while self.peek() == ("op", "or"):
            self.take()
            r = self.and_()
            v = Unknown(self.src) if isinstance(v, Unknown) or isinstance(r, Unknown) else (self.val(v) or self.val(r))
        return v

    def and_(self) -> Any:
        v = self.not_()
        while self.peek() == ("op", "and"):
            self.take()
            r = self.not_()
            v = Unknown(self.src) if isinstance(v, Unknown) or isinstance(r, Unknown) else (self.val(v) and self.val(r))
        return v

    def not_(self) -> Any:
        if self.peek() == ("op", "not"):
            self.take()
            v = self.not_()
            return v if isinstance(v, Unknown) else not self.val(v)
        return self.cmp()

    def cmp(self) -> Any:
        v = self.filt()
        tk = self.peek()
        if tk and tk[0] == "op" and tk[1] in ("==", "!=", "<", "<=", ">", ">=", "in"):
            self.take()
            r = self.filt()
            if isinstance(v, Unknown) or isinstance(r, Unknown):
                return Unknown(self.src)
            a, b = self.val(v), self.val(r)
            try:
                return {"==": lambda: a == b, "!=": lambda: a != b, "<": lambda: a < b, "<=": lambda: a <= b, ">": lambda: a > b,
                        ">=": lambda: a >= b, "in": lambda: a in b}[tk[1]]()
            except TypeError as e:
                raise PlaybookError(f"{{{{ {self.src} }}}}: {e}") from None
        return v

    def filt(self) -> Any:
        v = self.atom()
        while self.peek() == ("op", "|"):
            self.take()
            kind, name = self.take()
            if kind != "name":
                raise PlaybookError(f"in {{{{ {self.src} }}}}: a filter name after |")
            if name == "default":
                self.take("(")
                d = self.expr()
                self.take(")")
                if isinstance(v, Missing) or v is None:
                    v = d
                continue
            if name not in FILTERS:
                raise PlaybookError(f"{{{{ {self.src} }}}}: unknown filter {name!r} (filters: default, {', '.join(FILTERS)})")
            if not isinstance(v, Unknown):
                try:
                    v = FILTERS[name](self.val(v))
                except (TypeError, ValueError) as e:
                    raise PlaybookError(f"{{{{ {self.src} }}}}: {name}: {e}") from None
        return v

    def atom(self) -> Any:
        kind, v = self.take()
        if kind == "v":
            return v
        if kind == "name":
            return lookup(self.ctx, v)
        if v == "(":
            x = self.expr()
            self.take(")")
            return x
        raise PlaybookError(f"in {{{{ {self.src} }}}}: unexpected {v!r}")

    def val(self, v: Any) -> Any:
        if isinstance(v, Missing):
            raise PlaybookError(f"{{{{ {self.src} }}}}: {v.name!r} is not defined (vars, registered results, or | default(…))")
        return v


def evaluate(src: str, ctx: dict) -> Any:
    p = Parser(tokens(src), ctx, src)
    return p.done(p.expr())


def _text(s: str, ctx: dict) -> str:
    def one(m: re.Match) -> str:
        x = evaluate(m.group(1), ctx)
        return f"<{x.text}>" if isinstance(x, Unknown) else ("" if x is None else (json.dumps(x) if isinstance(x, (dict, list)) else str(x)))
    return EXPR.sub(one, s)


def render(v: Any, ctx: dict) -> Any:
    """render every {{ }} in a value (strings, lists, dicts)"""
    if isinstance(v, str):
        if "{%" in v:
            parts, last = [], 0
            for m in RAW.finditer(v):
                parts.append(_text(v[last:m.start()], ctx))
                parts.append(m.group(1))
                last = m.end()
            if last:
                return "".join(parts) + _text(v[last:], ctx)
        m = EXPR.fullmatch(v.strip())
        if m and v.count("{{") == 1:
            return evaluate(m.group(1), ctx)
        return _text(v, ctx)
    if isinstance(v, list):
        return [render(x, ctx) for x in v]
    if isinstance(v, dict):
        return {k: render(x, ctx) for k, x in v.items()}
    return v


def names(v: Any) -> set[str]:
    """the top-level names a value's expressions use (for check)"""
    out: set[str] = set()
    if isinstance(v, str):
        v = RAW.sub("", v)
        for m in EXPR.finditer(v):
            prev = None
            for kind, x in tokens(m.group(1)):
                if kind == "name" and prev != ("op", "|"):
                    out.add(x.split(".")[0])
                prev = (kind, x)
    elif isinstance(v, list):
        for x in v:
            out |= names(x)
    elif isinstance(v, dict):
        for x in v.values():
            out |= names(x)
    return out
