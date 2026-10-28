from __future__ import annotations

import argparse
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.assistant import Assistant
from ..core.events import EventBus
from ..logging_setup import configure_logging
from ..memory import Database
from ..security import PermissionDenied
from ..settings import ConfigError, Settings
from ..storage import paths
from ..tools import ToolError, WebSearch, render_results, render_sources
from ..voice import VoiceError, VoicePipeline
from .chat import ChatInput, ChatView, MessageBubble
from .settings import SettingsDialog

USER_ROLE = Qt.ItemDataRole.UserRole


class GenerationCancelled(Exception):
    pass


class ChatWorker(QThread):
    chunk = Signal(str)
    sources = Signal(object)
    finished_text = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    notice = Signal(str)

    def __init__(
        self,
        settings: Settings,
        session_id: int,
        text: str,
        persona_path: Path,
        assistant_factory=None,
        web_query: bool = False,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_id = session_id
        self.text = text
        self.persona_path = persona_path
        self.web_query = web_query
        self._assistant_factory = assistant_factory
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        assistant = None
        try:
            if self._assistant_factory is not None:
                assistant = self._assistant_factory()
            else:
                assistant = Assistant(
                    self.settings,
                    db=Database(),
                    events=EventBus(),
                    persona_path=self.persona_path,
                )
            assistant.events.subscribe(lambda event: self.notice.emit(event.message))
            if not assistant.resume(self.session_id):
                raise RuntimeError("Текущая сессия не найдена.")
            stream = bool(self.settings.get("ollama.stream", True))
            external_context = ""
            if self.web_query:
                search = WebSearch.from_settings(self.settings)
                results = search.search(self.text)
                self.sources.emit(results)
                external_context = render_results(results)

            def on_chunk(text: str) -> None:
                if self._cancel.is_set():
                    raise GenerationCancelled
                self.chunk.emit(text)

            answer = assistant.respond(
                self.text,
                stream=stream,
                on_chunk=on_chunk,
                external_context=external_context,
            )
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            self.finished_text.emit(answer)
        except GenerationCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - ошибка должна попасть в UI
            self.failed.emit(str(exc))
        finally:
            if assistant is not None:
                assistant.close()


class VoiceWorker(QThread):
    transcribed = Signal(str)
    spoke = Signal(str)
    failed = Signal(str)

    def __init__(self, pipeline: VoicePipeline, mode: str, payload: str) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.mode = mode
        self.payload = payload

    def run(self) -> None:
        try:
            if self.mode == "transcribe":
                text = self.pipeline.transcribe(Path(self.payload))
                self.transcribed.emit(text)
            elif self.mode == "speak":
                path = self.pipeline.speak(self.payload)
                self.spoke.emit(str(path))
            else:
                raise RuntimeError(f"Неизвестный режим голоса: {self.mode}")
        except Exception as exc:  # noqa: BLE001 - ошибка должна попасть в UI
            self.failed.emit(str(exc))


class SummaryWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        session_id: int,
        persona_path: Path,
        assistant_factory=None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_id = session_id
        self.persona_path = persona_path
        self._assistant_factory = assistant_factory

    def run(self) -> None:
        assistant = None
        try:
            if self._assistant_factory is not None:
                assistant = self._assistant_factory()
            else:
                assistant = Assistant(
                    self.settings,
                    db=Database(),
                    events=EventBus(),
                    persona_path=self.persona_path,
                )
            if not assistant.resume(self.session_id):
                raise RuntimeError("Текущая сессия не найдена.")
            summary = assistant.summarize_session()
            self.done.emit(summary.content)
        except Exception as exc:  # noqa: BLE001 - ошибка должна попасть в UI
            self.failed.emit(str(exc))
        finally:
            if assistant is not None:
                assistant.close()


class StatusWorker(QThread):
    result = Signal(bool, str, object)

    def __init__(self, assistant: Assistant) -> None:
        super().__init__()
        self.assistant = assistant

    def run(self) -> None:
        try:
            status = self.assistant.provider_status()
        except Exception as exc:  # noqa: BLE001 - статус не должен ронять поток
            self.result.emit(False, str(exc), ())
            return
        self.result.emit(status.ok, status.detail, status.models)


class MainWindow(QMainWindow):
    def __init__(
        self,
        assistant: Assistant,
        settings: Settings,
        auto_status: bool = True,
        voice_pipeline: VoicePipeline | None = None,
    ) -> None:
        super().__init__()
        self.assistant = assistant
        self.settings = settings
        self.voice = voice_pipeline or VoicePipeline(settings)
        self._voice_status: dict[str, tuple[bool, str]] = {}
        self._voice_worker: VoiceWorker | None = None
        self._summary_worker: SummaryWorker | None = None
        self._worker: ChatWorker | None = None
        self._status_worker: StatusWorker | None = None
        self._stream_bubble: MessageBubble | None = None
        self._stream_text = ""
        self._last_user_text = ""
        self._busy = False
        self._auto_status = auto_status
        self._search_query = ""

        self.setWindowTitle("Amadeus")
        self.resize(1080, 760)
        self._build_ui()
        self._build_menu()
        self._apply_style()
        self._load_session(self.assistant.session_id)
        self._refresh_history()
        self._refresh_facts()
        self._refresh_voice_status()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(60_000)
        self._status_timer.timeout.connect(self._refresh_status)
        if auto_status:
            self._status_timer.start()
            QTimer.singleShot(0, self._refresh_status)

        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(500)
        self._voice_timer.timeout.connect(self._update_voice_buttons)
        self._voice_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.chat = ChatView()
        layout.addWidget(self.chat, 1)

        voice_row = QHBoxLayout()
        self.record_button = QPushButton("Записать")
        self.record_button.clicked.connect(self._toggle_recording)
        self.cancel_record_button = QPushButton("Отменить запись")
        self.cancel_record_button.setEnabled(False)
        self.cancel_record_button.clicked.connect(self._cancel_recording)
        self.speak_button = QPushButton("Озвучить")
        self.speak_button.clicked.connect(self._speak_last)
        self.stop_speak_button = QPushButton("Стоп TTS")
        self.stop_speak_button.setEnabled(False)
        self.stop_speak_button.clicked.connect(self._stop_speaking)
        self.voice_status_label = QLabel()
        voice_row.addWidget(self.record_button)
        voice_row.addWidget(self.cancel_record_button)
        voice_row.addWidget(self.speak_button)
        voice_row.addWidget(self.stop_speak_button)
        voice_row.addStretch(1)
        voice_row.addWidget(self.voice_status_label)
        layout.addLayout(voice_row)

        row = QHBoxLayout()
        self.input = ChatInput()
        self.input.submitted.connect(self._send)
        row.addWidget(self.input, 1)

        buttons = QVBoxLayout()
        self.send_button = QPushButton("Отправить")
        self.send_button.clicked.connect(self._send)
        self.stop_button = QPushButton("Остановить")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_generation)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.stop_button)
        row.addLayout(buttons)
        layout.addLayout(row)
        self.setCentralWidget(central)

        dock = QDockWidget("Память", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        dock.setMinimumWidth(300)
        self._dock = dock
        tabs = QTabWidget()

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(6, 6, 6, 6)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Поиск по истории… (Enter)")
        self.history_search.returnPressed.connect(lambda: self._refresh_history())
        self.history_search.textChanged.connect(self._on_search_changed)
        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._on_history_item)
        self.history_list.itemActivated.connect(self._on_history_item)
        history_buttons = QHBoxLayout()
        self.new_button = QPushButton("Новая")
        self.new_button.clicked.connect(self._new_session)
        self.summary_button = QPushButton("Сводка")
        self.summary_button.clicked.connect(self._summarize_session)
        self.delete_session_button = QPushButton("Удалить")
        self.delete_session_button.clicked.connect(self._delete_session)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(lambda: self._refresh_history())
        history_buttons.addWidget(self.new_button)
        history_buttons.addWidget(self.summary_button)
        history_buttons.addWidget(self.delete_session_button)
        history_buttons.addWidget(refresh_button)
        history_layout.addWidget(self.history_search)
        history_layout.addWidget(self.history_list, 1)
        history_layout.addLayout(history_buttons)
        tabs.addTab(history_tab, "История")

        facts_tab = QWidget()
        facts_layout = QVBoxLayout(facts_tab)
        facts_layout.setContentsMargins(6, 6, 6, 6)
        self.facts_list = QListWidget()
        self.facts_list.currentItemChanged.connect(lambda *_: self._update_fact_buttons())
        facts_buttons = QHBoxLayout()
        add_fact_button = QPushButton("Добавить")
        add_fact_button.clicked.connect(self._add_fact)
        self.edit_fact_button = QPushButton("Изменить")
        self.edit_fact_button.clicked.connect(self._edit_fact)
        self.delete_fact_button = QPushButton("Удалить")
        self.delete_fact_button.clicked.connect(self._delete_fact)
        self.accept_fact_button = QPushButton("Принять")
        self.accept_fact_button.clicked.connect(self._accept_fact)
        self.reject_fact_button = QPushButton("Отклонить")
        self.reject_fact_button.clicked.connect(self._reject_fact)
        refresh_facts_button = QPushButton("Обновить")
        refresh_facts_button.clicked.connect(self._refresh_facts)
        facts_buttons.addWidget(add_fact_button)
        facts_buttons.addWidget(self.edit_fact_button)
        facts_buttons.addWidget(self.delete_fact_button)
        facts_buttons.addWidget(self.accept_fact_button)
        facts_buttons.addWidget(self.reject_fact_button)
        facts_buttons.addWidget(refresh_facts_button)
        facts_layout.addWidget(self.facts_list, 1)
        facts_layout.addLayout(facts_buttons)
        tabs.addTab(facts_tab, "Факты")

        dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [340], Qt.Orientation.Horizontal)

        self.status_label = QLabel("Модель: проверка…")
        self.cloud_label = QLabel()
        self.mic_label = QLabel("Микрофон: проверка…")
        self.statusBar().addPermanentWidget(self.cloud_label)
        self.statusBar().addPermanentWidget(self.mic_label)
        self.statusBar().addPermanentWidget(self.status_label)
        self._update_cloud_label()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        export_action = QAction("Экспорт данных…", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_data)
        delete_all_action = QAction("Удалить все данные…", self)
        delete_all_action.triggered.connect(self._delete_all)
        quit_action = QAction("Выход", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(export_action)
        file_menu.addAction(delete_all_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("Инструменты")
        sysinfo_action = QAction("Системная информация", self)
        sysinfo_action.triggered.connect(self._show_system_info)
        notify_action = QAction("Уведомление…", self)
        notify_action.triggered.connect(self._send_notification_dialog)
        open_action = QAction("Запустить приложение…", self)
        open_action.triggered.connect(self._launch_application_dialog)
        web_action = QAction("Веб-поиск…", self)
        web_action.triggered.connect(self._web_search)
        tools_menu.addAction(web_action)
        tools_menu.addSeparator()
        tools_menu.addAction(sysinfo_action)
        tools_menu.addAction(notify_action)
        tools_menu.addAction(open_action)
        tools_menu.addSeparator()
        system_menu = tools_menu.addMenu("Системные действия")
        copy_action = QAction("Скопировать последний ответ", self)
        copy_action.triggered.connect(self._copy_last_answer)
        screenshot_action = QAction("Скриншот", self)
        screenshot_action.triggered.connect(self._take_screenshot)
        volume_action = QAction("Громкость…", self)
        volume_action.triggered.connect(self._set_volume_dialog)
        media_menu = system_menu.addMenu("Медиа")
        for label, action_name in (
            ("Play/Pause", "play-pause"),
            ("Следующий", "next"),
            ("Предыдущий", "previous"),
            ("Стоп", "stop"),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, name=action_name: self._media_action(name)
            )
            media_menu.addAction(action)
        url_action = QAction("Открыть URL…", self)
        url_action.triggered.connect(self._open_url_dialog)
        system_menu.addAction(copy_action)
        system_menu.addAction(screenshot_action)
        system_menu.addAction(volume_action)
        system_menu.addAction(url_action)

        settings_menu = self.menuBar().addMenu("Настройки")
        prefs_action = QAction("Параметры…", self)
        prefs_action.setShortcut(QKeySequence("Ctrl+,"))
        prefs_action.triggered.connect(self._open_settings)
        settings_menu.addAction(prefs_action)

        help_menu = self.menuBar().addMenu("Справка")
        about_action = QAction("Об Amadeus", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QFrame#bubbleUser {
                background-color: rgba(70, 130, 220, 45);
                border-radius: 10px;
            }
            QFrame#bubbleAssistant {
                background-color: rgba(120, 120, 120, 35);
                border-radius: 10px;
            }
            QLabel#bubbleRole {
                color: #6b7280;
                font-weight: 600;
            }
            """
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.history_list.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        self.summary_button.setEnabled(not busy)
        self.delete_session_button.setEnabled(not busy)
        self.history_search.setEnabled(not busy)
        self._update_voice_buttons()
        if not busy:
            self.input.setFocus()

    def _send(self) -> None:
        if self._busy or (self._worker is not None and self._worker.isRunning()):
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self._start_generation(text, web_query=False)

    def _web_search(self) -> None:
        if self._busy or (self._worker is not None and self._worker.isRunning()):
            return
        query, ok = QInputDialog.getText(self, "Веб-поиск", "Поисковый запрос:")
        if not ok or not query.strip():
            return
        self._start_generation(query.strip(), web_query=True)

    def _start_generation(self, text: str, web_query: bool) -> None:
        self._last_user_text = text
        self.chat.add_message("user", text)
        self._stream_bubble = self.chat.add_message("assistant", "…")
        self._stream_text = ""
        self._set_busy(True)
        self.statusBar().showMessage("Поиск в интернете…" if web_query else "Генерация…")

        worker = ChatWorker(
            self.settings,
            self.assistant.session_id,
            text,
            self.assistant.persona_path,
            web_query=web_query,
        )
        worker.chunk.connect(self._on_chunk)
        worker.sources.connect(self._on_web_sources)
        worker.finished_text.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.notice.connect(self._on_notice)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        self._worker = worker
        worker.start()

    def _on_web_sources(self, results: object) -> None:
        items = list(results) if isinstance(results, list) else []
        if not items:
            return
        self.chat.add_message(
            "tool",
            "Источники из интернета (недоверенные данные):\n\n" + render_sources(items),
        )
        self.statusBar().showMessage(f"Найдено источников: {len(items)}", 8000)

    def _stop_generation(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage("Останавливаю генерацию…")

    def _on_chunk(self, text: str) -> None:
        self._stream_text += text
        if self._stream_bubble is not None:
            self.chat.update_message(self._stream_bubble, self._stream_text)

    def _on_finished(self, answer: str) -> None:
        self._stream_text = answer or self._stream_text
        if self._stream_bubble is not None:
            self._stream_bubble.set_text(self._stream_text or "(пустой ответ)")
        self._finish_generation()
        self._refresh_history()
        self._refresh_status()
        tts_ok = self._voice_status.get("tts", (False, ""))[0]
        player_ok = self._voice_status.get("player", (False, ""))[0]
        if bool(self.settings.get("voice.auto_speak", False)) and tts_ok and player_ok:
            self._speak_text(answer)
        self._maybe_remember(self._last_user_text)

    def _on_failed(self, message: str) -> None:
        if self._stream_bubble is not None:
            prefix = f"{self._stream_text}\n\n" if self._stream_text.strip() else ""
            self._stream_bubble.set_text(f"{prefix}Ошибка: {message}")
        self.statusBar().showMessage(f"Ошибка: {message}", 15_000)
        self._finish_generation()
        self._refresh_history()

    def _on_cancelled(self) -> None:
        if self._stream_bubble is not None:
            text = self._stream_text.strip()
            self._stream_bubble.set_text(f"{text}\n\n[Остановлено]" if text else "[Остановлено]")
        self.statusBar().showMessage("Генерация остановлена.", 8000)
        self._finish_generation()
        self._refresh_history()

    def _on_notice(self, message: str) -> None:
        self.statusBar().showMessage(message, 15_000)

    def _finish_generation(self) -> None:
        self._stream_bubble = None
        self._stream_text = ""
        self._set_busy(False)

    def _on_worker_finished(self, worker: ChatWorker) -> None:
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        if self._busy:
            self._set_busy(False)

    def _maybe_remember(self, text: str) -> None:
        if not text:
            return
        try:
            proposal = self.assistant.propose_from_text(text)
        except ValueError as exc:
            self.statusBar().showMessage(f"Память: {exc}", 10_000)
            return
        if proposal is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Память")
        box.setText("Сохранить факт о пользователе?")
        box.setInformativeText(proposal.content)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        later = box.addButton("Позже", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is later or clicked is None:
            self.statusBar().showMessage("Предложение сохранено в /fact pending.", 8000)
        elif box.standardButton(clicked) == QMessageBox.StandardButton.Yes:
            fact = self.assistant.accept_proposal(proposal.id)
            if fact is not None:
                self.statusBar().showMessage(f"Сохранён факт #{fact.id}.", 8000)
        else:
            self.assistant.reject_proposal(proposal.id)
        self._refresh_facts()

    def _refresh_voice_status(self) -> None:
        try:
            self._voice_status = self.voice.status()
        except Exception as exc:  # noqa: BLE001 - статус не должен ронять окно
            self._voice_status = {"stt": (False, str(exc))}
        details = "; ".join(detail for _, detail in self._voice_status.values())
        recorder_ok = self._voice_status.get("recorder", (False, ""))[0]
        stt_ok = self._voice_status.get("stt", (False, ""))[0]
        tts_ok = self._voice_status.get("tts", (False, ""))[0]
        player_ok = self._voice_status.get("player", (False, ""))[0]
        microphone_ready = recorder_ok and stt_ok
        speech_ready = tts_ok and player_ok
        self.mic_label.setText("Микрофон: готов" if microphone_ready else "Микрофон: не настроен")
        self.mic_label.setToolTip(details)
        if microphone_ready and speech_ready:
            self.voice_status_label.setText("Голос: готов")
        elif microphone_ready:
            self.voice_status_label.setText("Голос: микрофон готов, TTS не настроен")
        elif speech_ready:
            self.voice_status_label.setText("Голос: TTS готов, микрофон не настроен")
        else:
            self.voice_status_label.setText("Голос: не настроен")
        self.voice_status_label.setToolTip(details)
        self._update_voice_buttons()

    def _update_voice_buttons(self) -> None:
        if not hasattr(self, "record_button"):
            return
        recorder_ok = self._voice_status.get("recorder", (False, ""))[0]
        stt_ok = self._voice_status.get("stt", (False, ""))[0]
        tts_ok = self._voice_status.get("tts", (False, ""))[0]
        player_ok = self._voice_status.get("player", (False, ""))[0]
        recording = self.voice.recording
        voice_worker_busy = self._voice_worker is not None and self._voice_worker.isRunning()
        self.record_button.setEnabled(
            not self._busy and not voice_worker_busy and (recording or (recorder_ok and stt_ok))
        )
        self.record_button.setText("Стоп (запись)" if recording else "Записать")
        self.cancel_record_button.setEnabled(recording)
        self.speak_button.setEnabled(
            not self._busy and not voice_worker_busy and not recording and tts_ok and player_ok
        )
        self.stop_speak_button.setEnabled(self.voice.player.is_playing)

    def _toggle_recording(self) -> None:
        if self._busy:
            return
        if self.voice.recording:
            self._stop_recording()
            return
        try:
            self.voice.start_recording()
        except VoiceError as exc:
            QMessageBox.warning(self, "Запись", str(exc))
            self._refresh_voice_status()
            return
        self.mic_label.setText("Микрофон: запись…")
        self.statusBar().showMessage("Идёт запись. Нажмите «Стоп (запись)».", 0)
        self._update_voice_buttons()

    def _stop_recording(self) -> None:
        try:
            path = self.voice.finish_recording()
        except VoiceError as exc:
            QMessageBox.warning(self, "Запись", str(exc))
            self._refresh_voice_status()
            return
        self.mic_label.setText("Микрофон: распознавание…")
        self.statusBar().showMessage("Распознаю речь…", 0)
        self._start_voice_worker("transcribe", str(path))

    def _cancel_recording(self) -> None:
        self.voice.cancel_recording()
        self.statusBar().showMessage("Запись отменена.", 8000)
        self._refresh_voice_status()

    def _start_voice_worker(self, mode: str, payload: str) -> None:
        if self._voice_worker is not None and self._voice_worker.isRunning():
            return
        worker = VoiceWorker(self.voice, mode, payload)
        worker.transcribed.connect(self._on_transcribed)
        worker.spoke.connect(self._on_spoke)
        worker.failed.connect(self._on_voice_failed)
        worker.finished.connect(lambda: self._on_voice_worker_finished(worker))
        self._voice_worker = worker
        worker.start()
        self._update_voice_buttons()

    def _on_transcribed(self, text: str) -> None:
        self.statusBar().showMessage(f"Распознано: {text}", 10_000)
        self.input.setPlainText(text)
        self.input.setFocus()
        if bool(self.settings.get("voice.auto_send", True)) and text.strip():
            QTimer.singleShot(0, self._send)

    def _on_spoke(self, path: str) -> None:
        self.statusBar().showMessage("Озвучивание…", 8000)
        self._update_voice_buttons()

    def _on_voice_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"Голос: {message}", 15_000)
        self._refresh_voice_status()
        self.input.setFocus()

    def _on_voice_worker_finished(self, worker: VoiceWorker) -> None:
        if self._voice_worker is worker:
            self._voice_worker = None
        worker.deleteLater()
        self._refresh_voice_status()

    def _speak_text(self, text: str) -> None:
        if not text.strip():
            return
        tts_ok = self._voice_status.get("tts", (False, ""))[0]
        player_ok = self._voice_status.get("player", (False, ""))[0]
        if not (tts_ok and player_ok):
            self.statusBar().showMessage("TTS не настроен. Проверьте настройки голоса.", 10_000)
            return
        if self._voice_worker is not None and self._voice_worker.isRunning():
            return
        self.statusBar().showMessage("Синтез речи…", 0)
        self._start_voice_worker("speak", text)

    def _speak_last(self) -> None:
        messages = self.assistant.history.messages(self.assistant.session_id, limit=50)
        answer = next((m.content for m in reversed(messages) if m.role == "assistant"), None)
        if answer is None:
            self.statusBar().showMessage("В текущей сессии ещё нет ответа Amadeus.", 8000)
            return
        self._speak_text(answer)

    def _stop_speaking(self) -> None:
        self.voice.stop_speaking()
        self.statusBar().showMessage("Озвучивание остановлено.", 8000)
        self._update_voice_buttons()

    def _load_session(self, session_id: int) -> None:
        if not self.assistant.resume(session_id):
            self.statusBar().showMessage(f"Сессия #{session_id} не найдена.", 8000)
            return
        self.chat.clear()
        messages = self.assistant.history.messages(session_id)
        for message in messages:
            self.chat.add_message(message.role, message.content)
        if not messages:
            self.chat.add_message("system", "Сессия пуста. Напишите сообщение.")
        session = self.assistant.history.get_session(session_id)
        title = session["title"] if session is not None else ""
        self.setWindowTitle(f"Amadeus — #{session_id}" + (f" — {title}" if title else ""))

    def _refresh_history(self) -> None:
        query = self.history_search.text().strip()
        self._search_query = query
        self.history_list.blockSignals(True)
        self.history_list.clear()
        current = self.assistant.session_id
        current_row = -1
        if query:
            hits = self.assistant.history.search(query, limit=50)
            for hit in hits:
                snippet = " ".join(hit.content.split())[:90]
                item = QListWidgetItem(f"#{hit.session_id} [{hit.role}] {snippet}")
                item.setData(USER_ROLE, hit.session_id)
                item.setToolTip(hit.content)
                self.history_list.addItem(item)
                if hit.session_id == current and current_row < 0:
                    current_row = self.history_list.count() - 1
            if not hits:
                item = QListWidgetItem("Ничего не найдено")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.history_list.addItem(item)
        else:
            sessions = self.assistant.history.list_sessions(limit=50)
            for row in sessions:
                title = row["title"] or "(без названия)"
                item = QListWidgetItem(
                    f"#{row['id']} {title}  ·  сообщений: {row['message_count']}"
                )
                item.setData(USER_ROLE, int(row["id"]))
                item.setToolTip(row["updated_at"])
                self.history_list.addItem(item)
                if row["id"] == current:
                    current_row = self.history_list.count() - 1
            if not sessions:
                item = QListWidgetItem("История пуста")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.history_list.addItem(item)
        if current_row >= 0:
            self.history_list.setCurrentRow(current_row)
        self.history_list.blockSignals(False)

    def _on_search_changed(self, text: str) -> None:
        if not text.strip() and self._search_query:
            self._refresh_history()

    def _on_history_item(self, item: QListWidgetItem) -> None:
        if self._busy:
            return
        session_id = item.data(USER_ROLE)
        if isinstance(session_id, int):
            self._load_session(session_id)

    def _new_session(self) -> None:
        if self._busy:
            return
        session_id = self.assistant.new_session()
        self.chat.clear()
        self.chat.add_message("system", "Новая сессия. Напишите сообщение.")
        self.setWindowTitle(f"Amadeus — #{session_id}")
        self._refresh_history()
        self.history_search.clear()
        self.input.setFocus()

    def _summarize_session(self) -> None:
        if self._busy or (self._summary_worker is not None and self._summary_worker.isRunning()):
            return
        worker = SummaryWorker(
            self.settings,
            self.assistant.session_id,
            self.assistant.persona_path,
        )
        worker.done.connect(self._on_summary_done)
        worker.failed.connect(self._on_summary_failed)
        worker.finished.connect(lambda: self._on_summary_finished(worker))
        self._summary_worker = worker
        self._set_busy(True)
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage("Создаю сводку сессии…", 0)
        worker.start()

    def _on_summary_done(self, content: str) -> None:
        self.chat.add_message("system", "Сводка сессии:\n\n" + content)
        self.statusBar().showMessage("Сводка сохранена.", 8000)

    def _on_summary_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Сводка", message)
        self.statusBar().showMessage("Сводка не создана.", 8000)

    def _on_summary_finished(self, worker: SummaryWorker) -> None:
        if self._summary_worker is worker:
            self._summary_worker = None
        worker.deleteLater()
        if self._busy:
            self._set_busy(False)

    def _delete_session(self) -> None:
        item = self.history_list.currentItem()
        if item is None:
            return
        session_id = item.data(USER_ROLE)
        if not isinstance(session_id, int):
            return
        if (
            QMessageBox.question(self, "Удалить сессию", f"Удалить сессию #{session_id}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.assistant.history.delete_session(session_id)
        if session_id == self.assistant.session_id:
            self.assistant.detach_session()
            self._new_session()
        else:
            self._refresh_history()

    def _refresh_facts(self) -> None:
        self.facts_list.blockSignals(True)
        self.facts_list.clear()
        for fact in self.assistant.facts.list():
            item = QListWidgetItem(f"#{fact.id}  {fact.content}")
            item.setData(USER_ROLE, {"kind": "fact", "id": fact.id})
            item.setToolTip(f"Источник: {fact.source}, создан: {fact.created_at}")
            self.facts_list.addItem(item)
        for proposal in self.assistant.proposals.pending():
            item = QListWidgetItem(f"[ожидает] #{proposal.id}  {proposal.content}")
            item.setData(USER_ROLE, {"kind": "proposal", "id": proposal.id})
            item.setToolTip("Требует подтверждения")
            self.facts_list.addItem(item)
        if self.facts_list.count() == 0:
            item = QListWidgetItem("Фактов пока нет")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.facts_list.addItem(item)
        self.facts_list.blockSignals(False)
        self._update_fact_buttons()

    def _selected_fact(self) -> dict[str, object] | None:
        item = self.facts_list.currentItem()
        if item is None:
            return None
        data = item.data(USER_ROLE)
        return data if isinstance(data, dict) else None

    def _update_fact_buttons(self) -> None:
        data = self._selected_fact()
        kind = data.get("kind") if data else None
        self.edit_fact_button.setEnabled(kind == "fact")
        self.delete_fact_button.setEnabled(kind == "fact")
        self.accept_fact_button.setEnabled(kind == "proposal")
        self.reject_fact_button.setEnabled(kind == "proposal")

    def _add_fact(self) -> None:
        text, ok = QInputDialog.getText(self, "Новый факт", "Текст факта:")
        if not ok or not text.strip():
            return
        existing = self.assistant.facts.find_exact(text)
        if existing is not None:
            QMessageBox.information(self, "Факт", f"Этот факт уже сохранён под #{existing.id}.")
            return
        if (
            QMessageBox.question(self, "Факт", "Сохранить этот факт?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        fact = self.assistant.facts.add(text, source="user_confirmed")
        self.statusBar().showMessage(f"Сохранён факт #{fact.id}.", 8000)
        self._refresh_facts()

    def _edit_fact(self) -> None:
        data = self._selected_fact()
        if not data or data.get("kind") != "fact":
            return
        fact_id = int(data["id"])
        fact = self.assistant.facts.get(fact_id)
        if fact is None:
            self._refresh_facts()
            return
        text, ok = QInputDialog.getText(self, "Изменить факт", "Текст факта:", text=fact.content)
        if not ok or not text.strip():
            return
        try:
            updated = self.assistant.facts.update(fact_id, text)
        except ValueError as exc:
            QMessageBox.warning(self, "Факт", str(exc))
            return
        if updated is not None:
            self.statusBar().showMessage(f"Факт #{updated.id} обновлён.", 8000)
        self._refresh_facts()

    def _delete_fact(self) -> None:
        data = self._selected_fact()
        if not data or data.get("kind") != "fact":
            return
        fact_id = int(data["id"])
        if (
            QMessageBox.question(self, "Факт", f"Удалить факт #{fact_id}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.assistant.facts.delete(fact_id)
        self._refresh_facts()

    def _accept_fact(self) -> None:
        data = self._selected_fact()
        if not data or data.get("kind") != "proposal":
            return
        proposal_id = int(data["id"])
        if (
            QMessageBox.question(self, "Память", f"Сохранить предложение #{proposal_id}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        fact = self.assistant.accept_proposal(proposal_id)
        if fact is not None:
            self.statusBar().showMessage(f"Сохранён факт #{fact.id}.", 8000)
        self._refresh_facts()

    def _reject_fact(self) -> None:
        data = self._selected_fact()
        if not data or data.get("kind") != "proposal":
            return
        proposal_id = int(data["id"])
        if (
            QMessageBox.question(self, "Память", f"Отклонить предложение #{proposal_id}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.assistant.reject_proposal(proposal_id)
        self._refresh_facts()

    def _refresh_status(self) -> None:
        if self._status_worker is not None and self._status_worker.isRunning():
            return
        self.status_label.setText("Модель: проверка…")
        worker = StatusWorker(self.assistant)
        worker.result.connect(self._on_status)
        worker.finished.connect(lambda: self._on_status_finished(worker))
        self._status_worker = worker
        worker.start()

    def _on_status(self, ok: bool, detail: str, models: object) -> None:
        provider = str(self.settings.get("provider.name", "ollama"))
        if provider == "cloud":
            label = "Облако: доступно" if ok else "Облако: ошибка"
        else:
            model = self.settings.get("ollama.model")
            label = f"Модель: {model} — OK" if ok else "Модель: недоступна"
        self.status_label.setText(label)
        self.status_label.setToolTip(detail)
        if not ok:
            self.statusBar().showMessage(detail, 15_000)

    def _on_status_finished(self, worker: StatusWorker) -> None:
        if self._status_worker is worker:
            self._status_worker = None
        worker.deleteLater()
        self._update_cloud_label()

    def _update_cloud_label(self) -> None:
        allowed = bool(self.settings.get("provider.allow_cloud", False))
        provider = str(self.settings.get("provider.name", "ollama"))
        if provider == "cloud":
            self.cloud_label.setText("Провайдер: облако")
        elif allowed:
            self.cloud_label.setText("Провайдер: локальный (облако разрешено)")
        else:
            self.cloud_label.setText("Провайдер: локальный")

    def _show_system_info(self) -> None:
        try:
            result = self.assistant.tools.execute("system_info", {}, confirmed=True)
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Системная информация", str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("Системная информация")
        box.setText(result)
        box.exec()

    def _send_notification_dialog(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Уведомление", "Текст уведомления:")
        if not ok or not text.strip():
            return
        try:
            result = self.assistant.tools.execute(
                "send_notification",
                {"title": "Amadeus", "text": text},
                confirmed=True,
            )
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Уведомление", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _launch_application_dialog(self) -> None:
        apps = sorted(self.assistant.tools.policy.allowed_apps)
        if not apps:
            QMessageBox.warning(self, "Приложения", "Allowlist приложений пуст.")
            return
        app, ok = QInputDialog.getItem(self, "Запуск приложения", "Приложение:", apps, 0, False)
        if not ok or not app:
            return
        tool = self.assistant.tools.get("launch_application")
        if tool.requires_confirmation:
            answer = QMessageBox.question(self, "Запуск приложения", f"Запустить «{app}»?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            result = self.assistant.tools.execute(
                "launch_application",
                {"app": app, "args": []},
                confirmed=True,
            )
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Приложения", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _last_assistant_text(self) -> str | None:
        messages = self.assistant.history.messages(self.assistant.session_id, limit=50)
        return next((m.content for m in reversed(messages) if m.role == "assistant"), None)

    def _copy_last_answer(self) -> None:
        text = self._last_assistant_text()
        if not text:
            self.statusBar().showMessage("В сессии ещё нет ответа Amadeus.", 8000)
            return
        try:
            result = self.assistant.tools.execute("copy_clipboard", {"text": text}, confirmed=True)
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Буфер обмена", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _take_screenshot(self) -> None:
        if (
            QMessageBox.question(self, "Скриншот", "Сделать скриншот экрана?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            result = self.assistant.tools.execute("screenshot", {}, confirmed=True)
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Скриншот", str(exc))
            return
        QMessageBox.information(self, "Скриншот", result)

    def _set_volume_dialog(self) -> None:
        percent, ok = QInputDialog.getInt(self, "Громкость", "Процентов (0–150):", 50, 0, 150, 5)
        if not ok:
            return
        try:
            result = self.assistant.tools.execute(
                "set_volume", {"percent": percent}, confirmed=True
            )
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Громкость", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _media_action(self, action: str) -> None:
        try:
            result = self.assistant.tools.execute(
                "media_control", {"action": action}, confirmed=True
            )
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Медиа", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _open_url_dialog(self) -> None:
        url, ok = QInputDialog.getText(self, "Открыть URL", "http/https URL:")
        if not ok or not url.strip():
            return
        if (
            QMessageBox.question(self, "Открыть URL", f"Открыть {url.strip()}?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            result = self.assistant.tools.execute("open_url", {"url": url.strip()}, confirmed=True)
        except (ToolError, PermissionDenied, OSError) as exc:
            QMessageBox.critical(self, "Открыть URL", str(exc))
            return
        self.statusBar().showMessage(result, 8000)

    def _open_settings(self) -> None:
        if self.voice.recording:
            QMessageBox.warning(self, "Настройки", "Сначала остановите запись.")
            return
        if self._voice_worker is not None and self._voice_worker.isRunning():
            QMessageBox.warning(self, "Настройки", "Дождитесь завершения голосовой операции.")
            return
        dialog = SettingsDialog(self.settings, self.assistant.persona_path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.voice.close()
            self.voice = VoicePipeline(self.settings)
            self._refresh_voice_status()
            self._update_cloud_label()
            self._refresh_status()
            self.statusBar().showMessage("Настройки сохранены.", 8000)

    def _export_data(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        default = str(Path.home() / f"amadeus-export-{stamp}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт данных", default, "JSON (*.json)")
        if not path:
            return
        try:
            target = self.assistant.export(path)
        except OSError as exc:
            QMessageBox.critical(self, "Экспорт", f"Не удалось экспортировать: {exc}")
            return
        self.statusBar().showMessage(f"Экспортировано: {target}", 10_000)

    def _delete_all(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Удалить все данные",
                "Удалить всю историю, факты и предложения безвозвратно?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.assistant.history.delete_all()
        self.assistant.detach_session()
        self.chat.clear()
        self._new_session()
        self._refresh_facts()
        self.statusBar().showMessage("Все данные удалены.", 10_000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "Об Amadeus",
            f"Amadeus {__version__}\n\n"
            "Локальный ИИ-ассистент для CachyOS.\n"
            "Текстовое ядро, память, GUI на PySide6 и локальный голос.\n\n"
            f"Данные: {paths.data_dir()}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Генерация",
                "Идёт генерация. Остановить и выйти?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            if not self._worker.wait(5000):
                QMessageBox.warning(
                    self,
                    "Генерация",
                    "Не удалось остановить запрос. Дождитесь завершения или таймаута.",
                )
                event.ignore()
                return
        if self._status_worker is not None and self._status_worker.isRunning():
            if not self._status_worker.wait(6000):
                self._status_worker.terminate()
                self._status_worker.wait(1000)
        if self.voice.recording:
            self.voice.cancel_recording()
        self.voice.stop_speaking()
        if self._summary_worker is not None and self._summary_worker.isRunning():
            if not self._summary_worker.wait(10_000):
                QMessageBox.warning(
                    self,
                    "Сводка",
                    "Сводка ещё создаётся. Дождитесь завершения.",
                )
                event.ignore()
                return
        if self._voice_worker is not None and self._voice_worker.isRunning():
            if not self._voice_worker.wait(10_000):
                QMessageBox.warning(
                    self,
                    "Голос",
                    "Голосовая операция ещё выполняется. Дождитесь её завершения.",
                )
                event.ignore()
                return
        self.voice.close()
        self._voice_timer.stop()
        self._status_timer.stop()
        event.accept()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amadeus-gui",
        description="Amadeus — графический интерфейс локального ИИ-ассистента.",
    )
    parser.add_argument("--config", type=Path, help="путь к альтернативному settings.toml")
    parser.add_argument("--model", help="переопределить модель Ollama")
    parser.add_argument("--session", type=int, help="открыть сессию по id")
    parser.add_argument("--new", action="store_true", help="начать новую сессию")
    parser.add_argument("--no-stream", action="store_true", help="отключить потоковый вывод")
    parser.add_argument("--version", action="version", version=f"Amadeus {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging()
    logger.info("GUI start version=%s", __version__)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Amadeus")
    app.setApplicationDisplayName("Amadeus")
    app.setOrganizationName("Amadeus")
    QGuiApplication.setDesktopFileName("amadeus")

    try:
        settings = Settings.load(args.config)
    except ConfigError as exc:
        QMessageBox.critical(None, "Amadeus", f"Ошибка конфигурации: {exc}")
        return 2

    if args.model:
        settings.set("ollama.model", args.model)
    if args.no_stream:
        settings.set("ollama.stream", False)

    try:
        db = Database()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Amadeus", f"Не удалось открыть базу данных: {exc}")
        return 2

    assistant = Assistant(settings, db=db, persona_path=settings.persona_path)
    if args.new:
        assistant.new_session()
    elif args.session is not None and not assistant.resume(args.session):
        QMessageBox.warning(None, "Amadeus", f"Сессия #{args.session} не найдена.")
        return 2

    window = MainWindow(assistant, settings)
    app.aboutToQuit.connect(assistant.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
