"""The agent façade. On Vault, it talks to Vault's own agent. On Base (which hosts no agent), it runs a small tool loop
here: a model from config.models (any OpenAI-compatible endpoint: Ollama, Ollama Cloud, OpenAI, Base's own gateway)
with Base's tools, every call going through the harness (approvals, idempotency keys).

    agent = stack.agent("my-booker", target="base")
    reply = agent.ask("how many products do I have?")
    for ev in agent.stream("create a products collection"): ...
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from . import http
from .errors import JadeError, SafetyError

DEFAULT_URLS = {"ollama": "http://127.0.0.1:11434", "ollama-cloud": "https://ollama.com", "openai": "https://api.openai.com"}


class Agent:
    def __init__(self, harness: Any, name: str = "jade", *, target: str = "vault", model: str | None = None, max_steps: int = 8, system: str | None = None):
        if target not in ("vault", "base"):
            raise JadeError("an agent runs on vault or base", "JADE400")
        self.h, self.name, self.target, self.max_steps = harness, name, target, max_steps
        self.model = model
        self.system = system or ("You manage a Jade Agent Base backend through tools. Use tools to look before you change things. "
                                 "Answer briefly. If a tool is refused, say so and stop.")
        self.messages: list[dict] = []

    def ask(self, message: str) -> dict:
        last: dict = {}
        for ev in self.stream(message):
            last = ev
        return last

    def stream(self, message: str) -> Iterator[dict]:
        if self.target == "vault":
            yield {"event": "start", "target": "vault"}
            r = self.h.call("vault", "chat", {"message": message, "session": self.name})
            yield {"event": "answer", "text": r.get("reply") or r.get("text") or r.get("answer") or json.dumps(r), "raw": r}
            return
        cfg = self.h.config.get("models") or {}
        provider = cfg.get("provider", "ollama")
        url = (cfg.get("url") or DEFAULT_URLS.get(provider, "")).rstrip("/")
        model = self.model or cfg.get("strong") or cfg.get("fast")
        if not url or not model:
            raise JadeError("set models.url and models.strong in jade.config.yaml (jade init)", "JADE100")
        key = self.h.secrets.get(cfg["key"]) if cfg.get("key") else None
        tools = self.h.base.tools("openai")
        if not self.messages:
            self.messages.append({"role": "system", "content": self.system})
        self.messages.append({"role": "user", "content": message})
        yield {"event": "start", "target": "base", "model": model, "tools": len(tools)}
        for step in range(self.max_steps):
            r = http.request("POST", url + "/v1/chat/completions", token=key, body={"model": model, "messages": self.messages, "tools": tools, "stream": False},
                             timeout=self.h.config.get("defaults.chat_timeout", 300)).json() or {}
            msg = ((r.get("choices") or [{}])[0]).get("message") or {}
            self.messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
            calls = msg.get("tool_calls") or []
            if not calls:
                yield {"event": "answer", "text": msg.get("content") or "", "steps": step + 1}
                return
            for c in calls:
                fn = c.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else (fn.get("arguments") or {})
                except ValueError:
                    args = {}
                yield {"event": "tool", "tool": fn.get("name"), "args": args}
                try:
                    out: Any = self.h.call("base", fn.get("name", ""), args)
                    content = json.dumps(out)[:20000]
                except SafetyError as e:
                    content = f"Refused here: {e.message}. Do not retry this."
                    yield {"event": "refused", "tool": fn.get("name"), "error": e.to_dict()}
                except JadeError as e:
                    content = f"Error: {e.message}"
                    if e.code == "JADE103":
                        raise
                self.messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "name": fn.get("name"), "content": content})
        yield {"event": "answer", "text": "(stopped after the step limit)", "steps": self.max_steps}
