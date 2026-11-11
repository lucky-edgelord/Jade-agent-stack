"""A small, safe Markdown renderer (headings with ids, paragraphs, lists, task lists, quotes, fenced code, tables,
links, images, bold, italic, code). Every character of the source is escaped; only the tags below are made, links are
http(s), mailto, # or relative paths, images https, relative or data:image."""

from __future__ import annotations

import html
import re

_esc = lambda s: html.escape(s, quote=True)


def _safe_href(u: str) -> str | None:
    u = u.strip()
    if re.match(r"^(https?://|mailto:|#|/|\./|\.\./)", u, re.I) or re.match(r"^[\w\-./]+(#[\w\-]*)?$", u):
        return None if re.match(r"^\s*(javascript|data|vbscript):", u, re.I) else u
    return None


def _safe_src(u: str) -> str | None:
    u = u.strip()
    if re.match(r"^(https://|/|\./|data:image/(png|jpe?g|gif|webp|svg\+xml);base64,)", u, re.I) or re.match(r"^[\w\-./]+$", u):
        return u
    return None


def slug(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s).lower()
    return re.sub(r"[^\w]+", "-", s).strip("-") or "section"


def inline(src: str) -> str:
    keep: list[str] = []

    def put(h: str) -> str:
        keep.append(h)
        return f"\x00{len(keep) - 1}\x00"

    s = re.sub(r"(`+)(.+?)\1", lambda m: put(f"<code>{_esc(m.group(2).strip())}</code>"), src)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~|>])", lambda m: put(_esc(m.group(1))), s)
    s = _esc(s)

    def img(m):
        url = _safe_src(html.unescape(m.group(2)))
        return put(f'<img src="{_esc(url)}" alt="{m.group(1)}" loading="lazy">') if url else m.group(1)

    def link(m):
        url = _safe_href(html.unescape(m.group(2)))
        if not url:
            return m.group(1)
        ext = ' target="_blank" rel="noopener noreferrer"' if url.startswith("http") else ""
        return put(f'<a href="{_esc(url)}"{ext}>') + m.group(1) + put("</a>")

    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*?&quot;)?\)", img, s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*?&quot;)?\)", link, s)

    def auto(m):
        raw = m.group(2)
        u = re.split(r"&quot;|&#x27;|&lt;|&gt;", raw)[0].rstrip(".,;:!?)]")
        if len(u) < 9:
            return m.group(0)
        return m.group(1) + put(f'<a href="{u}" target="_blank" rel="noopener noreferrer">') + u + put("</a>") + raw[len(u):]

    s = re.sub(r"(^|\s)(https?://[^\s<]+)", auto, s)
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", s)
    s = re.sub(r"(^|[^*\w])\*(?=\S)([^*]*?\S)\*(?!\*)", lambda m: f"{m.group(1)}<em>{m.group(2)}</em>", s)
    s = re.sub(r"(^|\W)_(?=\S)([^_]*?\S)_(?!\w)", lambda m: f"{m.group(1)}<em>{m.group(2)}</em>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", s)
    for _ in range(2):
        s = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], s)
    return s


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)")
_LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HR = re.compile(r"^ {0,3}([-*_])( *\1){2,} *$")


def _start(l: str) -> bool:
    return bool(_FENCE.match(l) or re.match(r"^ {0,3}#{1,6}\s", l) or re.match(r"^ {0,3}>", l) or _LIST.match(l) or _HR.match(l))


def _cells(l: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", l.strip().strip("|"))]


def _blocks(lines: list[str], ids: set) -> str:
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        m = _FENCE.match(l)
        if m:
            close = re.compile(rf"^ {{0,3}}{re.escape(m.group(1)[0])}{{{len(m.group(1))},}}\s*$")
            body, i = [], i + 1
            while i < len(lines) and not close.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            lang = m.group(2).lower()
            out.append(f'<pre data-lang="{_esc(lang)}"><code>{_esc(chr(10).join(body))}</code></pre>')
            continue
        m = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", l)
        if m:
            n, text = len(m.group(1)), inline(m.group(2))
            hid = slug(text)
            base, k = hid, 2
            while hid in ids:
                hid, k = f"{base}-{k}", k + 1
            ids.add(hid)
            out.append(f'<h{n} id="{hid}">{text}</h{n}>')
            i += 1
            continue
        if _HR.match(l):
            out.append("<hr>")
            i += 1
            continue
        if re.match(r"^ {0,3}>", l):
            q = []
            while i < len(lines) and lines[i].strip() and re.match(r"^ {0,3}>", lines[i]):
                q.append(re.sub(r"^ {0,3}> ?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{_blocks(q, ids)}</blockquote>")
            continue
        if "|" in l and i + 1 < len(lines) and _TSEP.match(lines[i + 1]):
            head = _cells(l)
            al = ["center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "" for c in _cells(lines[i + 1])]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            def td(t, c, k):
                st = ' style="text-align:' + al[k] + '"' if k < len(al) and al[k] else ""
                return f"<{t}{st}>{inline(c)}</{t}>"
            th = "".join(td("th", c, k) for k, c in enumerate(head))
            tb = "".join("<tr>" + "".join(td("td", r[k] if k < len(r) else "", k) for k in range(len(head))) + "</tr>" for r in rows)
            out.append(f'<div class="table"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>')
            continue
        m = _LIST.match(l)
        if m:
            base, ordered = len(m.group(1)), m.group(2)[0].isdigit()
            items: list[list[str]] = []
            while i < len(lines):
                x = lines[i]
                lm = _LIST.match(x)
                if lm and len(lm.group(1)) <= base + 1 and lm.group(2)[0].isdigit() == ordered:
                    items.append([lm.group(3)])
                    i += 1
                    continue
                if not x.strip():
                    nx = lines[i + 1] if i + 1 < len(lines) else ""
                    if nx.strip() and (len(nx) - len(nx.lstrip()) > base or (_LIST.match(nx) and len(_LIST.match(nx).group(1)) == base)):
                        items[-1].append("")
                        i += 1
                        continue
                    break
                if len(x) - len(x.lstrip()) > base or (items and not _start(x) and not lm):
                    items[-1].append(re.sub(rf"^\s{{0,{base + 4}}}", "", x))
                    i += 1
                    continue
                if lm and len(lm.group(1)) > base:
                    items[-1].append(x[min(base + 2, len(lm.group(1))):])
                    i += 1
                    continue
                break
            tag = "ol" if ordered else "ul"
            start = int(re.match(r"\d+", m.group(2)).group()) if ordered else 1
            lis = []
            for it in items:
                first, box = it[0], ""
                t = re.match(r"^\[([ xX])\]\s+", first)
                if t:
                    box = f'<input type="checkbox" disabled{" checked" if t.group(1) != " " else ""}> '
                    first = first[t.end():]
                rest = it[1:]
                inner = _blocks([first, *rest], ids) if any(r.strip() for r in rest) else inline(first)
                if inner.startswith("<p>") and not any(not r.strip() for r in rest):
                    inner = re.sub(r"^<p>(.*?)</p>", r"\1", inner, count=1, flags=re.S)
                cls = ' class="task"' if box else ""
                lis.append(f"<li{cls}>{box}{inner}</li>")
            st = f' start="{start}"' if ordered and start != 1 else ""
            out.append(f"<{tag}{st}>" + "".join(lis) + f"</{tag}>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not (para and _start(lines[i])) and not ("|" in lines[i] and i + 1 < len(lines) and _TSEP.match(lines[i + 1])):
            para.append(lines[i])
            i += 1
        if not para:
            para, i = [lines[i]], i + 1
        out.append("<p>" + " ".join(inline(p.strip()) for p in para) + "</p>")
    return "".join(out)


def render(text: str) -> str:
    """markdown → safe HTML (headings get ids)"""
    return _blocks(str(text or "").replace("\r\n", "\n").split("\n"), set())


def headings(text: str) -> list[tuple[int, str, str]]:
    """(level, text, id) of every heading, as render() names them"""
    out, ids = [], set()
    fence = False
    for l in str(text or "").split("\n"):
        if _FENCE.match(l):
            fence = not fence
            continue
        m = None if fence else re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", l)
        if m:
            t = re.sub(r"<[^>]+>", "", inline(m.group(2)))
            hid, base, k = slug(t), slug(t), 2
            while hid in ids:
                hid, k = f"{base}-{k}", k + 1
            ids.add(hid)
            out.append((len(m.group(1)), html.unescape(t), hid))
    return out
