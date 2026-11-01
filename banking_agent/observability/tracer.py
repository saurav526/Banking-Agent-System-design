"""Observability (left box #1): prompts, agent calls, tool calls, etc.

Every event is tagged with the current trace/session id (via contextvars),
kept in an in-memory ring buffer for the dashboard and appended to a JSONL
file that can be shipped to any log pipeline (ELK, Loki, Datadog ...).
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator

from ..config import settings

current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("session_id", default="-")
current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")


class Tracer:
    def __init__(self, path: str, max_events: int = 5000) -> None:
        self._events: deque[dict] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._path = path
        self.counters: dict[str, int] = {}

    def new_trace(self) -> str:
        tid = uuid.uuid4().hex[:16]
        current_trace_id.set(tid)
        return tid

    def event(self, kind: str, name: str, **data: Any) -> dict:
        evt = {
            "ts": time.time(),
            "trace_id": current_trace_id.get(),
            "session_id": current_session_id.get(),
            "user_id": current_user_id.get(),
            "kind": kind,  # prompt | llm_response | agent_call | tool_call | security | error ...
            "name": name,
            **data,
        }
        with self._lock:
            self._events.append(evt)
            self.counters[kind] = self.counters.get(kind, 0) + 1
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(evt, default=str) + "\n")
            except OSError:
                pass
        return evt

    @contextmanager
    def span(self, kind: str, name: str, **data: Any) -> Iterator[dict]:
        start = time.perf_counter()
        result: dict = {}
        try:
            yield result
            status = "ok"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            result["error"] = repr(exc)
            raise
        finally:
            self.event(
                kind,
                name,
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                **data,
                **result,
            )

    def recent(self, limit: int = 200, trace_id: str | None = None, session_id: str | None = None) -> list[dict]:
        with self._lock:
            items = list(self._events)
        if trace_id:
            items = [e for e in items if e["trace_id"] == trace_id]
        if session_id:
            items = [e for e in items if e["session_id"] == session_id]
        return items[-limit:]


tracer = Tracer(settings.trace_log)
