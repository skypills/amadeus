from __future__ import annotations

import subprocess
from pathlib import Path

from .base import VoiceError, resolve_executable, tail


class PiperTTS:
    def __init__(
        self,
        command: str = "piper",
        model: str = "",
        speaker: int | None = None,
        length_scale: float = 1.0,
        timeout: float = 120,
    ) -> None:
        self.command = command
        self.model = model
        self.speaker = speaker
        self.length_scale = length_scale
        self.timeout = timeout

    def _model_path(self) -> Path:
        if not self.model.strip():
            raise VoiceError("Не задан путь к голосу Piper в [voice].tts_model.")
        path = Path(self.model).expanduser()
        if not path.exists():
            raise VoiceError(f"Модель Piper не найдена: {path}")
        return path

    def status(self) -> tuple[bool, str]:
        try:
            executable = resolve_executable(self.command)
            model = self._model_path()
        except VoiceError as exc:
            return False, str(exc)
        return True, f"TTS: Piper ({Path(executable).name}, {model.name})"

    def synthesize(self, text: str, output_path: Path) -> Path:
        text = text.strip()
        if not text:
            raise VoiceError("Нечего озвучивать: пустой текст.")
        executable = resolve_executable(self.command)
        model = self._model_path()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        command = [
            executable,
            "--model",
            str(model),
            "--output_file",
            str(output_path),
        ]
        if self.speaker is not None:
            command.extend(["--speaker", str(self.speaker)])
        if self.length_scale != 1.0:
            command.extend(["--length_scale", str(self.length_scale)])
        try:
            process = subprocess.run(
                command,
                input=text,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VoiceError(f"Синтез речи не завершился за {self.timeout:.0f} секунд.") from exc
        except OSError as exc:
            raise VoiceError(f"Не удалось запустить Piper: {exc}") from exc
        if process.returncode != 0:
            detail = tail(process.stderr or process.stdout or "нет вывода")
            raise VoiceError(f"Piper завершился с ошибкой: {detail}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VoiceError("Piper не создал аудиофайл.")
        return output_path
