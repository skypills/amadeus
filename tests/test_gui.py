from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from amadeus.core.assistant import Assistant  # noqa: E402
from amadeus.core.events import EventBus  # noqa: E402
from amadeus.memory import Database  # noqa: E402
from amadeus.ui.chat import ChatView  # noqa: E402
from amadeus.ui.settings import SettingsDialog  # noqa: E402
from amadeus.ui.window import ChatWorker, MainWindow, VoiceWorker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class FakeAssistant:
    def __init__(self, answer: str = "привет", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.events = EventBus()
        self.session_id = None
        self.closed = False

    def resume(self, session_id: int) -> bool:
        self.session_id = session_id
        return True

    def respond(
        self,
        text: str,
        stream: bool = True,
        on_chunk=None,
        external_context: str = "",
    ) -> str:
        if self.error is not None:
            raise self.error
        for part in self.answer:
            if on_chunk is not None:
                on_chunk(part)
        return self.answer

    def close(self) -> None:
        self.closed = True


def test_chat_view_streaming(qapp):
    view = ChatView()
    bubble = view.add_message("assistant", "")
    view.update_message(bubble, "привет")
    assert bubble.text() == "привет"
    view.clear()
    assert view.is_empty()


def test_chat_worker_streams_and_closes(qapp, settings, tmp_path):
    fake = FakeAssistant()
    worker = ChatWorker(
        settings,
        session_id=7,
        text="hi",
        persona_path=tmp_path / "persona.md",
        assistant_factory=lambda: fake,
    )
    chunks: list[str] = []
    finished: list[str] = []
    errors: list[str] = []
    worker.chunk.connect(chunks.append)
    worker.finished_text.connect(finished.append)
    worker.failed.connect(errors.append)

    worker.run()

    assert chunks == list("привет")
    assert finished == ["привет"]
    assert errors == []
    assert fake.session_id == 7
    assert fake.closed


def test_chat_worker_reports_error(qapp, settings, tmp_path):
    fake = FakeAssistant(error=RuntimeError("нет связи"))
    worker = ChatWorker(
        settings,
        1,
        "hi",
        tmp_path / "persona.md",
        assistant_factory=lambda: fake,
    )
    errors: list[str] = []
    worker.failed.connect(errors.append)
    worker.run()
    assert errors == ["нет связи"]
    assert fake.closed


def test_chat_worker_cancels(qapp, settings, tmp_path):
    fake = FakeAssistant()
    worker = ChatWorker(
        settings,
        1,
        "hi",
        tmp_path / "persona.md",
        assistant_factory=lambda: fake,
    )
    cancelled: list[bool] = []
    finished: list[str] = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.finished_text.connect(finished.append)
    worker.cancel()

    worker.run()

    assert cancelled == [True]
    assert finished == []
    assert fake.closed


class FakeVoicePipeline:
    def transcribe(self, path):
        self.transcribed_path = path
        return "распознанный текст"

    def speak(self, text):
        self.spoken_text = text
        return Path("/tmp/fake-speech.wav")


def test_voice_worker_transcribes(qapp):
    pipeline = FakeVoicePipeline()
    worker = VoiceWorker(pipeline, "transcribe", "/tmp/audio.wav")
    result: list[str] = []
    worker.transcribed.connect(result.append)
    worker.run()
    assert result == ["распознанный текст"]
    assert str(pipeline.transcribed_path) == "/tmp/audio.wav"


def test_voice_worker_speaks(qapp):
    pipeline = FakeVoicePipeline()
    worker = VoiceWorker(pipeline, "speak", "привет")
    result: list[str] = []
    worker.spoke.connect(result.append)
    worker.run()
    assert result == ["/tmp/fake-speech.wav"]
    assert pipeline.spoken_text == "привет"


def test_settings_dialog_saves(qapp, settings, tmp_path):
    dialog = SettingsDialog(settings, tmp_path / "persona.md")
    dialog.model_edit.setText("gui-test:1b")
    dialog.stream_check.setChecked(False)
    dialog.verbosity_spin.setValue(0.9)
    dialog.stt_model_edit.setText("/tmp/whisper.bin")
    dialog.auto_speak_check.setChecked(True)
    dialog._save()

    assert settings.get("ollama.model") == "gui-test:1b"
    assert settings.get("ollama.stream") is False
    assert settings.get("personality.verbosity") == 0.9
    assert settings.get("voice.stt_model") == "/tmp/whisper.bin"
    assert settings.get("voice.auto_speak") is True


def test_main_window_smoke(qapp, settings, tmp_path):
    assistant = Assistant(
        settings,
        db=Database(tmp_path / "gui.db"),
        persona_path=tmp_path / "persona.md",
    )
    window = MainWindow(assistant, settings, auto_status=False)
    assert window.windowTitle().startswith("Amadeus")
    assert window.history_list.count() >= 1
    assert "Микрофон" in window.mic_label.text()
    window.close()
    assistant.close()


def test_chat_worker_web_search_passes_sources(qapp, settings, tmp_path, monkeypatch):
    from amadeus.tools import SearchResult

    class FakeSearch:
        def search(self, query):
            return [SearchResult("T", "https://example.com", "S", "")]

    monkeypatch.setattr(
        "amadeus.ui.window.WebSearch.from_settings",
        lambda settings: FakeSearch(),
    )
    fake = FakeAssistant(answer="ответ")
    captured = {}

    def respond(text, stream=True, on_chunk=None, external_context=""):
        captured["context"] = external_context
        if on_chunk:
            on_chunk("ответ")
        return "ответ"

    fake.respond = respond
    worker = ChatWorker(
        settings,
        1,
        "запрос",
        tmp_path / "persona.md",
        assistant_factory=lambda: fake,
        web_query=True,
    )
    sources = []
    worker.sources.connect(sources.append)
    worker.run()
    assert sources[0][0].url == "https://example.com"
    assert "https://example.com" in captured["context"]
    assert "НЕДОВЕРЕННЫЕ" in captured["context"]
