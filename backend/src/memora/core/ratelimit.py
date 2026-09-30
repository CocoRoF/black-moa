"""In-process token-bucket rate limiter (single backend process by design, see plan/25 D-22)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from memora.core.errors import RateLimited


def _disabled() -> bool:
    return os.environ.get("MEMORA_RATELIMIT_DISABLED") == "1"


@dataclass
class _Bucket:
    tokens: float
    updated: float = field(default_factory=time.monotonic)


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._last_sweep = time.monotonic()

    def check(self, key: str, limit: int, per_seconds: float) -> None:
        """Consume one token or raise RateLimited(retry_after)."""
        if _disabled():
            return
        now = time.monotonic()
        rate = limit / per_seconds
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket(tokens=float(limit), updated=now)
            self._buckets[key] = b
        else:
            b.tokens = min(float(limit), b.tokens + (now - b.updated) * rate)
            b.updated = now
        if b.tokens < 1.0:
            retry = int((1.0 - b.tokens) / rate) + 1
            raise RateLimited("too many requests", detail={"retry_after": retry})
        b.tokens -= 1.0
        if now - self._last_sweep > 300:
            self._sweep(now)

    def remaining(self, key: str, limit: int) -> int:
        b = self._buckets.get(key)
        return int(b.tokens) if b else limit

    def _sweep(self, now: float) -> None:
        stale = [k for k, b in self._buckets.items() if now - b.updated > 3600]
        for k in stale:
            self._buckets.pop(k, None)
        self._last_sweep = now


limiter = RateLimiter()
