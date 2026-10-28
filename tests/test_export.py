from __future__ import annotations

import json

from amadeus.memory import (
    Database,
    Facts,
    History,
    Proposals,
    Summaries,
    build_export,
    export_json,
)


def test_export_contains_sessions_facts_and_proposals(tmp_path):
    db = Database(tmp_path / "export.db")
    history = History(db)
    facts = Facts(db)
    proposals = Proposals(db, facts)
    session = history.create_session()
    history.add_message(session, "user", "Привет")
    history.add_message(session, "assistant", "Здравствуйте")
    fact = facts.add("Пользователь использует CachyOS")
    proposal = proposals.propose("Любимый редактор — neovim")
    summaries = Summaries(db)
    summaries.upsert(session, "Сводка сессии", 2)

    payload = build_export(history, facts, proposals, summaries)
    assert payload["format"] == "amadeus-export"
    assert payload["version"] == 1
    assert payload["sessions"][0]["messages"][1]["content"] == "Здравствуйте"
    assert payload["facts"][0]["id"] == fact.id
    assert payload["pending_proposals"][0]["id"] == proposal.id
    assert payload["session_summaries"][0]["content"] == "Сводка сессии"

    target = export_json(history, facts, proposals, tmp_path / "out" / "data.json", summaries)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["facts"][0]["content"] == "Пользователь использует CachyOS"
    db.close()
