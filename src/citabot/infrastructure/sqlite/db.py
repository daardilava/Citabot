"""SQLite connection wrapper that doubles as the unit of work."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    vertical        TEXT NOT NULL,
    welcome_message TEXT NOT NULL,
    slot_minutes    INTEGER NOT NULL CHECK (slot_minutes > 0),
    opening_hours   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS services (
    id               INTEGER PRIMARY KEY,
    business_id      INTEGER NOT NULL REFERENCES businesses(id),
    name             TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price            TEXT,
    active           INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    phone       TEXT NOT NULL,
    name        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (business_id, phone)
);
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    contact_id      INTEGER NOT NULL UNIQUE REFERENCES contacts(id),
    mode            TEXT NOT NULL CHECK (mode IN ('bot', 'human')),
    needs_attention INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    sender          TEXT NOT NULL CHECK (sender IN ('customer', 'bot', 'agent')),
    text            TEXT NOT NULL,
    options         TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    external_id     TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
    id            INTEGER PRIMARY KEY,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    contact_id    INTEGER NOT NULL REFERENCES contacts(id),
    service_id    INTEGER NOT NULL REFERENCES services(id),
    starts_at     TEXT NOT NULL,
    ends_at       TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled', 'completed')),
    source        TEXT NOT NULL CHECK (source IN ('whatsapp', 'dashboard')),
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id          INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_appointments_time ON appointments (business_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_appointments_contact ON appointments (contact_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations (business_id, updated_at);
"""

# What a business owns besides its own row and its users. Child tables first,
# so deletes respect foreign keys.
BUSINESS_CONTENT_TABLES = ("appointments", "conversations", "contacts", "knowledge_docs", "services")


class Database:
    """One shared connection guarded by a re-entrant lock.

    `with db:` opens a transaction (nested blocks join the outer one), commits
    on success and rolls back on error. Holding the lock for the whole block
    serialises writers, which is what makes check-then-insert booking safe.
    For a multi-process deployment the same contract maps onto Postgres with
    `SELECT … FOR UPDATE` or an exclusion constraint.
    """

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._depth = 0
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring a database created by an earlier version up to the current schema."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(messages)")}
        if "external_id" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN external_id TEXT")
        # The provider's message id, unique so a redelivered webhook is stored once.
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external "
            "ON messages (external_id) WHERE external_id IS NOT NULL"
        )

    def __enter__(self) -> Database:
        self._lock.acquire()
        if self._depth == 0:
            self._conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self._depth -= 1
            if self._depth == 0:
                self._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self._lock.release()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a write statement and return the last inserted row id."""
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return cursor.lastrowid or 0

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def clear_business(self, business_id: int) -> None:
        """Delete everything a business owns, keeping the business itself and its users."""
        with self:
            self._conn.execute(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE business_id = ?)",
                (business_id,),
            )
            for table in BUSINESS_CONTENT_TABLES:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE business_id = ?", (business_id,)
                )  # fixed names

    def close(self) -> None:
        with self._lock:
            self._conn.close()
