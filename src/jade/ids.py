"""UUIDv7 (time-ordered) for idempotency keys and run ids."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> str:
    ms = int(time.time() * 1000)
    r = int.from_bytes(os.urandom(10), "big")
    v = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | ((r >> 62) & 0xFFF) << 64 | 0b10 << 62 | (r & ((1 << 62) - 1))
    return str(uuid.UUID(int=v))
