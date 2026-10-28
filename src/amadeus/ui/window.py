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
from ..memory import Database
from ..settings import ConfigError, Settings
from ..storage import paths
from .chat import ChatInput, ChatView, MessageBubble
from .settings import SettingsDialog

USER_ROLE = Qt.ItemDataRole.UserRole


class GenerationCancelled(Exception):
    pass


class ChatWorker(QThread):
    chunk = Signal(str)
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
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_id = session_id
        self.text = text
        self.persona_path = persona_path
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

            def on_chunk(text: str) -> None:
                if self._cancel.is_set():
                    raise GenerationCancelled
                self.chunk.emit(text)

            answer = assistant.respond(self.text, stream=stream, on_chunk=on_chunk)
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
    ) -> None:
        super().__init__()
        self.assistant = assistant
        self.settings = settings
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

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(60_000)
        self._status_timer.timeout.connect(self._refresh_status)
        if auto_status:
            self._status_timer.start()
            QTimer.singleShot(0, self._refresh_status)

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.chat = ChatView()
        layout.addWidget(self.chat, 1)

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
        self.delete_session_button = QPushButton("Удалить")
        self.delete_session_button.clicked.connect(self._delete_session)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(lambda: self._refresh_history())
        history_buttons.addWidget(self.new_button)
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
        self.delete_fact_button = QPushButton("Удалить")
        self.delete_fact_button.clicked.connect(self._delete_fact)
        self.accept_fact_button = QPushButton("Принять")
        self.accept_fact_button.clicked.connect(self._accept_fact)
        self.reject_fact_button = QPushButton("Отклонить")
        self.reject_fact_button.clicked.connect(self._reject_fact)
        refresh_facts_button = QPushButton("Обновить")
        refresh_facts_button.clicked.connect(self._refresh_facts)
        facts_buttons.addWidget(add_fact_button)
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
        self.mic_label = QLabel("Микрофон: не подключён (этап 4)")
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
        self.delete_session_button.setEnabled(not busy)
        self.history_search.setEnabled(not busy)
        if not busy:
            self.input.setFocus()

    def _send(self) -> None:
        if self._busy or (self._worker is not None and self._worker.isRunning()):
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self._last_user_text = text
        self.chat.add_message("user", text)
        self._stream_bubble = self.chat.add_message("assistant", "…")
        self._stream_text = ""
        self._set_busy(True)
        self.statusBar().showMessage("Генерация…")

        worker = ChatWorker(
            self.settings,
            self.assistant.session_id,
            text,
            self.assistant.persona_path,
        )
        worker.chunk.connect(self._on_chunk)
        worker.finished_text.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.notice.connect(self._on_notice)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        self._worker = worker
        worker.start()

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

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.assistant.persona_path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
            "Текстовое ядро, память и GUI на PySide6.\n\n"
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
