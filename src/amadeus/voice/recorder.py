from __future__ import annotations

import shutil
import signal
import subprocess
import time
from pathlib import Path

from .base import VoiceError, resolve_executable, split_command

CANDIDATES = ("parecord", "pw-record", "arecord")


class AudioRecorder:
    def __init__(self, command: str = "", sample_rate: int = 16000) -> None:
        self.command = command.strip()
        self.sample_rate = sample_rate
        self._process: subprocess.Popen | None = None
        self._path: Path | None = None

    @property
    def recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _command_for(self, path: Path) -> list[str]:
        if self.command:
            parts = split_command(self.command)
            parts[0] = resolve_executable(parts[0])
            if "{output}" in parts:
                return [part.replace("{output}", str(path)) for part in parts]
            return [*parts, str(path)]
        for candidate in CANDIDATES:
            executable = shutil.which(candidate)
            if executable is None:
                continue
            if candidate == "parecord":
                return [
                    executable,
                    "--channels=1",
                    f"--rate={self.sample_rate}",
                    "--format=s16le",
                    str(path),
                ]
            if candidate == "pw-record":
                return [
                    executable,
                    "--rate",
                    str(self.sample_rate),
                    "--channels",
                    "1",
                    str(path),
                ]
            return [
                executable,
                "-q",
                "-f",
                "S16_LE",
                "-r",
                str(self.sample_rate),
                "-c",
                "1",
                "-t",
                "wav",
                str(path),
            ]
        raise VoiceError(
            "Не найден рекордер. Установите pipewire (pw-record), pulseaudio "
            "(parecord) или alsa-utils (arecord) либо задайте recorder_command."
        )

    def status(self) -> tuple[bool, str]:
        try:
            command = self._command_for(Path("recording.wav"))
        except VoiceError as exc:
            return False, str(exc)
        return True, f"рекордер: {Path(command[0]).name}"

    def start(self, path: Path) -> Path:
        if self.recording:
            raise VoiceError("Запись уже идёт.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        command = self._command_for(path)
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise VoiceError(f"Не удалось запустить запись: {exc}") from exc
        time.sleep(0.05)
        if process.poll() is not None:
            path.unlink(missing_ok=True)
            raise VoiceError(
                "Рекордер завершился сразу после запуска. Проверьте микрофон "
                "и команду recorder_command."
            )
        self._process = process
        self._path = path
        return path

    def finish(self) -> Path:
        process = self._process
        path = self._path
        if process is None or path is None:
            raise VoiceError("Запись не запущена.")
        try:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        finally:
            self._process = None
            self._path = None
        if not path.exists() or path.stat().st_size <= 44:
            path.unlink(missing_ok=True)
            raise VoiceError(
                "Запись не создана или пуста. Проверьте микрофон и выбранный рекордер."
            )
        return path

    def cancel(self) -> None:
        process = self._process
        path = self._path
        self._process = None
        self._path = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if path is not None:
            path.unlink(missing_ok=True)
