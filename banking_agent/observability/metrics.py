"""Observability (left box #2): CPU, memory, disk utilisation, etc."""
from __future__ import annotations

import os
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

_START = time.time()


class RequestStats:
    def __init__(self) -> None:
        self.total = 0
        self.errors = 0
        self.blocked = 0
        self.latencies_ms: list[float] = []

    def record(self, status: int, latency_ms: float) -> None:
        self.total += 1
        if status >= 500:
            self.errors += 1
        if status in (401, 403, 413, 429):
            self.blocked += 1
        self.latencies_ms.append(latency_ms)
        if len(self.latencies_ms) > 2000:
            self.latencies_ms = self.latencies_ms[-1000:]

    def percentiles(self) -> dict:
        if not self.latencies_ms:
            return {"p50": 0, "p95": 0, "p99": 0}
        s = sorted(self.latencies_ms)
        pick = lambda q: round(s[min(len(s) - 1, int(q * len(s)))], 2)  # noqa: E731
        return {"p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99)}


request_stats = RequestStats()


def system_metrics() -> dict:
    data: dict = {"uptime_s": round(time.time() - _START, 1), "pid": os.getpid()}
    if psutil:
        proc = psutil.Process()
        disk_root = os.path.abspath(os.sep)
        data.update(
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=psutil.virtual_memory().percent,
            process_rss_mb=round(proc.memory_info().rss / 1e6, 1),
            disk_percent=psutil.disk_usage(disk_root).percent,
            threads=proc.num_threads(),
        )
    data["requests"] = {
        "total": request_stats.total,
        "errors_5xx": request_stats.errors,
        "blocked_by_edge_or_auth": request_stats.blocked,
        "latency_ms": request_stats.percentiles(),
    }
    return data
