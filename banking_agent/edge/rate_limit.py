"""Token-bucket rate limiter keyed by client IP and authenticated subject."""
from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    def __init__(self, per_minute: int, burst: int) -> None:
        self.rate = per_minute / 60.0
        self.capacity = max(burst, 1)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, round((1 - tokens) / self.rate, 2)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
