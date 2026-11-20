"""SQLite storage for sessions and messages.

Every operation opens its own aiosqlite connection (aiosqlite runs sqlite3 in a
worker thread, so the event loop is never blocked). WAL mode plus busy_timeout
keeps concurrent readers and the single writer from tripping over each other.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  system_prompt TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

BUSY_TIMEOUT_MS = 5000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        # isolation_level=None: we issue BEGIN/COMMIT ourselves where a transaction is needed.
        async with aiosqlite.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            yield conn

    async def init(self) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        async with self._connect() as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.executescript(SCHEMA)

    async def ping(self) -> bool:
        try:
            async with self._connect() as conn:
                async with conn.execute("SELECT 1") as cur:
                    row = await cur.fetchone()
            return row is not None and row[0] == 1
        except Exception:
            return False

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT session_id, system_prompt, created_at, updated_at FROM sessions WHERE session_id = ?",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def recent_messages(self, session_id: str, limit: int) -> list[dict[str, str]]:
        """The last `limit` messages, oldest first, as {role, content} for the LLM."""
        if limit <= 0:
            return []
        async with self._connect() as conn:
            async with conn.execute(
                """
                SELECT role, content FROM (
                  SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Full stored history, oldest first. Metadata is attached to assistant messages only."""
        async with self._connect() as conn:
            async with conn.execute(
                "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ) as cur:
                rows = await cur.fetchall()
        messages: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            if r["role"] == "assistant" and r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            messages.append(item)
        return messages

    async def save_turn(
        self,
        session_id: str,
        system_prompt: str | None,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Upsert the session and append both messages in ONE transaction.

        Only called after the LLM succeeded, so a failed request leaves no trace.
        A None system_prompt keeps whatever prompt the session already has.
        """
        now = utc_now()
        async with self._connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await conn.execute(
                    """
                    INSERT INTO sessions (session_id, system_prompt, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                      system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt),
                      updated_at = excluded.updated_at
                    """,
                    (session_id, system_prompt, now, now),
                )
                await conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
                    (session_id, user_content, now),
                )
                await conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                    (session_id, assistant_content, json.dumps(metadata), now),
                )
                await conn.execute("COMMIT")
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
