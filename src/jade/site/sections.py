"""The section library: the building blocks of a page. Each section has parameters (with defaults drawn from the site,
so most can be used with no parameters at all) and renders HTML that uses Jade Agent UI/UX elements where it helps.

A section is a dict: {"type": "hero", "title": "…"}. Every section also takes "id" (an anchor) and "class"."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import markdown

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)


@dataclass
class Param:
    type: str
    default: Any = None
    doc: str = ""
    required: bool = False


@dataclass
class Section:
    name: str
    doc: str
    params: dict[str, Param]
    render: Callable[[dict, "Context"], str]
    needs: list[str] = field(default_factory=list)  # backend modules it uses: gateway, billing
    example: dict = field(default_factory=dict)


@dataclass
class Context:
    """what a section sees while rendering"""
    site: dict
    page: dict
    pages: list[dict]
    backend: str  # the server URL ('' for a static site)
    scripts: list[str] = field(default_factory=list)  # module script bodies for this page
    warnings: list[str] = field(default_factory=list)
    root: str = ""  # relative path to the site root ("" or "../")
    seq: int = 0

    def uid(self, p: str = "s") -> str:
        self.seq += 1
        return f"{p}{self.seq}"

    def href(self, path: str) -> str:
        """a site path (/pricing) as a link that works from this page, on any host or sub-folder"""
        if not path or re.match(r"^(https?:|mailto:|#)", path):
            return path or "#"
        p = path.strip("/")
        return (self.root or "./") + (p + "/" if p and "." not in p.split("/")[-1] else p)


REGISTRY: dict[str, Section] = {}


def section(name: str, doc: str, /, needs: list[str] | None = None, example: dict | None = None, **params: Param):
    def deco(fn):
        REGISTRY[name] = Section(name, doc, params, fn, needs or [], example or {})
        return fn
    return deco


def g(s: dict, k: str, d: Any = None) -> Any:
    v = s.get(k)
    return d if v is None or v == "" else v


def wrap(s: dict, inner: str, cls: str = "") -> str:
    sid = f' id="{E(s["id"])}"' if s.get("id") else ""
    return f'<section class="sec {cls} {E(s.get("class", ""))}"{sid}><div class="wrap">{inner}</div></section>'


def head(title: str | None, sub: str | None = None) -> str:
    return (f'<header class="sec-head"><h2>{E(title)}</h2>{f"<p class=lead>{E(sub)}</p>" if sub else ""}</header>' if title else "")


def button(b: Any, ctx: Context, primary: bool = True) -> str:
    if isinstance(b, str):
        b = {"label": b, "href": "#"}
    return f'<a class="btn{" primary" if primary else ""}" href="{E(ctx.href(b.get("href", "#")))}">{E(b.get("label", "Learn more"))}</a>'


# ---------------- sections ----------------

@section("nav", "The top bar: the site's name, links to its pages, a theme switch and, with a backend, Sign in.",
         brand=Param("string", None, "name shown (default: the site name)"), links=Param("list", None, 'links [{"label", "href"}] (default: every page with nav = true)'),
         cta=Param("object", None, 'a button {"label", "href"}'), theme_toggle=Param("bool", True, "show the light/dark switch"))
def _nav(s, ctx):
    links = s.get("links") or [{"label": p.get("nav_label") or p.get("title"), "href": p["path"]} for p in ctx.pages if p.get("nav", p["path"] != "/") and p.get("title")]
    cur = ctx.page["path"]
    items = "".join(f'<a href="{E(ctx.href(l["href"]))}"{" aria-current=page" if l["href"] == cur else ""}>{E(l["label"])}</a>' for l in links)
    cta = button(s["cta"], ctx) if s.get("cta") else ""
    tog = "<jade-theme-toggle></jade-theme-toggle>" if g(s, "theme_toggle", True) else ""
    logo = ctx.site.get("logo")
    brand = (f'<img src="{E(logo)}" alt="" class="logo">' if logo else "") + E(g(s, "brand", ctx.site["name"]))
    return (f'<header class="nav"><div class="wrap nav-in"><a class="brand" href="{E(ctx.href("/"))}">{brand}</a>'
            f'<button class="menu" aria-label="Menu" aria-expanded="false" onclick="this.parentNode.classList.toggle(\'open\');this.setAttribute(\'aria-expanded\',this.parentNode.classList.contains(\'open\'))">☰</button>'
            f'<nav aria-label="Main">{items}</nav><div class="nav-end">{tog}{cta}</div></div></header>')


@section("hero", "The opening: a big title, a line under it, buttons and an optional image.",
         example={"type": "hero", "title": "Embeddings for every app", "subtitle": "One API, fair prices.", "buttons": [{"label": "Start free", "href": "/account"}]},
         title=Param("string", None, "headline (default: the site name)"), subtitle=Param("string", None, "one or two sentences (default: the site tagline)"),
         eyebrow=Param("string", None, "small text above the title"), buttons=Param("list", None, '[{"label", "href"}] (first is primary)'),
         image=Param("string", None, "an image URL or path"), align=Param("string", "center", "center | left"))
def _hero(s, ctx):
    btns = "".join(button(b, ctx, i == 0) for i, b in enumerate(s.get("buttons") or []))
    img = f'<img class="hero-img" src="{E(s["image"])}" alt="">' if s.get("image") else ""
    eb = f'<p class="eyebrow">{E(s["eyebrow"])}</p>' if s.get("eyebrow") else ""
    return wrap(s, f'{eb}<h1>{E(g(s, "title", ctx.site["name"]))}</h1><p class="lead">{E(g(s, "subtitle", ctx.site.get("tagline", "")))}</p>'
                   f'{f"<div class=btns>{btns}</div>" if btns else ""}{img}', f'hero {"left" if s.get("align") == "left" else ""}')


@section("features", "A grid of features: an icon (emoji or short text), a title and a sentence each.",
         example={"type": "features", "title": "Why us", "items": [{"icon": "⚡", "title": "Fast", "text": "Answers in milliseconds."}]},
         title=Param("string", None, "heading"), subtitle=Param("string", None, "line under the heading"),
         items=Param("list", [], '[{"icon", "title", "text"}]', True), columns=Param("int", 3, "columns on wide screens"))
def _features(s, ctx):
    icon = lambda i: f'<div class=icon aria-hidden=true>{E(i.get("icon"))}</div>' if i.get("icon") else ""
    items = "".join(f'<div class="card feat">{icon(i)}'
                    f'<h3>{E(i.get("title"))}</h3><p>{E(i.get("text"))}</p></div>' for i in s.get("items") or [])
    return wrap(s, head(s.get("title"), s.get("subtitle")) + f'<div class="grid" style="--cols:{int(g(s, "columns", 3))}">{items}</div>', "features")


@section("steps", "Numbered steps (how it works).", title=Param("string", "How it works", "heading"), items=Param("list", [], '[{"title", "text"}]', True))
def _steps(s, ctx):
    items = "".join(f'<li class="card"><span class="num">{n}</span><h3>{E(i.get("title"))}</h3><p>{E(i.get("text"))}</p></li>' for n, i in enumerate(s.get("items") or [], 1))
    return wrap(s, head(g(s, "title", "How it works")) + f'<ol class="steps grid" style="--cols:{min(4, max(1, len(s.get("items") or [])))}">{items}</ol>', "steps-sec")


@section("stats", "Big numbers with labels.", items=Param("list", [], '[{"value", "label"}]', True), title=Param("string", None, "heading"))
def _stats(s, ctx):
    items = "".join(f'<div class="stat"><div class="v">{E(i.get("value"))}</div><div class="k">{E(i.get("label"))}</div></div>' for i in s.get("items") or [])
    return wrap(s, head(s.get("title")) + f'<div class="grid stats" style="--cols:{min(4, max(1, len(s.get("items") or [])))}">{items}</div>', "stats-sec")


@section("pricing", "Plans. With a backend: the live plans and Subscribe buttons (Stripe Checkout). Without: the plans you list.",
         needs=["gateway"], example={"type": "pricing", "title": "Pricing"},
         title=Param("string", "Pricing", "heading"), subtitle=Param("string", None, "line under it"), currency=Param("string", "USD", "currency code"),
         plans=Param("list", None, 'for a static site: [{"name", "price", "features": [...], "button": {"label","href"}}] (default: backend.plans)'))
def _pricing(s, ctx):
    top = head(g(s, "title", "Pricing"), s.get("subtitle"))
    if ctx.backend:
        signin = ctx.href(_page_with(ctx, "auth") or "/account")
        ctx.scripts.append(f"document.querySelectorAll('jade-pricing').forEach(p=>p.addEventListener('jade-needs-signin',()=>location.href={json.dumps(signin)}));")
        return wrap(s, top + f'<jade-pricing currency="{E(g(s, "currency", "USD"))}"></jade-pricing>', "pricing")
    plans = s.get("plans") or [{"name": p.get("name"), "price": p.get("price_month", 0), "features": p.get("features") or _plan_feats(p)} for p in ctx.site.get("_plans", [])]
    cur = g(s, "currency", "USD")
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(cur, cur + " ")
    cards = "".join(f'<div class="card plan"><h3>{E(str(p.get("name", "")).title())}</h3><div class="price">{E(sym + _num(p["price"])) if p.get("price") else "Free"}'
                    f'{"<small> / month</small>" if p.get("price") else ""}</div><ul>{"".join(f"<li>{E(x)}</li>" for x in p.get("features", []))}</ul>'
                    f'{button(p.get("button") or {"label": "Choose " + str(p.get("name", "")), "href": "#"}, ctx, bool(p.get("price")))}</div>' for p in plans)
    if not plans:
        ctx.warnings.append("pricing: no plans (add backend.plans or plans = [...])")
    return wrap(s, top + f'<div class="grid" style="--cols:{min(4, max(1, len(plans)))}">{cards}</div>', "pricing")


def _num(n):
    return f"{n:g}" if isinstance(n, (int, float)) else str(n)


def _plan_feats(p):
    f = []
    if p.get("monthly_tokens"):
        f.append(f'{p["monthly_tokens"]:,} tokens a month')
    if p.get("rpm"):
        f.append(f'{p["rpm"]} requests a minute')
    if p.get("description"):
        f.append(p["description"])
    return f


def _page_with(ctx, kind):
    for p in ctx.pages:
        if any(x.get("type") == kind for x in p.get("sections", [])):
            return p["path"]
    return None


@section("auth", "Sign in, create an account, reset a password (needs a backend). After signing in, go to `next`.",
         needs=[], title=Param("string", None, "heading above it"), next=Param("string", None, "where to go after signing in, e.g. /account"))
def _auth(s, ctx):
    if not ctx.backend:
        ctx.warnings.append("auth: needs a backend (backend.url)")
    nxt = s.get("next")
    if nxt:
        ctx.scripts.append(f"document.querySelectorAll('jade-auth').forEach(a=>a.addEventListener('jade-auth',()=>location.href={json.dumps(ctx.href(nxt))}));")
    return wrap(s, head(s.get("title")) + '<div class="narrow"><jade-auth></jade-auth></div>', "auth")


@section("account", "The signed-in user's plan, usage, billing and API keys; signed out, a sign-in form (needs a backend).",
         needs=["gateway"], title=Param("string", "Your account", "heading"), currency=Param("string", "USD", "currency code"))
def _account(s, ctx):
    if not ctx.backend:
        ctx.warnings.append("account: needs a backend (backend.url)")
    ctx.scripts.append("{const c=await UI.baseClient();const show=()=>{for(const a of document.querySelectorAll('[data-signed-out]'))a.hidden=c.signedIn;};c.addEventListener('change',show);show();}")
    return wrap(s, head(g(s, "title", "Your account")) + f'<div class="narrow" data-signed-out><jade-auth></jade-auth></div><jade-account currency="{E(g(s, "currency", "USD"))}"></jade-account>', "account")


@section("chat", "An AI chat. mode gateway: the backend's models for signed-in users. mode ollama: the visitor pastes an Ollama Cloud key. mode demo: a scripted demo.",
         needs=["gateway"], example={"type": "chat", "model": "house-chat", "suggestions": ["What can you do?"]},
         title=Param("string", None, "heading"), mode=Param("string", "gateway", "gateway | ollama | demo"),
         model=Param("string", None, "model name (gateway: one of backend.models)"), system=Param("string", None, "system prompt"),
         greeting=Param("string", "How can I help?", "empty-state heading"), suggestions=Param("list", [], "starter prompts"),
         height=Param("string", "70vh", "CSS height"), tools=Param("bool", False, "give the model the kit's workspace tools (files, shell)"),
         replies=Param("object", None, 'demo mode: {"keyword": "reply"}; "*" for anything else'))
def _chat(s, ctx):
    cid = ctx.uid("chat")
    mode = "demo" if ctx.site.get("demo") else g(s, "mode", "gateway" if ctx.backend else "demo")
    attrs = f'id="{cid}" greeting="{E(g(s, "greeting", "How can I help?"))}" suggestions="{E(json.dumps(s.get("suggestions") or []))}" style="height:{E(g(s, "height", "70vh"))}"'
    model = g(s, "model", (ctx.site.get("_chat_models") or [None])[0])
    sysmsg = json.dumps(g(s, "system", f"You are the assistant of {ctx.site['name']}. Be concise and helpful."))
    tools = "['read','write','edit','bash']" if s.get("tools") else "[]"
    if mode == "demo":
        rep = json.dumps(s.get("replies") or {"*": f"This is a demo of {ctx.site['name']}. Connect a backend to talk to a real model."})
        ctx.scripts.append(f"{{const c=document.getElementById('{cid}');await customElements.whenDefined('jade-chat');const R={rep};"
                           "c.handler=async(t,r)=>{const k=Object.keys(R).find(k=>k!=='*'&&t.toLowerCase().includes(k.toLowerCase()));const a=R[k]??R['*']??'…';"
                           "for(const w of a.match(/\\S+\\s*/g)||[]){r.append(w);await new Promise(x=>setTimeout(x,25));}};}")
        return wrap(s, head(s.get("title")) + f'<jade-chat {attrs}></jade-chat>', "chat-sec")
    kit = json.dumps(ctx.site["_kit"])
    if mode == "ollama":
        ctx.scripts.append(f"{{const c=document.getElementById('{cid}');const f=document.getElementById('{cid}-key');await customElements.whenDefined('jade-chat');"
                           f"f.addEventListener('submit',async e=>{{e.preventDefault();const {{createKit}}=await import({kit});const kit=await createKit({{ollamaKey:f.key.value.trim()}});"
                           f"await c.connect(kit,{{ui:false,model:{json.dumps(model or 'gpt-oss:120b')},system:{sysmsg},tools:{tools}}});f.hidden=true;}});}}")
        form = f'<form id="{cid}-key" class="keyform"><label>Ollama Cloud key <input name="key" type="password" required autocomplete="off"></label><button class="btn primary">Connect</button></form>'
        return wrap(s, head(s.get("title")) + form + f'<jade-chat {attrs}></jade-chat>', "chat-sec")
    if not model:
        ctx.warnings.append("chat: no model (set model, or add a chat model to backend.models)")
    signin = ctx.href(_page_with(ctx, "auth") or _page_with(ctx, "account") or "/account")
    ctx.scripts.append(f"{{const c=document.getElementById('{cid}');const b=await UI.baseClient();await customElements.whenDefined('jade-chat');let on=false;"
                       f"const go=async()=>{{if(!b.signedIn){{c.setAttribute('hint','Sign in to chat');c.composer.setAttribute('disabled','');return;}}"
                       f"c.removeAttribute('hint');c.composer.removeAttribute('disabled');if(on)return;on=true;const {{createKit}}=await import({kit});"
                       f"const kit=await createKit({{ollamaHost:b.url,provider:'local'}});const o=await kit.use('ollama');o.local.apiKey=b.token;"
                       f"await c.connect(kit,{{ui:false,model:{json.dumps(model or '')},system:{sysmsg},tools:{tools}}});}};"
                       f"c.addEventListener('click',()=>{{if(!b.signedIn)location.href={json.dumps(signin)};}});b.addEventListener('change',go);go();}}")
    return wrap(s, head(s.get("title")) + f'<jade-chat {attrs}></jade-chat>', "chat-sec")


@section("form", "A form that saves to a backend collection (waitlists, contact forms, signups). The collection must let anyone create.",
         example={"type": "form", "collection": "waitlist", "fields": ["email:email!", "company:text"], "submit": "Join the waitlist"},
         collection=Param("string", None, "collection name", True), title=Param("string", None, "heading"), text=Param("string", None, "a line under it"),
         fields=Param("list", [], 'field specs "name:type!" (type: text, email, number, url, textarea, checkbox; ! = required) or {"name","label","type","required"}', True),
         submit=Param("string", "Send", "button label"), success=Param("string", "Thank you! We got it.", "shown after sending"))
def _form(s, ctx):
    fid = ctx.uid("form")
    if not ctx.backend:
        ctx.warnings.append("form: needs a backend (backend.url)")
    rows = []
    for f in s.get("fields") or []:
        f = parse_field(f)
        ty = f["type"]
        req = " required" if f["required"] else ""
        star = '<span class="req" aria-hidden="true">*</span>' if f["required"] else ""
        if ty == "textarea":
            ctl = f'<textarea name="{E(f["name"])}" rows="4"{req}></textarea>'
        elif ty in ("checkbox", "bool"):
            rows.append(f'<label class="check"><input type="checkbox" name="{E(f["name"])}"{req}> {E(f["label"])}</label>')
            continue
        else:
            ctl = f'<input name="{E(f["name"])}" type="{E({"text": "text", "email": "email", "number": "number", "url": "url"}.get(ty, "text"))}"{req}>'
        rows.append(f'<label><span>{E(f["label"])}{star}</span>{ctl}</label>')
    ctx.scripts.append(f"{{const f=document.getElementById('{fid}');const b=await UI.baseClient();f.addEventListener('submit',async e=>{{e.preventDefault();"
                       "const d={};for(const el of f.elements){if(!el.name)continue;d[el.name]=el.type==='checkbox'?el.checked:el.type==='number'?(el.value===''?null:+el.value):el.value.trim();}"
                       "const st=f.querySelector('.form-status');const btn=f.querySelector('button');btn.disabled=true;"
                       f"try{{await b.fetch('/api/collections/'+{json.dumps(s.get('collection', ''))}+'/records',{{method:'POST',body:d,auth:false}});f.reset();st.className='form-status ok';st.textContent={json.dumps(g(s, 'success', 'Thank you! We got it.'))};}}"
                       "catch(x){st.className='form-status err';st.textContent=Object.values(x.fields||{}).join(' ')||x.message;}finally{btn.disabled=false;}});}")
    text = f'<p class="lead">{E(s["text"])}</p>' if s.get("text") else ""
    return wrap(s, head(s.get("title")) + text + f'<form id="{fid}" class="card form narrow">{"".join(rows)}<div class="form-status" role="status"></div>'
                   f'<button class="btn primary" type="submit">{E(g(s, "submit", "Send"))}</button></form>', "form-sec")


def parse_field(f) -> dict:
    """'email:email!' or {name, type, label, required} → {name, type, label, required}"""
    if isinstance(f, str):
        name, _, ty = f.partition(":")
        req = ty.endswith("!") or name.endswith("!")
        ty, name = ty.rstrip("!") or "text", name.rstrip("!")
        return {"name": name, "type": ty, "label": name.replace("_", " ").capitalize(), "required": req}
    return {"name": f["name"], "type": f.get("type", "text"), "label": f.get("label") or f["name"].replace("_", " ").capitalize(), "required": bool(f.get("required"))}


@section("records", "Cards listing records of a public backend collection (products, posts, team, …).",
         example={"type": "records", "collection": "products", "title_field": "title", "text_field": "description", "price_field": "price"},
         collection=Param("string", None, "collection name (its list rule must allow the visitor)", True), title=Param("string", None, "heading"),
         title_field=Param("string", "title", "field shown as the card title"), text_field=Param("string", None, "field shown as text"),
         image_field=Param("string", None, "file field shown as the image"), price_field=Param("string", None, "field shown as a price"),
         filter=Param("string", None, "PocketBase filter"), sort=Param("string", None, "sort, e.g. title or -price (-created needs a created field)"), limit=Param("int", 12, "how many"),
         empty=Param("string", "Nothing here yet.", "shown when there are none"))
def _records(s, ctx):
    rid = ctx.uid("rec")
    cfg = json.dumps({k: s.get(k) for k in ("collection", "title_field", "text_field", "image_field", "price_field", "filter", "sort", "limit", "empty")} | {"title_field": g(s, "title_field", "title"), "sort": g(s, "sort", None), "limit": g(s, "limit", 12), "empty": g(s, "empty", "Nothing here yet.")})
    ctx.scripts.append(f"{{const el=document.getElementById('{rid}');const c={cfg};const b=await UI.baseClient();const esc=s=>String(s??'').replace(/[&<>\"']/g,x=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}})[x]);"
                       "try{const r=await b.fetch('/api/collections/'+c.collection+'/records',{query:{filter:c.filter,sort:c.sort,perPage:c.limit},auth:b.signedIn});"
                       "el.innerHTML=r.items.length?r.items.map(x=>`<div class=\"card rec\">${c.image_field&&x[c.image_field]?`<img src=\"${b.url}/api/files/${x.collectionId}/${x.id}/${encodeURIComponent([].concat(x[c.image_field])[0])}\" alt=\"\" loading=lazy>`:''}"
                       "<h3>${esc(x[c.title_field])}</h3>${c.text_field?`<p>${esc(x[c.text_field])}</p>`:''}${c.price_field&&x[c.price_field]!=null?`<div class=\"price-sm\">${esc(x[c.price_field])}</div>`:''}</div>`).join(''):`<p class=\"muted\">${esc(c.empty)}</p>`;}"
                       "catch(e){el.innerHTML=`<p class=\"muted\">Could not load: ${esc(e.message)}</p>`;}}")
    return wrap(s, head(s.get("title")) + f'<div id="{rid}" class="grid records" style="--cols:3" aria-live="polite"><div class="card skel"></div><div class="card skel"></div><div class="card skel"></div></div>', "records-sec")


@section("faq", "Questions and answers that open and close.", title=Param("string", "Questions", "heading"),
         items=Param("list", [], '[{"q", "a"}] (answers may use markdown)', True))
def _faq(s, ctx):
    items = "".join(f'<details class="card"><summary>{E(i.get("q"))}</summary><div class="md">{markdown.render(i.get("a", ""))}</div></details>' for i in s.get("items") or [])
    return wrap(s, head(g(s, "title", "Questions")) + f'<div class="faq narrow">{items}</div>', "faq-sec")


@section("cta", "A call to action: a heading, a line and a button, on a coloured band.",
         title=Param("string", None, "heading", True), text=Param("string", None, "a line"), button=Param("object", None, '{"label", "href"}'))
def _cta(s, ctx):
    b = button(s["button"], ctx) if s.get("button") else ""
    lead = f'<p class=lead>{E(s["text"])}</p>' if s.get("text") else ""
    return wrap(s, f'<h2>{E(s.get("title"))}</h2>{lead}<div class="btns">{b}</div>', "cta")


@section("markdown", "Text written in markdown (or a .md file next to jade.toml).",
         text=Param("string", None, "markdown"), file=Param("string", None, "a markdown file, relative to jade.toml"), narrow=Param("bool", True, "a reading width"))
def _md(s, ctx):
    txt = s.get("text") or s.get("_file_text") or ""
    return wrap(s, f'<div class="md{" narrow" if g(s, "narrow", True) else ""}">{markdown.render(txt)}</div>', "md-sec")


@section("gallery", "A grid of images with captions.", title=Param("string", None, "heading"),
         images=Param("list", [], '[{"src", "alt", "caption"}] or URLs', True), columns=Param("int", 3, "columns"))
def _gallery(s, ctx):
    def fig(i):
        cap = f'<figcaption>{E(i.get("caption"))}</figcaption>' if i.get("caption") else ""
        return f'<figure class="card"><img src="{E(i.get("src"))}" alt="{E(i.get("alt", ""))}" loading="lazy">{cap}</figure>'
    imgs = "".join(fig(i if isinstance(i, dict) else {"src": i})
                   for i in s.get("images") or [])
    return wrap(s, head(s.get("title")) + f'<div class="grid gallery" style="--cols:{int(g(s, "columns", 3))}">{imgs}</div>', "gallery-sec")


@section("code", "A code block with copy and highlighting.", title=Param("string", None, "heading"), lang=Param("string", "", "language"), code=Param("string", "", "the code", True))
def _code(s, ctx):
    return wrap(s, head(s.get("title")) + f'<div class="narrow"><jade-code lang="{E(s.get("lang", ""))}">{E(s.get("code", ""))}</jade-code></div>', "code-sec")


@section("surface", "UI from a Jade surface spec (components, data, actions), e.g. a calculator, a dashboard or a quiz.",
         title=Param("string", None, "heading"), spec=Param("object", {}, "a surface spec: {root, components, data} (see the UI/UX catalog)"),
         file=Param("string", None, "a saved surface spec (YAML or JSON), relative to jade.site.yaml: reuse a design instead of rebuilding it"),
         name=Param("string", None, "surface name (for agents and actions)"))
def _surface(s, ctx):
    sid = ctx.uid("surf")
    spec = s.get("spec") or s.get("_file_spec") or {}
    if not spec:
        ctx.warnings.append("surface: no spec (spec or file)")
    ctx.scripts.append(f"{{const el=document.getElementById('{sid}');await customElements.whenDefined('jade-surface');await el.render({json.dumps(spec)});}}")
    return wrap(s, head(s.get("title")) + f'<jade-surface id="{sid}" name="{E(g(s, "name", sid))}"></jade-surface>', "surface-sec")


@section("html", "Your own HTML, as it is (an escape hatch).", html=Param("string", "", "HTML", True))
def _html(s, ctx):
    return wrap(s, s.get("html", ""), "html-sec")


@section("footer", "The bottom of the page: a line of text and links.", text=Param("string", None, "text (default: © the site name)"),
         links=Param("list", [], '[{"label", "href"}]'))
def _footer(s, ctx):
    links = "".join(f'<a href="{E(ctx.href(l.get("href", "#")))}">{E(l.get("label"))}</a>' for l in s.get("links") or [])
    return f'<footer class="foot"><div class="wrap foot-in"><p>{E(g(s, "text", "© " + ctx.site["name"]))}</p><nav aria-label="Footer">{links}</nav></div></footer>'


def describe(name: str | None = None, short: bool = False) -> str:
    """the section library as compact text (for agents): one line each, or one section in full"""
    if name:
        sec = REGISTRY.get(name)
        if not sec:
            return f"unknown section {name!r}; sections: {', '.join(REGISTRY)}"
        lines = [f"{sec.name}: {sec.doc}"]
        for k, p in sec.params.items():
            d = "" if p.default in (None, [], {}) else f" (default {json.dumps(p.default)})"
            lines.append(f"  {k}{'*' if p.required else ''}: {p.type}{d}: {p.doc}")
        if sec.needs:
            lines.append(f"  needs backend modules: {', '.join(sec.needs)}")
        if sec.example:
            lines.append(f"  example: {json.dumps(sec.example)}")
        return "\n".join(lines)
    if short:
        return ", ".join(REGISTRY)
    return "\n".join(f"{s.name}: {s.doc} [{', '.join(k + ('*' if p.required else '') for k, p in s.params.items())}]" for s in REGISTRY.values())
