from __future__ import annotations

import json
from pathlib import Path

from .facts import Facts
from .history import History, utc_now
from .proposals import Proposals
from .summaries import Summaries


def build_export(
    history: History,
    facts: Facts,
    proposals: Proposals,
    summaries: Summaries | None = None,
) -> dict[str, object]:
    sessions: list[dict[str, object]] = []
    for session in history.list_sessions(limit=1_000_000):
        sessions.append(
            {
                "id": session["id"],
                "title": session["title"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at,
                    }
                    for message in history.messages(int(session["id"]))
                ],
            }
        )
    return {
        "format": "amadeus-export",
        "version": 1,
        "exported_at": utc_now(),
        "sessions": sessions,
        "facts": [
            {
                "id": fact.id,
                "content": fact.content,
                "source": fact.source,
                "created_at": fact.created_at,
                "updated_at": fact.updated_at,
            }
            for fact in facts.list(limit=1_000_000)
        ],
        "pending_proposals": [
            {
                "id": proposal.id,
                "content": proposal.content,
                "source": proposal.source,
                "created_at": proposal.created_at,
            }
            for proposal in proposals.pending(limit=1_000_000)
        ],
        "session_summaries": [
            {
                "session_id": summary.session_id,
                "content": summary.content,
                "through_message_id": summary.through_message_id,
                "created_at": summary.created_at,
                "updated_at": summary.updated_at,
            }
            for summary in (summaries.list(limit=1_000_000) if summaries else [])
        ],
    }


def export_json(
    history: History,
    facts: Facts,
    proposals: Proposals,
    path: Path | str,
    summaries: Summaries | None = None,
) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_export(history, facts, proposals, summaries)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
