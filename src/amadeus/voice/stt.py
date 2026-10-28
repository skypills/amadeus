from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import VoiceError, resolve_executable, tail


class WhisperCppSTT:
    def __init__(
        self,
        command: str = "whisper-cli",
        model: str = "",
        language: str = "ru",
        timeout: float = 300,
    ) -> None:
        self.command = command
        self.model = model
        self.language = language
        self.timeout = timeout

    def _model_path(self) -> Path:
        if not self.model.strip():
            raise VoiceError("Не задан путь к модели Whisper в [voice].stt_model.")
        path = Path(self.model).expanduser()
        if not path.exists():
            raise VoiceError(f"Модель Whisper не найдена: {path}")
        return path

    def status(self) -> tuple[bool, str]:
        try:
            executable = resolve_executable(self.command)
            model = self._model_path()
        except VoiceError as exc:
            return False, str(exc)
        return True, f"STT: whisper.cpp ({Path(executable).name}, {model.name})"

    def transcribe(self, wav_path: Path) -> str:
        executable = resolve_executable(self.command)
        model = self._model_path()
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise VoiceError(f"Аудиофайл не найден: {wav_path}")
        workdir = Path(tempfile.mkdtemp(prefix="amadeus-stt-", dir=wav_path.parent))
        output_base = workdir / "transcript"
        command = [
            executable,
            "-m",
            str(model),
            "-f",
            str(wav_path),
            "-l",
            self.language,
            "-nt",
            "-otxt",
            "-of",
            str(output_base),
        ]
        try:
            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise VoiceError(
                    f"Распознавание не завершилось за {self.timeout:.0f} секунд."
                ) from exc
            except OSError as exc:
                raise VoiceError(f"Не удалось запустить whisper.cpp: {exc}") from exc
            output_file = Path(f"{output_base}.txt")
            text = ""
            if output_file.exists():
                text = output_file.read_text(encoding="utf-8", errors="replace")
            if not text.strip() and process.stdout:
                text = process.stdout
            if process.returncode != 0 and not text.strip():
                detail = tail(process.stderr or process.stdout or "нет вывода")
                raise VoiceError(f"whisper.cpp завершился с ошибкой: {detail}")
            text = " ".join(text.split())
            if not text:
                raise VoiceError("Речь не распознана. Проверьте микрофон и модель.")
            return text
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
