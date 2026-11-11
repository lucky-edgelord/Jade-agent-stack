"""Jade Agent UI/UX is web components from a CDN. The toolkit writes HTML that mounts them."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .. import compat
from ..site import themes

MOUNTS = ("full-screen", "widget", "inline")


def chat(*, mount: str = "full-screen", theme: dict | str | None = None, base: str | None = None, title: str = "Chat",
         greeting: str = "How can I help?", suggestions: list[str] | None = None, out: str | None = None) -> dict:
    """a page with <jade-chat> (full-screen or inline) or <jade-chat-widget> (a floating button). theme: a preset name
    or {"preset": "midnight", "mode": "dark"}. base: a Jade Agent Base URL for sign-in and the gateway."""
    if mount not in MOUNTS:
        from ..errors import JadeError
        raise JadeError(f"mount must be one of {', '.join(MOUNTS)}", "JADE400")
    t = theme if isinstance(theme, dict) else {"preset": theme or "jade"}
    css = themes.css(themes.get(t.get("preset", "jade")), mode=t.get("mode", "auto"))
    sug = html.escape(json.dumps(suggestions or []))
    meta = f'<meta name="jade-base" content="{html.escape(base)}">' if base else ""
    if mount == "widget":
        el = f'<jade-chat-widget title="{html.escape(title)}" greeting="{html.escape(greeting)}" suggestions="{sug}"></jade-chat-widget>'
    else:
        el = f'<jade-chat greeting="{html.escape(greeting)}" suggestions="{sug}" style="{"height:100vh" if mount == "full-screen" else "height:70vh"}"></jade-chat>'
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta}
<title>{html.escape(title)}</title><style>{css}html,body{{margin:0;background:var(--jade-bg);color:var(--jade-fg)}}</style>
<script type="module" src="{html.escape(compat.CDN['ui'])}"></script></head>
<body>{el}
<script type="module">
// answer with your own backend: document.querySelector('{"jade-chat-widget" if mount == "widget" else "jade-chat"}').handler = async (text, reply) => reply.append('…')
</script></body></html>
"""
    if out:
        Path(out).write_text(doc)
    return {"html": doc, "mount": mount, **({"out": out} if out else {})}
