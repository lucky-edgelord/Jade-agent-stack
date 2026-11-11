"""asyncio wrappers: the same API, awaitable. Calls run in a worker thread (the core is blocking and dependency-free).

    stack = await jade.aio.Stack.load()
    reply = await stack.agent("booker", target="base").ask("how many products?")
    async for ev in stack.agent("booker", target="base").stream("…"): ...
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class _Agent:
    def __init__(self, a: Any):
        self._a = a

    async def ask(self, message: str) -> dict:
        return await asyncio.to_thread(self._a.ask, message)

    async def stream(self, message: str) -> AsyncIterator[dict]:
        it = self._a.stream(message)
        sentinel = object()
        while True:
            ev = await asyncio.to_thread(next, it, sentinel)
            if ev is sentinel:
                return
            yield ev  # type: ignore[misc]


class Stack:
    def __init__(self, stack: Any):
        self._s = stack

    @classmethod
    async def load(cls, path: str | None = None, **kw: Any) -> "Stack":
        from . import Stack as S
        return cls(await asyncio.to_thread(S.load, path, **kw))

    async def doctor(self) -> dict:
        return await asyncio.to_thread(self._s.doctor)

    async def call(self, target: str | None, tool: str, args: dict | None = None, **kw: Any) -> Any:
        return await asyncio.to_thread(self._s.call, target, tool, args, **kw)

    async def run(self, command: str, **args: Any) -> Any:
        return await asyncio.to_thread(self._s.run, command, **args)

    def agent(self, name: str = "jade", **kw: Any) -> _Agent:
        return _Agent(self._s.agent(name, **kw))

    @property
    def sync(self) -> Any:
        return self._s
