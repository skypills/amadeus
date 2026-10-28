from __future__ import annotations

import time
from pathlib import Path

from ..settings import Settings
from ..storage import paths
from .base import VoiceError
from .player import AudioPlayer
from .recorder import AudioRecorder
from .stt import WhisperCppSTT
from .tts import PiperTTS


class VoicePipeline:
    def __init__(
        self,
        settings: Settings,
        recorder: AudioRecorder | None = None,
        stt: WhisperCppSTT | None = None,
        tts: PiperTTS | None = None,
        player: AudioPlayer | None = None,
    ) -> None:
        self.settings = settings
        self.recorder = recorder or AudioRecorder(
            str(settings.get("voice.recorder_command", "")),
            sample_rate=int(settings.get("voice.sample_rate", 16000)),
        )
        self.stt = stt or WhisperCppSTT(
            str(settings.get("voice.stt_command", "whisper-cli")),
            str(settings.get("voice.stt_model", "")),
            str(settings.get("voice.language", "ru")),
            timeout=float(settings.get("voice.stt_timeout", 300)),
        )
        self.tts = tts or PiperTTS(
            str(settings.get("voice.tts_command", "piper")),
            str(settings.get("voice.tts_model", "")),
            timeout=float(settings.get("voice.tts_timeout", 120)),
        )
        self.player = player or AudioPlayer(str(settings.get("voice.player_command", "")))
        self.work_dir = paths.data_dir() / "voice"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @property
    def recording(self) -> bool:
        return self.recorder.recording

    def status(self) -> dict[str, tuple[bool, str]]:
        return {
            "recorder": self.recorder.status(),
            "stt": self.stt.status(),
            "tts": self.tts.status(),
            "player": self.player.status(),
        }

    def status_text(self) -> str:
        return "; ".join(detail for _, detail in self.status().values())

    def microphone_ready(self) -> bool:
        recorder_ok, _ = self.recorder.status()
        stt_ok, _ = self.stt.status()
        return recorder_ok and stt_ok

    def tts_ready(self) -> bool:
        tts_ok, _ = self.tts.status()
        player_ok, _ = self.player.status()
        return tts_ok and player_ok

    def start_recording(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.work_dir / f"recording-{stamp}.wav"
        return self.recorder.start(path)

    def finish_recording(self) -> Path:
        return self.recorder.finish()

    def cancel_recording(self) -> None:
        self.recorder.cancel()

    def transcribe(self, wav_path: Path) -> str:
        wav_path = Path(wav_path)
        try:
            return self.stt.transcribe(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)

    def record_for(self, seconds: float = 5.0) -> str:
        if seconds <= 0:
            raise VoiceError("Длительность записи должна быть больше нуля.")
        path = self.start_recording()
        try:
            time.sleep(seconds)
        except KeyboardInterrupt:
            self.cancel_recording()
            raise
        try:
            wav_path = self.finish_recording()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.transcribe(wav_path)

    def speak(self, text: str) -> Path:
        target = self.work_dir / "last-response.wav"
        path = self.tts.synthesize(text, target)
        self.player.play(path)
        return path

    def stop_speaking(self) -> None:
        self.player.stop()

    def close(self) -> None:
        self.cancel_recording()
        self.stop_speaking()
