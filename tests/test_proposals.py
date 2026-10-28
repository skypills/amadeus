from __future__ import annotations

import pytest

from amadeus.memory import Database, Facts, Proposals, detect_remember_request
from amadeus.memory.proposals import normalize_fact


def make_proposals(tmp_path) -> tuple[Database, Proposals, Facts]:
    db = Database(tmp_path / "proposals.db")
    facts = Facts(db)
    return db, Proposals(db, facts), facts


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Запомни, что я люблю тёмную тему", "я люблю тёмную тему"),
        ("запомни: мой редактор — neovim", "мой редактор — neovim"),
        ("Не забудь, что встреча в пятницу", "встреча в пятницу"),
        ("Пожалуйста, учти что я живу в Москве", "я живу в Москве"),
        ("remember that I use CachyOS", "I use CachyOS"),
        ("запомни это", None),
        ("Просто сообщение", None),
    ],
)
def test_detect_remember_request(text, expected):
    assert detect_remember_request(text) == expected


def test_normalize_fact():
    assert normalize_fact("  я   люблю   чай . ") == "я люблю чай"


def test_proposal_accept_moves_to_facts(tmp_path):
    db, proposals, facts = make_proposals(tmp_path)
    proposal = proposals.propose("Пользователь любит тёмную тему")
    assert [item.id for item in proposals.pending()] == [proposal.id]
    assert facts.list() == []

    fact = proposals.accept(proposal.id)

    assert fact is not None
    assert fact.content == "Пользователь любит тёмную тему"
    assert fact.source == "user_confirmed"
    assert proposals.pending() == []
    assert [item.id for item in facts.list()] == [fact.id]
    db.close()


def test_proposal_reject_and_duplicates(tmp_path):
    db, proposals, _ = make_proposals(tmp_path)
    proposal = proposals.propose("Любимый цвет — синий")
    with pytest.raises(ValueError, match="ожидает подтверждения"):
        proposals.propose("Любимый цвет — синий")
    assert proposals.reject(proposal.id)
    assert proposals.pending() == []
    db.close()


def test_proposal_rejects_existing_fact(tmp_path):
    db, proposals, facts = make_proposals(tmp_path)
    facts.add("Пользователь использует CachyOS")
    with pytest.raises(ValueError, match="уже сохранён"):
        proposals.propose("Пользователь использует CachyOS")
    db.close()


def test_accept_returns_existing_fact_without_duplicate(tmp_path):
    db, proposals, facts = make_proposals(tmp_path)
    proposal = proposals.propose("Любимый цвет — синий")
    existing = facts.add("Любимый цвет — синий")
    result = proposals.accept(proposal.id)
    assert result is not None
    assert result.id == existing.id
    assert len(facts.list()) == 1
    db.close()


def test_proposals_survive_reopen(tmp_path):
    db, proposals, _ = make_proposals(tmp_path)
    proposal = proposals.propose("Пользователь предпочитает Wayland")
    db.close()

    reopened = Database(tmp_path / "proposals.db")
    assert [item.id for item in Proposals(reopened).pending()] == [proposal.id]
    reopened.close()


def test_delete_all_clears_proposals(tmp_path):
    from amadeus.memory import History

    db, proposals, facts = make_proposals(tmp_path)
    history = History(db)
    session = history.create_session()
    history.add_message(session, "user", "привет")
    facts.add("факт")
    proposals.propose("предложение")
    history.delete_all()
    assert facts.list() == []
    assert proposals.pending() == []
    assert history.list_sessions() == []
    db.close()
