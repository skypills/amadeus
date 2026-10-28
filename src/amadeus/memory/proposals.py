from __future__ import annotations

import re
from dataclasses import dataclass

from .database import Database
from .facts import Fact, Facts, normalize_fact_content
from .history import utc_now

GENERIC_CONTENT = {"это", "это.", "всё", "все", "это всё", "this", "that"}

REMEMBER_PATTERNS = (
    re.compile(
        r"^\s*(?:пожалуйста,?\s*)?"
        r"(?:запомни|запомните|не забудь|не забывай|учти)"
        r"(?:\s*,?\s*что)?\s*[:\-—]?\s*(?P<content>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:please\s+)?remember(?:\s+that)?\s*[:\-—]?\s*(?P<content>.+)$",
        re.IGNORECASE,
    ),
)


def normalize_fact(content: str) -> str:
    return normalize_fact_content(content)


def detect_remember_request(text: str) -> str | None:
    for pattern in REMEMBER_PATTERNS:
        match = pattern.match(text)
        if match is None:
            continue
        content = normalize_fact(match.group("content"))
        if len(content) < 3 or content.casefold() in GENERIC_CONTENT:
            return None
        return content
    return None


@dataclass(frozen=True)
class FactProposal:
    id: int
    content: str
    source: str
    created_at: str


class Proposals:
    def __init__(self, db: Database, facts: Facts | None = None) -> None:
        self.db = db
        self.facts = facts or Facts(db)

    def propose(self, content: str, source: str = "user_request") -> FactProposal:
        content = normalize_fact(content)
        if not content:
            raise ValueError("Факт не может быть пустым")
        if self.facts.find_exact(content) is not None:
            raise ValueError("Этот факт уже сохранён.")
        for proposal in self.pending(limit=1000):
            if proposal.content.casefold() == content.casefold():
                raise ValueError("Такой факт уже ожидает подтверждения.")
        now = utc_now()
        cursor = self.db.conn.execute(
            "INSERT INTO fact_proposals (content, source, created_at) VALUES (?, ?, ?)",
            (content, source, now),
        )
        self.db.conn.commit()
        return FactProposal(int(cursor.lastrowid), content, source, now)

    def get(self, proposal_id: int) -> FactProposal | None:
        row = self.db.conn.execute(
            "SELECT * FROM fact_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        return FactProposal(*row) if row else None

    def pending(self, limit: int = 50) -> list[FactProposal]:
        rows = self.db.conn.execute(
            "SELECT * FROM fact_proposals ORDER BY id ASC LIMIT ?", (limit,)
        )
        return [FactProposal(*row) for row in rows]

    def accept(self, proposal_id: int) -> Fact | None:
        proposal = self.get(proposal_id)
        if proposal is None:
            return None
        existing = self.facts.find_exact(proposal.content)
        if existing is None:
            fact = self.facts.add(proposal.content, source="user_confirmed")
        else:
            fact = existing
        self.db.conn.execute("DELETE FROM fact_proposals WHERE id = ?", (proposal_id,))
        self.db.conn.commit()
        return fact

    def reject(self, proposal_id: int) -> bool:
        cursor = self.db.conn.execute("DELETE FROM fact_proposals WHERE id = ?", (proposal_id,))
        self.db.conn.commit()
        return cursor.rowcount > 0

    def delete_all(self) -> None:
        self.db.conn.execute("DELETE FROM fact_proposals")
        self.db.conn.commit()

    def count(self) -> int:
        row = self.db.conn.execute("SELECT COUNT(*) FROM fact_proposals").fetchone()
        return int(row[0]) if row else 0
