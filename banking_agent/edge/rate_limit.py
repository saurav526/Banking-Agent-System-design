"""
Token-Bucket Rate Limiter Module
================================

Provides an in-memory, thread-safe token-bucket algorithm implementation used
by edge and security layers to meter request rates per client identifier (IP address,
authenticated user subject, or API key).

Key Components & Mechanics:
---------------------------
1. TokenBucketLimiter:
   - Evaluates incoming request keys against preconfigured sustained rates (`per_minute`)
     and maximum burst capacities (`burst`).
   - Maintains an in-memory table (`_buckets`) mapping identifiers to `(tokens, last_timestamp)` tuples.

2. State & Concurrency Control:
   - Uses `threading.Lock` across token evaluations and resets to maintain consistency
     under multi-threaded ASGI worker environments.
   - Leverages `time.monotonic()` to guard against system clock drift or adjustments.

3. Flow Control & Penalty Calculation (`allow`):
   - Refills tokens continuously based on elapsed time since the previous request:
     `tokens = min(capacity, tokens + elapsed * rate)`.
   - Grants access (`True, 0.0`) and decrements 1 token if `tokens >= 1`.
   - Denies access (`False, retry_after`) when depleted, returning the exact floating-point
     seconds needed to accumulate 1 full token (for populating `Retry-After` HTTP headers).

4. Maintenance:
   - `reset()`: Flushes all active bucket allocations, restoring full burst allowances.
"""
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
