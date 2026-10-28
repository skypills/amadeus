from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from .base import VoiceError, resolve_executable, split_command

CANDIDATES = ("pw-play", "paplay", "aplay", "ffplay")


class AudioPlayer:
    def __init__(self, command: str = "") -> None:
        self.command = command.strip()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def _command_for(self, path: Path) -> list[str]:
        if self.command:
            parts = split_command(self.command)
            parts[0] = resolve_executable(parts[0])
            if "{input}" in parts:
                return [part.replace("{input}", str(path)) for part in parts]
            return [*parts, str(path)]
        for candidate in CANDIDATES:
            executable = shutil.which(candidate)
            if executable is None:
                continue
            if candidate == "ffplay":
                return [
                    executable,
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    str(path),
                ]
            return [executable, str(path)]
        raise VoiceError(
            "Не найден аудиоплеер. Установите pipewire (pw-play), pulseaudio "
            "(paplay), alsa-utils (aplay) или ffmpeg, либо задайте player_command."
        )

    def status(self) -> tuple[bool, str]:
        try:
            command = self._command_for(Path("speech.wav"))
        except VoiceError as exc:
            return False, str(exc)
        return True, f"плеер: {Path(command[0]).name}"

    def play(self, path: Path) -> None:
        with self._lock:
            self._stop_locked()
            command = self._command_for(Path(path))
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                raise VoiceError(f"Не удалось запустить аудиоплеер: {exc}") from exc

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
