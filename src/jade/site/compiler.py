"""Compile a site spec to static files: one HTML page per path (folder/index.html), the theme as CSS custom properties,
the UI/UX elements from the CDN, sitemap.xml, robots.txt and 404.html. No build tools; output is plain files any host
serves, including Jade Agent Base's own site folder."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

from .. import compat
from . import markdown, sections, themes

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)

SITE_CSS = """
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{animation:none!important;transition:none!important}}
body{margin:0;background:var(--jade-bg);color:var(--jade-fg);font:16px/1.6 var(--jade-font,system-ui,sans-serif);-webkit-font-smoothing:antialiased}
a{color:var(--jade-accent)}img{max-width:100%;height:auto}
h1,h2,h3{line-height:1.2;letter-spacing:-.01em;margin:0 0 .4em}h1{font-size:clamp(2.1rem,5vw,3.6rem)}h2{font-size:clamp(1.5rem,3vw,2.2rem)}h3{font-size:1.1rem}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.skip{position:absolute;left:-999px}.skip:focus{left:12px;top:12px;z-index:99;background:var(--jade-bg);padding:8px 12px;border-radius:8px}
:focus-visible{outline:2px solid var(--jade-accent);outline-offset:2px}
.nav{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--jade-bg) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--jade-border)}
.nav-in{display:flex;align-items:center;gap:20px;min-height:62px}
.brand{font-weight:700;font-size:1.1rem;color:var(--jade-fg);text-decoration:none;display:flex;align-items:center;gap:8px}.brand .logo{height:28px;width:auto}
.nav nav{display:flex;gap:4px;flex:1}.nav nav a{color:var(--jade-muted);text-decoration:none;padding:6px 10px;border-radius:8px}
.nav nav a:hover,.nav nav a[aria-current]{color:var(--jade-fg);background:var(--jade-surface-2)}
.nav-end{display:flex;align-items:center;gap:10px}.menu{display:none;background:none;border:0;font-size:1.4rem;color:var(--jade-fg);cursor:pointer}
@media (max-width:760px){.menu{display:block;margin-left:auto}.nav nav{display:none;position:absolute;top:62px;left:0;right:0;flex-direction:column;background:var(--jade-bg);padding:10px 20px;border-bottom:1px solid var(--jade-border)}
.nav-in.open nav{display:flex}.nav-end{display:none}.nav-in.open .nav-end{display:flex;position:absolute;top:calc(62px + var(--n,170px));left:20px}}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 18px;border-radius:var(--jade-radius,10px);border:1px solid var(--jade-border);
 background:var(--jade-surface);color:var(--jade-fg);font:inherit;font-weight:600;text-decoration:none;cursor:pointer;transition:transform .1s ease,background .15s}
.btn:hover{transform:translateY(-1px)}.btn.primary{background:var(--jade-accent);border-color:var(--jade-accent);color:var(--jade-accent-fg)}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}
.sec{padding:72px 0}.sec+.sec{padding-top:24px}.sec-head{max-width:680px;margin:0 auto 32px;text-align:center}
.lead{font-size:1.15rem;color:var(--jade-muted);margin:0}
.hero{padding:96px 0 64px;text-align:center}.hero .lead{max-width:640px;margin:0 auto}.hero .btns{justify-content:center}
.hero.left{text-align:left}.hero.left .lead{margin:0}.hero.left .btns{justify-content:flex-start}
.eyebrow{display:inline-block;font-size:.85rem;font-weight:600;color:var(--jade-accent);background:color-mix(in srgb,var(--jade-accent) 12%,transparent);padding:4px 12px;border-radius:999px;margin:0 0 16px}
.hero-img{display:block;margin:48px auto 0;border-radius:calc(var(--jade-radius,10px)*1.4);border:1px solid var(--jade-border);box-shadow:0 30px 80px rgb(0 0 0/.15)}
.grid{display:grid;gap:18px;grid-template-columns:repeat(var(--cols,3),minmax(0,1fr))}
@media (max-width:900px){.grid{grid-template-columns:repeat(min(var(--cols,3),2),minmax(0,1fr))}}@media (max-width:600px){.grid{grid-template-columns:1fr}}
.card{background:var(--jade-surface);border:1px solid var(--jade-border);border-radius:var(--jade-radius,10px);padding:22px}
.feat .icon{font-size:1.6rem;width:44px;height:44px;display:grid;place-items:center;border-radius:10px;background:var(--jade-surface-2);margin-bottom:12px}
.feat p,.steps p{color:var(--jade-muted);margin:0}
.steps{list-style:none;padding:0;margin:0}.steps .num{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--jade-accent);color:var(--jade-accent-fg);font-weight:700;margin-bottom:10px}
.stats{text-align:center}.stat .v{font-size:2.4rem;font-weight:800;color:var(--jade-accent)}.stat .k{color:var(--jade-muted)}
.plan{display:flex;flex-direction:column;gap:10px}.plan .price{font-size:2rem;font-weight:800}.plan .price small{font-size:.9rem;font-weight:500;color:var(--jade-muted)}
.plan ul{padding-left:18px;margin:0 0 8px;flex:1;color:var(--jade-muted)}
.narrow{max-width:680px;margin:0 auto}
.faq details{margin-bottom:10px}.faq summary{cursor:pointer;font-weight:600}.faq .md{margin-top:10px;color:var(--jade-muted)}
.cta .wrap{background:var(--jade-accent);color:var(--jade-accent-fg);border-radius:calc(var(--jade-radius,10px)*1.6);padding:56px 28px;text-align:center}
.cta .lead{color:inherit;opacity:.9}.cta .btns{justify-content:center}.cta .btn.primary{background:var(--jade-accent-fg);color:var(--jade-accent);border-color:transparent}
.form{display:grid;gap:14px}.form label{display:grid;gap:6px;font-weight:600;font-size:.95rem}.form .req{color:var(--jade-danger,#c0392b);margin-left:2px}
.form input,.form textarea,.keyform input{font:inherit;padding:10px 12px;border-radius:calc(var(--jade-radius,10px)*.7);border:1px solid var(--jade-border);background:var(--jade-bg);color:var(--jade-fg)}
.form .check{display:flex;align-items:center;gap:8px;font-weight:500}.form-status:empty{display:none}.form-status.ok{color:var(--jade-ok,#1f8a5b)}.form-status.err{color:var(--jade-danger,#c0392b)}
.keyform{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:14px}.keyform label{display:grid;gap:4px;flex:1;min-width:220px}
.rec img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:8px;margin-bottom:10px}.rec p{color:var(--jade-muted);margin:0}.price-sm{font-weight:700;margin-top:8px}
.skel{min-height:140px;background:linear-gradient(90deg,var(--jade-surface),var(--jade-surface-2),var(--jade-surface));background-size:200% 100%;animation:sk 1.2s infinite}@keyframes sk{to{background-position:-200% 0}}
.gallery figure{margin:0;padding:10px}.gallery img{width:100%;border-radius:8px}.gallery figcaption{color:var(--jade-muted);font-size:.9rem;margin-top:6px}
.md pre{background:var(--jade-code,var(--jade-surface-2));padding:14px;border-radius:8px;overflow:auto}.md code{font-family:ui-monospace,monospace;font-size:.92em}
.md .table{overflow-x:auto}.md table{border-collapse:collapse}.md th,.md td{border:1px solid var(--jade-border);padding:6px 10px}
.muted{color:var(--jade-muted)}
.foot{border-top:1px solid var(--jade-border);padding:28px 0;margin-top:48px;color:var(--jade-muted);font-size:.92rem}
.foot-in{display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:center}.foot p{margin:0}.foot nav{display:flex;gap:16px}.foot a{color:inherit}
jade-chat{display:block;border:1px solid var(--jade-border);border-radius:var(--jade-radius,10px);overflow:hidden}
"""


def out_path(path: str) -> str:
    p = path.strip("/")
    return "index.html" if not p else (p if "." in p.split("/")[-1] else p + "/index.html")


def compile_site(s: dict, *, base_dir: Path | None = None, write: Path | None = None, ui: str | None = None, kit: str | None = None) -> dict:
    """→ {"files": {path: text}, "warnings": [...], "out": dir}. With write, files go to that folder (replaced)."""
    base_dir = base_dir or Path.cwd()
    th = s.get("theme") or "jade"
    td = th if isinstance(th, dict) else {"name": th}
    theme = themes.get(td.get("name", "jade"))
    overrides = {k: v for k, v in td.items() if k not in ("name", "mode")}
    cdn = s.get("cdn") or {}
    ui = ui or cdn.get("ui") or compat.CDN["ui"]
    kit = kit or cdn.get("kit") or compat.CDN["kit"]
    b = s.get("backend") or {}
    backend = (b.get("url") or "").rstrip("/")
    site = {**s, "_kit": kit, "_plans": b.get("plans") or [], "_chat_models": [m["name"] for m in b.get("models") or [] if m.get("kind", "chat") == "chat"]}
    css = themes.css(theme, mode=td.get("mode", "auto"), overrides={("--jade-" + k.replace("_", "-") if not k.startswith("--") else k): v for k, v in overrides.items()} or None) + SITE_CSS
    files: dict[str, str] = {}
    warnings: list[str] = []
    pages = s["pages"]
    for page in pages:
        rel = out_path(page["path"])
        depth = rel.count("/")
        ctx = sections.Context(site=site, page=page, pages=pages, backend=backend, root="../" * depth)
        body = []
        for sec in page["sections"]:
            sec = dict(sec)
            if sec.get("type") == "markdown" and sec.get("file"):
                sec["_file_text"] = (base_dir / sec["file"]).read_text()
            if sec.get("type") == "surface" and sec.get("file") and not sec.get("spec"):
                import yaml
                sec["_file_spec"] = yaml.safe_load((base_dir / sec["file"]).read_text())
            body.append(sections.REGISTRY[sec["type"]].render(sec, ctx))
        warnings += [f"{page['path']}: {w}" for w in ctx.warnings]
        files[rel] = document(s, page, "\n".join(body), ctx, css, ui, theme, backend)
    if "404.html" not in files:
        nf = {"path": "/404", "title": "Not found", "sections": [{"type": "nav"}, {"type": "hero", "title": "Page not found", "subtitle": "That page does not exist.", "buttons": [{"label": "Home", "href": "/"}]}, {"type": "footer"}]}
        ctx = sections.Context(site=site, page=nf, pages=pages, backend=backend, root="/")
        files["404.html"] = document(s, nf, "\n".join(sections.REGISTRY[x["type"]].render(x, ctx) for x in nf["sections"]), ctx, css, ui, theme, backend)
    url = (s.get("url") or "").rstrip("/")
    if url:
        files["sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
            f"  <url><loc>{E(url + p['path'])}</loc></url>\n" for p in pages if p["path"] != "/404") + "</urlset>\n"
    files["robots.txt"] = "User-agent: *\nAllow: /\n" + (f"Sitemap: {url}/sitemap.xml\n" if url else "")
    result = {"files": {k: v for k, v in files.items()}, "warnings": warnings, "pages": [p["path"] for p in pages]}
    if write is not None:
        out = Path(write)
        if out.exists():
            for c in out.iterdir():
                shutil.rmtree(c) if c.is_dir() else c.unlink()
        out.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            f = out / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        st = base_dir / (s.get("static") or "static")
        if st.is_dir():
            shutil.copytree(st, out, dirs_exist_ok=True)
        result["out"] = str(out)
        result["bytes"] = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    return result


def document(s: dict, page: dict, body: str, ctx: sections.Context, css: str, ui: str, theme: dict, backend: str) -> str:
    title = page.get("title") or s["name"]
    full = s["name"] if page["path"] == "/" or title == s["name"] else f"{title} · {s['name']}"
    desc = page.get("description") or s.get("description") or s.get("tagline") or ""
    url = (s.get("url") or "").rstrip("/")
    font = f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="{E(theme["font_url"])}">' if theme.get("font_url") else ""
    fav = s.get("favicon") or "data:image/svg+xml," + _favicon(s["name"], themes.get(theme["name"])["light"].get("--jade-accent", "#0b7a5b"))
    meta = [f'<meta name="description" content="{E(desc)}">', f'<meta property="og:title" content="{E(full)}">', f'<meta property="og:description" content="{E(desc)}">',
            '<meta property="og:type" content="website">']
    if url:
        meta += [f'<link rel="canonical" href="{E(url + page["path"])}">', f'<meta property="og:url" content="{E(url + page["path"])}">']
    if backend:
        meta.append(f'<meta name="jade-base" content="{E(backend)}">')
    scripts = "\n".join(f"  try{{{js}}}catch(e){{console.error('[jade site]',e)}}" for js in ctx.scripts)
    boot = (f"<script type=\"module\">\nimport * as UI from {json.dumps(ui)};\nwindow.UI = UI;\n(async () => {{\n{scripts}\n}})();\n</script>" if ctx.scripts
            else f'<script type="module" src="{E(ui)}"></script>')
    head = s.get("head") or ""
    return f"""<!doctype html>
<html lang="{E(s.get('lang', 'en'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(full)}</title>
{chr(10).join(meta)}
<meta name="generator" content="Jade Agent Stack {compat.TOOLKIT}">
<link rel="icon" href="{E(fav)}">
{font}
<style>{css}</style>
{head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{_nav_split(body)}
{boot}
</body>
</html>
"""


def _nav_split(body: str) -> str:
    """put everything after the top nav in <main id=main>, and the footer after it"""
    nav_end = body.find("</header>") + len("</header>") if body.startswith('<header class="nav">') else 0
    foot = body.rfind('<footer class="foot">')
    foot = foot if foot >= 0 else len(body)
    return body[:nav_end] + '\n<main id="main">\n' + body[nav_end:foot] + "\n</main>\n" + body[foot:]


def _favicon(name: str, color: str) -> str:
    from urllib.parse import quote
    letter = html.escape((name or "J").strip()[:1].upper())
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{color}"/><text x="32" y="44" font-family="system-ui,sans-serif" font-size="36" font-weight="700" text-anchor="middle" fill="#fff">{letter}</text></svg>'
    return quote(svg)


def render_markdown_page(text: str) -> str:
    return markdown.render(text)
