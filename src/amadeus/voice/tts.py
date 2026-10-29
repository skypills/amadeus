from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

from .base import VoiceError, resolve_executable, tail


class PiperTTS:
    def __init__(
        self,
        command: str = "piper",
        model: str = "",
        speaker: int | None = None,
        length_scale: float = 1.0,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
        pitch_semitones: float = 0.0,
        timeout: float = 120,
    ) -> None:
        self.command = command
        self.model = model
        self.speaker = speaker
        self.length_scale = length_scale
        self.noise_scale = noise_scale
        self.noise_w = noise_w
        self.pitch_semitones = pitch_semitones
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
            if self.pitch_semitones and shutil.which("ffmpeg") is None:
                raise VoiceError("Для изменения тона нужен ffmpeg.")
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
        command.extend(["--length_scale", str(self.length_scale)])
        command.extend(["--noise_scale", str(self.noise_scale)])
        command.extend(["--noise_w", str(self.noise_w)])
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
        self._shift_pitch(output_path)
        return output_path

    def _shift_pitch(self, path: Path) -> None:
        if self.pitch_semitones == 0:
            return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise VoiceError("Для изменения тона нужен ffmpeg.")
        try:
            with wave.open(str(path), "rb") as audio:
                rate = audio.getframerate()
        except (wave.Error, OSError) as exc:
            raise VoiceError(f"Не удалось прочитать WAV для изменения тона: {exc}") from exc
        factor = 2 ** (self.pitch_semitones / 12)
        temporary = path.with_name(path.stem + ".pitch.wav")
        filter_chain = f"asetrate={rate * factor:.3f},aresample={rate},atempo={1 / factor:.6f}"
        try:
            process = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-filter:a",
                    filter_chain,
                    str(temporary),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            temporary.unlink(missing_ok=True)
            raise VoiceError(f"Не удалось изменить тон: {exc}") from exc
        if process.returncode != 0 or not temporary.exists():
            temporary.unlink(missing_ok=True)
            raise VoiceError(
                "ffmpeg не смог изменить тон: " + tail(process.stderr or process.stdout)
            )
        temporary.replace(path)
