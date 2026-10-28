from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .database import Database
from .history import utc_now


@dataclass(frozen=True)
class SessionSummary:
    session_id: int
    content: str
    through_message_id: int
    created_at: str
    updated_at: str


class Summaries:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.conn

    def get(self, session_id: int) -> SessionSummary | None:
        row = self.conn.execute(
            "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
        ).fetchone()
        return SessionSummary(*row) if row else None

    def upsert(self, session_id: int, content: str, through_message_id: int) -> SessionSummary:
        content = content.strip()
        if not content:
            raise ValueError("Сводка не может быть пустой")
        now = utc_now()
        existing = self.get(session_id)
        if existing is None:
            self.conn.execute(
                "INSERT INTO session_summaries "
                "(session_id, content, through_message_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, content, through_message_id, now, now),
            )
        else:
            self.conn.execute(
                "UPDATE session_summaries SET content = ?, through_message_id = ?, "
                "updated_at = ? WHERE session_id = ?",
                (content, through_message_id, now, session_id),
            )
        self.conn.commit()
        summary = self.get(session_id)
        assert summary is not None
        return summary

    def delete(self, session_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM session_summaries WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def list(self, limit: int = 1000) -> list[SessionSummary]:
        rows = self.conn.execute(
            "SELECT * FROM session_summaries ORDER BY session_id ASC LIMIT ?", (limit,)
        )
        return [SessionSummary(*row) for row in rows]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM session_summaries").fetchone()
        return int(row[0]) if row else 0
