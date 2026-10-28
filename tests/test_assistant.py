from __future__ import annotations

import pytest

from amadeus.core.assistant import Assistant, AssistantError
from amadeus.core.events import EventBus
from amadeus.memory import Database
from amadeus.providers import ProviderConnectionError, ProviderStatus


class FakeProvider:
    def __init__(self, name: str = "ollama", answer: str = "Ответ") -> None:
        self.name = name
        self.answer = answer
        self.messages: list[dict[str, str]] = []
        self.fail: Exception | None = None

    def chat(self, messages, stream=True, on_chunk=None) -> str:
        self.messages = list(messages)
        if self.fail is not None:
            raise self.fail
        if on_chunk is not None:
            on_chunk(self.answer)
        return self.answer

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, "ok")


def make_assistant(tmp_path, settings) -> Assistant:
    return Assistant(
        settings,
        db=Database(tmp_path / "assistant.db"),
        events=EventBus(),
        persona_path=tmp_path / "persona.md",
    )


def test_respond_saves_history_and_uses_system_prompt(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    fake = FakeProvider(answer="Здравствуйте!")
    assistant.router.selected = lambda: fake
    assistant.router.can_fallback = lambda: False

    chunks: list[str] = []
    answer = assistant.respond("Привет", on_chunk=chunks.append)

    assert answer == "Здравствуйте!"
    assert chunks == ["Здравствуйте!"]
    messages = assistant.history.messages(assistant.session_id)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "Привет"),
        ("assistant", "Здравствуйте!"),
    ]
    assert fake.messages[0]["role"] == "system"
    assert "Amadeus" in fake.messages[0]["content"]
    assert fake.messages[-1] == {"role": "user", "content": "Привет"}
    assistant.close()


def test_context_keeps_previous_messages(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    fake = FakeProvider()
    assistant.router.selected = lambda: fake
    assistant.router.can_fallback = lambda: False

    assistant.respond("Первое")
    assistant.respond("Второе")

    assert [m["content"] for m in fake.messages[1:]] == ["Первое", "Ответ", "Второе"]
    assistant.close()


def test_fallback_to_cloud_is_announced(tmp_path, settings):
    settings.set("provider.allow_cloud", True)
    assistant = make_assistant(tmp_path, settings)
    local = FakeProvider()
    local.fail = ProviderConnectionError("локальная недоступна")
    cloud = FakeProvider(name="cloud", answer="облачный ответ")
    assistant.router.selected = lambda: local
    assistant.router.can_fallback = lambda: True
    assistant.router.cloud_provider = lambda: cloud
    events = []
    assistant.events.subscribe(events.append)

    answer = assistant.respond("Вопрос")

    assert answer == "облачный ответ"
    assert any(event.kind == "fallback" for event in events)
    assert any(event.kind == "cloud" for event in events)
    assert len(assistant.history.messages(assistant.session_id)) == 2
    assistant.close()


def test_cloud_privacy_filters_context(tmp_path, settings):
    settings.set("provider.allow_cloud", True)
    assistant = make_assistant(tmp_path, settings)
    local = FakeProvider(answer="секретная история")
    assistant.router.selected = lambda: local
    assistant.router.can_fallback = lambda: False
    assistant.respond("Старый вопрос")
    assistant.facts.add("любимый цвет синий")

    cloud = FakeProvider(name="cloud", answer="ответ облака")
    assistant.router.selected = lambda: cloud

    assistant.respond("Какой мой любимый цвет?")
    sent = "\n".join(message["content"] for message in cloud.messages)
    assert "секретная история" not in sent
    assert "любимый цвет синий" not in sent
    assert [m["role"] for m in cloud.messages] == ["system", "user"]

    settings.set("privacy.send_history_to_cloud", True)
    settings.set("privacy.send_facts_to_cloud", True)
    assistant.respond("Какой мой любимый цвет?")
    sent = "\n".join(message["content"] for message in cloud.messages)
    assert "секретная история" in sent
    assert "любимый цвет синий" in sent
    assistant.close()


def test_provider_error_becomes_assistant_error(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    fake = FakeProvider()
    fake.fail = ProviderConnectionError("нет связи")
    assistant.router.selected = lambda: fake
    assistant.router.can_fallback = lambda: False

    with pytest.raises(AssistantError, match="нет связи"):
        assistant.respond("Вопрос")

    messages = assistant.history.messages(assistant.session_id)
    assert [m.role for m in messages] == ["user"]
    assistant.close()


def test_empty_answer_is_error_and_not_saved(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    fake = FakeProvider(answer="   ")
    assistant.router.selected = lambda: fake
    assistant.router.can_fallback = lambda: False

    with pytest.raises(AssistantError, match="пустой"):
        assistant.respond("Вопрос")
    assert [m.role for m in assistant.history.messages(assistant.session_id)] == ["user"]
    assistant.close()


def test_empty_message_rejected(tmp_path, settings):
    assistant = make_assistant(tmp_path, settings)
    with pytest.raises(AssistantError):
        assistant.respond("   ")
    assistant.close()


def test_cloud_disabled_is_reported(tmp_path, settings):
    settings.set("provider.name", "cloud")
    settings.set("provider.allow_cloud", False)
    assistant = make_assistant(tmp_path, settings)
    with pytest.raises(AssistantError, match="Облачный провайдер отключён"):
        assistant.respond("Вопрос")
    assistant.close()
