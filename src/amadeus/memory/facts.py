from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .database import Database
from .history import _fts_query, _like_query, utc_now


@dataclass(frozen=True)
class Fact:
    id: int
    content: str
    source: str
    created_at: str
    updated_at: str


class Facts:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.conn

    def add(self, content: str, source: str = "user") -> Fact:
        content = " ".join(content.split())
        if not content:
            raise ValueError("Факт не может быть пустым")
        now = utc_now()
        cursor = self.conn.execute(
            "INSERT INTO facts (content, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (content, source, now, now),
        )
        self.conn.commit()
        return Fact(int(cursor.lastrowid), content, source, now, now)

    def get(self, fact_id: int) -> Fact | None:
        row = self.conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
        return Fact(*row) if row else None

    def list(self, limit: int = 100) -> list[Fact]:
        rows = self.conn.execute("SELECT * FROM facts ORDER BY id ASC LIMIT ?", (limit,))
        return [Fact(*row) for row in rows]

    def delete(self, fact_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_all(self) -> None:
        self.conn.execute("DELETE FROM facts")
        self.conn.commit()

    def search(self, query: str, limit: int = 5) -> list[Fact]:
        if not query.strip():
            return []
        if self.db.fts_enabled and (fts := _fts_query(query)):
            try:
                rows = self.conn.execute(
                    """
                    SELECT f.* FROM facts_fts s
                    JOIN facts f ON f.id = s.rowid
                    WHERE facts_fts MATCH ?
                    ORDER BY rank LIMIT ?
                    """,
                    (fts, limit),
                )
                return [Fact(*row) for row in rows]
            except sqlite3.OperationalError:
                pass
        rows = self.conn.execute(
            "SELECT * FROM facts WHERE content LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?",
            (_like_query(query), limit),
        )
        return [Fact(*row) for row in rows]
