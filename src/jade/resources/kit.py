"""Jade Agent Kit runs in a browser, not in Python. The toolkit writes the page that loads it: bootstrap HTML, the JS
configuration and the list of features the page asks for (each loads on first use)."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .. import compat

FEATURES = ("agent", "vfs", "shell", "python", "js", "sqlite", "vector", "bm25", "tfjs", "onnx", "litert", "transformers", "webxdc",
            "notes", "mcp", "http", "usb", "backup", "schedule", "decide", "ollama", "base")


def manifest(features: list[str] | None = None, *, ollama: str | None = None, model: str | None = None, cdn: str | None = None) -> dict:
    feats = list(dict.fromkeys(features or ["agent"]))
    bad = [f for f in feats if f not in FEATURES]
    if bad:
        from ..errors import JadeError
        raise JadeError(f"unknown Kit feature(s) {', '.join(bad)} (features: {', '.join(FEATURES)})", "JADE400")
    return {"kit": cdn or compat.CDN["kit"], "ui": compat.CDN["ui"], "features": feats, "config": {k: v for k, v in {"ollamaHost": ollama, "model": model}.items() if v}}


def page(features: list[str] | None = None, *, ollama: str | None = None, model: str | None = None, title: str = "Jade agent", out: str | None = None, cdn: str | None = None) -> dict:
    """→ {"html", "manifest"}; writes the page to out when given. The visitor's Ollama key is asked for in the page."""
    if isinstance(features, str):
        features = [f.strip() for f in features.split(",") if f.strip()]
    m = manifest(features, ollama=ollama, model=model, cdn=cdn)
    cfg = json.dumps(m["config"])
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<script type="module" src="{html.escape(m['ui'])}"></script>
<style>html,body{{margin:0;height:100%}}body{{display:flex;flex-direction:column;font-family:system-ui,sans-serif}}
form{{display:flex;gap:8px;padding:10px;border-bottom:1px solid #ddd}}input{{flex:1;font:inherit;padding:6px 8px}}jade-chat{{flex:1;min-height:0}}</style>
</head><body>
<!-- features: {html.escape(', '.join(m['features']))} (each loads on first use) -->
<form id="key"><input name="key" type="password" placeholder="Ollama Cloud API key (stays in this browser)" required autocomplete="off"><button>Connect</button></form>
<jade-chat id="chat" greeting="{html.escape(title)}"></jade-chat>
<script type="module">
import {{ createKit }} from {json.dumps(m['kit'])};
const f = document.getElementById('key'), chat = document.getElementById('chat');
f.addEventListener('submit', async e => {{
  e.preventDefault();
  const kit = await createKit({{ ...{cfg}, ollamaKey: f.key.value.trim() }});
  await customElements.whenDefined('jade-chat');
  await chat.connect(kit, {{ ui: false{', model: ' + json.dumps(model) if model else ''} }});
  f.hidden = true;
}});
</script>
</body></html>
"""
    if out:
        Path(out).write_text(doc)
    return {"html": doc, "manifest": m, **({"out": out} if out else {})}
