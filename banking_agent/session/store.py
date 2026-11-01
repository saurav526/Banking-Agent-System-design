"""Session Store: conversation history + inter-agent shared state (SQLite).

Swap for Redis/Postgres in production by re-implementing this interface.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from ..config import settings


class SessionStore:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    created_at REAL, updated_at REAL);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
                    agent TEXT, content TEXT, ts REAL);
                CREATE TABLE IF NOT EXISTS shared_state (
                    session_id TEXT, key TEXT, value TEXT, updated_by TEXT, ts REAL,
                    PRIMARY KEY (session_id, key));
                """
            )

    # ---- sessions ----
    def create_session(self, user_id: str) -> str:
        sid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (sid, user_id, now, now))
        return sid

    def get_owner(self, session_id: str) -> str | None:
        row = self._conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return row["user_id"] if row else None

    def list_sessions(self, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- conversation history ----
    def append(self, session_id: str, role: str, content: str, agent: str = "") -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages(session_id, role, agent, content, ts) VALUES (?,?,?,?,?)",
                (session_id, role, agent, content, now),
            )
            self._conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))

    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, agent, content, ts FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---- inter-agent shared state ----
    def set_state(self, session_id: str, key: str, value, updated_by: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO shared_state VALUES (?,?,?,?,?)",
                (session_id, key, json.dumps(value, default=str), updated_by, time.time()),
            )

    def get_state(self, session_id: str, key: str | None = None):
        if key is not None:
            row = self._conn.execute(
                "SELECT value FROM shared_state WHERE session_id=? AND key=?", (session_id, key)
            ).fetchone()
            return json.loads(row["value"]) if row else None
        rows = self._conn.execute(
            "SELECT key, value, updated_by FROM shared_state WHERE session_id=?", (session_id,)
        ).fetchall()
        return {r["key"]: {"value": json.loads(r["value"]), "updated_by": r["updated_by"]} for r in rows}


session_store = SessionStore(settings.session_db)
