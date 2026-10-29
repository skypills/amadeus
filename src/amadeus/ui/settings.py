from __future__ import annotations

import os
import shlex
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..personality import MOODS, PERSONAS, write_persona
from ..settings import Settings
from ..voice.profiles import VOICE_PROFILES, apply_voice_profile


class SettingsDialog(QDialog):
    def __init__(
        self, settings: Settings, persona_path: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.persona_path = persona_path
        self.setWindowTitle("Настройки Amadeus")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_model_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_ui_group())
        layout.addWidget(self._build_personality_group())
        layout.addWidget(self._build_persona_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("Модель и провайдер")
        form = QFormLayout(group)

        self.base_url_edit = QLineEdit(str(self.settings.get("ollama.base_url")))
        self.model_edit = QLineEdit(str(self.settings.get("ollama.model")))
        self.stream_check = QCheckBox("Потоковый вывод")
        self.stream_check.setChecked(bool(self.settings.get("ollama.stream", True)))
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["ollama", "cloud"])
        self.provider_combo.setCurrentText(str(self.settings.get("provider.name", "ollama")))
        self.allow_cloud_check = QCheckBox("Разрешить облачный режим")
        self.allow_cloud_check.setChecked(bool(self.settings.get("provider.allow_cloud", False)))
        self.cloud_fallback_check = QCheckBox("Резерв на облако при ошибке Ollama")
        self.cloud_fallback_check.setChecked(
            bool(self.settings.get("provider.cloud_fallback", True))
        )
        self.cloud_url_edit = QLineEdit(str(self.settings.get("provider.cloud_base_url")))
        self.cloud_model_edit = QLineEdit(str(self.settings.get("provider.cloud_model")))
        self.cloud_key_env_edit = QLineEdit(str(self.settings.get("provider.cloud_api_key_env")))
        self.cloud_key_status = QLabel()
        self.cloud_key_env_edit.textChanged.connect(self._update_key_status)
        self._update_key_status()

        form.addRow("Ollama URL:", self.base_url_edit)
        form.addRow("Модель:", self.model_edit)
        form.addRow("", self.stream_check)
        form.addRow("Провайдер:", self.provider_combo)
        form.addRow("", self.allow_cloud_check)
        form.addRow("", self.cloud_fallback_check)
        form.addRow("Cloud URL:", self.cloud_url_edit)
        form.addRow("Cloud модель:", self.cloud_model_edit)
        form.addRow("Переменная ключа:", self.cloud_key_env_edit)
        form.addRow("Ключ:", self.cloud_key_status)
        return group

    def _build_voice_group(self) -> QGroupBox:
        group = QGroupBox("Голос")
        form = QFormLayout(group)
        self.stt_command_edit = QLineEdit(str(self.settings.get("voice.stt_command")))
        self.stt_model_edit = QLineEdit(str(self.settings.get("voice.stt_model")))
        self.tts_command_edit = QLineEdit(str(self.settings.get("voice.tts_command")))
        self.tts_model_edit = QLineEdit(str(self.settings.get("voice.tts_model")))
        self.language_edit = QLineEdit(str(self.settings.get("voice.language", "ru")))
        self.recorder_command_edit = QLineEdit(str(self.settings.get("voice.recorder_command")))
        self.player_command_edit = QLineEdit(str(self.settings.get("voice.player_command")))
        self.auto_send_check = QCheckBox("Отправлять распознанное сразу")
        self.auto_send_check.setChecked(bool(self.settings.get("voice.auto_send", True)))
        self.auto_speak_check = QCheckBox("Озвучивать ответы автоматически")
        self.auto_speak_check.setChecked(bool(self.settings.get("voice.auto_speak", False)))
        self.voice_profile_combo = QComboBox()
        self.voice_profile_combo.addItems(list(VOICE_PROFILES))
        self.voice_profile_combo.setCurrentText(str(self.settings.get("voice.profile", "default")))

        form.addRow("STT команда:", self.stt_command_edit)
        form.addRow("Модель Whisper:", self.stt_model_edit)
        form.addRow("TTS команда:", self.tts_command_edit)
        form.addRow("Голос Piper:", self.tts_model_edit)
        form.addRow("Язык:", self.language_edit)
        form.addRow("Рекордер (пусто = авто):", self.recorder_command_edit)
        form.addRow("Плеер (пусто = авто):", self.player_command_edit)
        form.addRow("Профиль голоса:", self.voice_profile_combo)
        form.addRow("", self.auto_send_check)
        form.addRow("", self.auto_speak_check)
        hint = QLabel(
            "Модели whisper.cpp и Piper не входят в пакет. Пути и установка описаны в README."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return group

    def _build_ui_group(self) -> QGroupBox:
        group = QGroupBox("Интерфейс")
        form = QFormLayout(group)
        self.close_tray_check = QCheckBox("Закрывать окно в трей")
        self.close_tray_check.setChecked(bool(self.settings.get("ui.close_to_tray", True)))
        self.chibi_check = QCheckBox("Чиби-Курису на рабочем столе")
        self.chibi_check.setChecked(bool(self.settings.get("ui.chibi_enabled", True)))
        form.addRow("", self.close_tray_check)
        form.addRow("", self.chibi_check)
        hint = QLabel(
            "Чиби двигается по экрану, перетаскивается мышью и открывает Amadeus "
            "двойным кликом. Позиционирование использует Hyprland."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return group

    def _build_personality_group(self) -> QGroupBox:
        group = QGroupBox("Характер")
        form = QFormLayout(group)
        self.mood_combo = QComboBox()
        self.mood_combo.addItems(list(MOODS))
        self.mood_combo.setCurrentText(str(self.settings.get("personality.mood", "calm")))
        self.familiarity_spin = self._make_spin("personality.familiarity")
        self.verbosity_spin = self._make_spin("personality.verbosity")
        self.initiative_spin = self._make_spin("personality.initiative")
        form.addRow("Настроение:", self.mood_combo)
        form.addRow("Familiarity:", self.familiarity_spin)
        form.addRow("Verbosity:", self.verbosity_spin)
        form.addRow("Initiative:", self.initiative_spin)
        return group

    def _build_persona_group(self) -> QGroupBox:
        group = QGroupBox("Персона")
        layout = QVBoxLayout(group)
        preset_row = QHBoxLayout()
        self.persona_preset_combo = QComboBox()
        self.persona_preset_combo.addItems(list(PERSONAS))
        self.persona_preset_combo.setCurrentText(
            str(self.settings.get("personality.preset", "amadeus"))
        )
        apply_preset_button = QPushButton("Применить пресет")
        apply_preset_button.clicked.connect(self._apply_persona_preset)
        preset_row.addWidget(self.persona_preset_combo, 1)
        preset_row.addWidget(apply_preset_button)
        layout.addLayout(preset_row)
        buttons = QHBoxLayout()
        self.persona_label = QLabel(str(self.persona_path))
        self.persona_label.setWordWrap(True)
        edit_button = QPushButton("Редактировать")
        edit_button.clicked.connect(self._edit_persona)
        reset_button = QPushButton("Сбросить")
        reset_button.clicked.connect(self._reset_persona)
        buttons.addWidget(self.persona_label, 1)
        buttons.addWidget(edit_button)
        buttons.addWidget(reset_button)
        layout.addLayout(buttons)
        return group

    def _make_spin(self, key: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.1)
        spin.setDecimals(1)
        spin.setValue(float(self.settings.get(key, 0.5)))
        return spin

    def _update_key_status(self) -> None:
        env_name = self.cloud_key_env_edit.text().strip()
        found = bool(env_name and os.environ.get(env_name, "").strip())
        self.cloud_key_status.setText(
            f"переменная {env_name} найдена" if found else "не найден (задайте в окружении)"
        )

    def _save(self) -> None:
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()
        if not base_url or not model:
            QMessageBox.warning(self, "Настройки", "URL Ollama и модель не могут быть пустыми.")
            return
        provider = self.provider_combo.currentText()
        allow_cloud = self.allow_cloud_check.isChecked()
        if provider == "cloud" and (
            not self.cloud_url_edit.text().strip()
            or not self.cloud_model_edit.text().strip()
            or not self.cloud_key_env_edit.text().strip()
        ):
            QMessageBox.warning(
                self,
                "Настройки",
                "Для облачного провайдера заполните URL, модель и переменную ключа.",
            )
            return
        if provider == "cloud" and not allow_cloud:
            answer = QMessageBox.question(
                self,
                "Облачный режим",
                "Выбран облачный провайдер. Разрешить отправку запросов в интернет?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            allow_cloud = True

        values = {
            "ollama.base_url": base_url,
            "ollama.model": model,
            "ollama.stream": self.stream_check.isChecked(),
            "provider.name": provider,
            "provider.allow_cloud": allow_cloud,
            "provider.cloud_fallback": self.cloud_fallback_check.isChecked(),
            "provider.cloud_base_url": self.cloud_url_edit.text().strip(),
            "provider.cloud_model": self.cloud_model_edit.text().strip(),
            "provider.cloud_api_key_env": self.cloud_key_env_edit.text().strip(),
            "voice.stt_command": self.stt_command_edit.text().strip(),
            "voice.stt_model": self.stt_model_edit.text().strip(),
            "voice.tts_command": self.tts_command_edit.text().strip(),
            "voice.tts_model": self.tts_model_edit.text().strip(),
            "voice.language": self.language_edit.text().strip() or "ru",
            "voice.recorder_command": self.recorder_command_edit.text().strip(),
            "voice.player_command": self.player_command_edit.text().strip(),
            "voice.auto_send": self.auto_send_check.isChecked(),
            "voice.auto_speak": self.auto_speak_check.isChecked(),
            "ui.close_to_tray": self.close_tray_check.isChecked(),
            "ui.chibi_enabled": self.chibi_check.isChecked(),
            "personality.mood": self.mood_combo.currentText(),
            "personality.familiarity": self.familiarity_spin.value(),
            "personality.verbosity": self.verbosity_spin.value(),
            "personality.initiative": self.initiative_spin.value(),
        }
        for key, value in values.items():
            self.settings.set(key, value, save=False)
        try:
            apply_voice_profile(
                self.settings,
                self.voice_profile_combo.currentText(),
                save=False,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Голос", str(exc))
            return
        self.settings.save()
        self.accept()

    def _editor_command(self) -> list[str]:
        command = shlex.split(os.environ.get("EDITOR", ""))
        return command or ["nano"]

    def _apply_persona_preset(self) -> None:
        name = self.persona_preset_combo.currentText()
        answer = QMessageBox.question(
            self,
            "Персона",
            f"Заменить persona.md пресетом «{name}»?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        write_persona(self.persona_path, name)
        self.settings.set("personality.preset", name)
        QMessageBox.information(
            self,
            "Персона",
            f"Пресет «{name}» применён. Изменения вступят со следующего ответа.",
        )

    def _edit_persona(self) -> None:
        command = self._editor_command()
        result = QProcess.startDetached(command[0], [*command[1:], str(self.persona_path)])
        started = result[0] if isinstance(result, tuple) else bool(result)
        if not started:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.persona_path)))

    def _reset_persona(self) -> None:
        answer = QMessageBox.question(
            self,
            "Персона",
            "Вернуть стандартную персону? Текущий текст будет перезаписан.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        preset = str(self.settings.get("personality.preset", "amadeus"))
        preset = preset if preset in PERSONAS else "amadeus"
        write_persona(self.persona_path, preset)
        QMessageBox.information(self, "Персона", f"Пресет «{preset}» восстановлен.")
