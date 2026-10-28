from __future__ import annotations

import pytest

from amadeus.core.assistant import Assistant, AssistantError
from amadeus.core.events import EventBus
from amadeus.memory import Database, Facts, History, Summaries
from amadeus.providers.base import ProviderStatus


class SummaryProvider:
    name = "ollama"

    def __init__(self, answer: str = "Краткая сводка диалога.") -> None:
        self.answer = answer
        self.messages: list[dict[str, str]] = []

    def chat(self, messages, stream=True, on_chunk=None) -> str:
        self.messages = list(messages)
        return self.answer

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, "ok")


def make_assistant(tmp_path, settings) -> Assistant:
    return Assistant(
        settings,
        db=Database(tmp_path / "summaries.db"),
        events=EventBus(),
        persona_path=tmp_path / "persona.md",
    )


def test_summaries_crud_and_cascade(tmp_path):
    db = Database(tmp_path / "summaries.db")
    history = History(db)
    summaries = Summaries(db)
    session = history.create_session()
    history.add_message(session, "user", "привет")
    summary = summaries.upsert(session, "сводка", 1)
    assert summary.content == "сводка"
    assert summaries.get(session).through_message_id == 1
    updated = summaries.upsert(session, "новая сводка", 2)
    assert updated.content == "новая сводка"
    assert summaries.count() == 1
    history.delete_session(session)
    assert summaries.get(session) is None
    db.close()


def test_fact_update_and_duplicate_check(tmp_path):
    db = Database(tmp_path / "facts.db")
    facts = Facts(db)
    first = facts.add("любит чай")
    second = facts.add("любит кофе")
    assert facts.update(first.id, "любит зелёный чай").content == "любит зелёный чай"
    with pytest.raises(ValueError, match="уже сохранён"):
        facts.update(first.id, "любит кофе")
    assert facts.update(999, "нет") is None
    assert second.content == "любит кофе"
    db.close()


def test_summarize_session_saves_and_uses_provider(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    assistant.history.add_message(assistant.session_id, "user", "Меня зовут Владимир")
    assistant.history.add_message(assistant.session_id, "assistant", "Запомнил, чем помочь?")
    provider = SummaryProvider("Пользователь представился как Владимир.")
    assistant.router.selected = lambda: provider
    events = []
    assistant.events.subscribe(events.append)

    summary = assistant.summarize_session()

    assert summary.content == "Пользователь представился как Владимир."
    assert summary.through_message_id == 2
    assert assistant.summaries.get(assistant.session_id) == summary
    assert "Меня зовут Владимир" in provider.messages[-1]["content"]
    assert any(event.kind == "memory" for event in events)
    assistant.close()


def test_summary_included_when_history_truncated(tmp_path, settings):
    settings.set("generation.history_limit", 2)
    assistant = make_assistant(tmp_path, settings)
    for index in range(4):
        assistant.history.add_message(assistant.session_id, "user", f"старое {index}")
    assistant.summaries.upsert(assistant.session_id, "СТАРАЯ СВОДКА", 2)
    provider = SummaryProvider("ответ")
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False

    assistant.respond("новый вопрос")

    system = provider.messages[0]["content"]
    assert "СТАРАЯ СВОДКА" in system
    assert "Сводка предыдущей части" in system
    assistant.close()


def test_summary_not_included_without_truncation(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    assistant.history.add_message(assistant.session_id, "user", "короткий диалог")
    assistant.summaries.upsert(assistant.session_id, "НЕ ДОЛЖНА БЫТЬ", 1)
    provider = SummaryProvider("ответ")
    assistant.router.selected = lambda: provider
    assistant.router.can_fallback = lambda: False

    assistant.respond("вопрос")

    assert "НЕ ДОЛЖНА БЫТЬ" not in provider.messages[0]["content"]
    assistant.close()


def test_cloud_summary_requires_privacy_permission(tmp_path, settings):
    settings.set("provider.name", "cloud")
    settings.set("provider.allow_cloud", True)
    assistant = make_assistant(tmp_path, settings)
    assistant.history.add_message(assistant.session_id, "user", "привет")
    provider = SummaryProvider()
    provider.name = "cloud"
    assistant.router.selected = lambda: provider

    with pytest.raises(AssistantError, match="send_history_to_cloud"):
        assistant.summarize_session()
    assert assistant.summaries.get(assistant.session_id) is None

    settings.set("privacy.send_history_to_cloud", True)
    summary = assistant.summarize_session()
    assert summary.content == provider.answer
    assistant.close()
