from __future__ import annotations

from amadeus.memory import Database, Facts, History, Retrieval
from amadeus.memory.history import utc_now


def make_db(tmp_path) -> Database:
    return Database(tmp_path / "memory.db")


def test_history_persists_and_resumes(tmp_path):
    db = make_db(tmp_path)
    history = History(db)
    session_id = history.create_session()
    history.add_message(session_id, "user", "Привет, меня зовут Владимир")
    history.add_message(session_id, "assistant", "Здравствуйте, Владимир")
    db.close()

    reopened = Database(tmp_path / "memory.db")
    history = History(reopened)
    latest = history.latest_session()
    assert latest is not None
    assert latest["id"] == session_id
    assert latest["title"].startswith("Привет")
    messages = history.messages(session_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content == "Здравствуйте, Владимир"
    reopened.close()


def test_history_limit_returns_tail_in_order(tmp_path):
    db = make_db(tmp_path)
    history = History(db)
    session_id = history.create_session()
    for index in range(10):
        history.add_message(session_id, "user", f"сообщение {index}")
    tail = history.messages(session_id, limit=3)
    assert [message.content for message in tail] == [
        "сообщение 7",
        "сообщение 8",
        "сообщение 9",
    ]
    db.close()


def test_search_excludes_session_and_deletes_cascade(tmp_path):
    db = make_db(tmp_path)
    history = History(db)
    first = history.create_session()
    second = history.create_session()
    history.add_message(first, "user", "любимый редактор neovim")
    history.add_message(second, "user", "любимый терминал kitty")

    hits = history.search("любимый", exclude_session=second)
    assert [hit.session_id for hit in hits] == [first]

    assert history.delete_session(first)
    assert history.messages(first) == []
    db.close()


def test_facts_crud_and_search(tmp_path):
    db = make_db(tmp_path)
    facts = Facts(db)
    fact = facts.add("Пользователь предпочитает тёмную тему")
    assert fact.id > 0
    assert facts.get(fact.id).content.startswith("Пользователь")
    assert [item.id for item in facts.search("тёмную")] == [fact.id]
    assert facts.delete(fact.id)
    assert facts.list() == []
    db.close()


def test_retrieval_renders_only_relevant_memory(tmp_path):
    db = make_db(tmp_path)
    history = History(db)
    facts = Facts(db)
    old = history.create_session()
    current = history.create_session()
    history.add_message(old, "user", "я собираю проект на Python")
    facts.add("Пользователь использует CachyOS")
    retrieval = Retrieval(history, facts)

    context = retrieval.gather("Python", exclude_session=current)
    rendered = retrieval.render(context)
    assert "Python" in rendered
    assert "CachyOS" not in rendered or "факты" in rendered
    assert context.messages[0].session_id == old
    db.close()


def test_utc_now_is_iso():
    assert "T" in utc_now()
