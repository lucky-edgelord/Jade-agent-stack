"""Jade Agent Stack: one Python package to drive Jade Vault (control plane), Jade Agent Base (resource plane),
Jade Agent Kit (the embeddable subset of Vault) and Jade Agent UI/UX (presentation), through their documented interfaces.
It is a client, not a fork, and it needs the network to reach them.

    import jade
    stack = jade.Stack.load()                 # jade.config.yaml, found upward from the working directory
    stack.doctor()
    stack.base.tools(format="openai")
    stack.call("base", "records_list", {"collection": "posts"})
    site = jade.Site("Acme", tagline="…", template="saas"); site.build("dist")
    jade.docs.search("idempotency")
"""

from __future__ import annotations

from typing import Any

from . import commands, docs, playbook
from .compat import TOOLKIT as __version__
from .errors import JadeError
from .harness import Harness
from .site.spec import Site

__all__ = ["Stack", "Harness", "Site", "JadeError", "docs", "playbook", "commands", "aio", "__version__"]


class Stack:
    """the SDK entry point: a harness plus helpers. Blocking; for asyncio use jade.aio.Stack."""

    def __init__(self, harness: Harness):
        self.harness = harness

    @classmethod
    def load(cls, path: str | None = None, **kw: Any) -> "Stack":
        return cls(Harness.load(path, **kw))

    @property
    def config(self):
        return self.harness.config

    @property
    def base(self):
        return self.harness.base

    @property
    def vault(self):
        return self.harness.vault

    @property
    def kit(self):
        from .resources import kit
        return kit

    @property
    def ui(self):
        from .resources import ui
        return ui

    def doctor(self) -> dict:
        return self.harness.status()

    def call(self, target: str | None, tool: str, args: dict | None = None, **kw: Any) -> Any:
        return self.harness.call(target, tool, args, **kw)

    def agent(self, name: str = "jade", *, target: str = "vault", **kw: Any):
        from .agent import Agent
        return Agent(self.harness, name, target=target, **kw)

    def run(self, command: str, **args: Any) -> Any:
        """any command by name, e.g. stack.run("site.build", dir=".", out="dist")"""
        return commands.call(command, args, commands.Context(config=str(self.config.path) if self.config.path else None, interactive=False, _h=self.harness))


from . import aio  # noqa: E402
