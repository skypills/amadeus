from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from .database import Database


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Message:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str

    def as_llm(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class SearchHit:
    message_id: int
    session_id: int
    session_title: str
    role: str
    content: str
    created_at: str


def _fts_query(text: str) -> str | None:
    terms = re.findall(r"\w+", text, flags=re.UNICODE)
    if not terms:
        return None
    return " ".join(f'"{term}"' for term in terms)


def _like_query(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class History:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.conn

    def create_session(self, title: str = "") -> int:
        now = utc_now()
        cursor = self.conn.execute(
            "INSERT INTO sessions (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_session(self, session_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()

    def latest_session(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()

    def list_sessions(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT s.*, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def add_message(self, session_id: int, role: str, content: str) -> Message:
        now = utc_now()
        cursor = self.conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        if role == "user":
            session = self.get_session(session_id)
            if session is not None and not session["title"]:
                title = " ".join(content.split())[:60]
                self.conn.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, session_id),
                )
        self.conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        self.conn.commit()
        return Message(
            id=int(cursor.lastrowid),
            session_id=session_id,
            role=role,
            content=content,
            created_at=now,
        )

    def messages(self, session_id: int, limit: int | None = None) -> list[Message]:
        if limit is None:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            )
        return [
            Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_session(self, session_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def count_messages(self, session_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def delete_all(self) -> None:
        self.conn.execute("DELETE FROM sessions")
        self.conn.execute("DELETE FROM facts")
        self.conn.execute("DELETE FROM fact_proposals")
        self.conn.execute("DELETE FROM session_summaries")
        self.conn.commit()

    def search(
        self, query: str, limit: int = 10, exclude_session: int | None = None
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        if self.db.fts_enabled and (fts := _fts_query(query)):
            sql = """
                SELECT m.id, m.session_id, s.title AS session_title, m.role,
                       m.content, m.created_at
                FROM messages_fts f
                JOIN messages m ON m.id = f.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
            """
            params: list[object] = [fts]
            if exclude_session is not None:
                sql += " AND m.session_id != ?"
                params.append(exclude_session)
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)
            try:
                rows = self.conn.execute(sql, params)
                return [SearchHit(*row) for row in rows]
            except sqlite3.OperationalError:
                pass
        sql = """
            SELECT m.id, m.session_id, s.title AS session_title, m.role,
                   m.content, m.created_at
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.content LIKE ? ESCAPE '\\'
        """
        params = [_like_query(query)]
        if exclude_session is not None:
            sql += " AND m.session_id != ?"
            params.append(exclude_session)
        sql += " ORDER BY m.id DESC LIMIT ?"
        params.append(limit)
        return [SearchHit(*row) for row in self.conn.execute(sql, params)]
