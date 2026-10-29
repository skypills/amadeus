from __future__ import annotations

import time

import pytest

from amadeus.voice import (
    AudioPlayer,
    AudioRecorder,
    PiperTTS,
    VoiceError,
    VoicePipeline,
    WhisperCppSTT,
)


def make_script(tmp_path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def make_model(tmp_path, name: str = "model.bin") -> str:
    path = tmp_path / name
    path.write_bytes(b"model")
    return str(path)


def stt_script(tmp_path):
    return make_script(
        tmp_path,
        "fake-whisper",
        """
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -of) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'привет мир' > "$out.txt"
""",
    )


def tts_script(tmp_path):
    return make_script(
        tmp_path,
        "fake-piper",
        """
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output_file) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cat > /dev/null
dd if=/dev/zero of="$out" bs=1 count=200 2>/dev/null
""",
    )


def recorder_script(tmp_path):
    return make_script(
        tmp_path,
        "fake-recorder",
        """
out="$1"
dd if=/dev/zero of="$out" bs=1 count=200 2>/dev/null
trap 'exit 0' INT TERM
sleep 5
""",
    )


def player_script(tmp_path):
    return make_script(tmp_path, "fake-player", "sleep 5\n")


def test_whisper_stt_with_fake_binary(tmp_path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 100)
    stt = WhisperCppSTT(command=stt_script(tmp_path), model=make_model(tmp_path))
    assert stt.status()[0]
    assert stt.transcribe(wav) == "привет мир"


def test_whisper_reports_errors(tmp_path):
    model = make_model(tmp_path)
    failing = make_script(tmp_path, "fail-whisper", "echo 'model error' >&2\nexit 2\n")
    stt = WhisperCppSTT(command=failing, model=model)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"x")
    with pytest.raises(VoiceError, match="ошибкой"):
        stt.transcribe(wav)

    missing = WhisperCppSTT(command="/nonexistent-whisper", model=model)
    assert not missing.status()[0]


def test_missing_stt_model_is_reported(tmp_path):
    stt = WhisperCppSTT(command=stt_script(tmp_path), model=str(tmp_path / "nope.bin"))
    ok, detail = stt.status()
    assert not ok
    assert "не найдена" in detail


def test_piper_tts_with_fake_binary(tmp_path):
    tts = PiperTTS(command=tts_script(tmp_path), model=make_model(tmp_path))
    out = tts.synthesize("привет", tmp_path / "out.wav")
    assert out.exists()
    assert out.stat().st_size == 200
    assert tts.status()[0]


def test_parecord_command_uses_positional_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "amadeus.voice.recorder.shutil.which",
        lambda name: "/usr/bin/parecord" if name == "parecord" else None,
    )
    recorder = AudioRecorder()
    command = recorder._command_for(tmp_path / "rec.wav")
    assert "--file" not in " ".join(command)
    assert command[-1] == str(tmp_path / "rec.wav")
    assert "--format=s16le" in command


def test_audio_recorder_start_finish_cancel(tmp_path):
    script = recorder_script(tmp_path)
    recorder = AudioRecorder(command=f"{script} {{output}}")
    path = recorder.start(tmp_path / "rec.wav")
    assert recorder.recording
    time.sleep(0.1)
    finished = recorder.finish()
    assert finished == path
    assert path.exists() and path.stat().st_size == 200
    assert not recorder.recording

    path2 = recorder.start(tmp_path / "rec2.wav")
    time.sleep(0.1)
    recorder.cancel()
    assert not path2.exists()


def test_audio_player_play_stop(tmp_path):
    script = player_script(tmp_path)
    player = AudioPlayer(command=f"{script} {{input}}")
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 44)
    assert player.status()[0]
    player.play(wav)
    assert player.is_playing
    player.stop()
    assert not player.is_playing


def test_voice_pipeline_records_transcribes_and_speaks(tmp_path, settings):
    model = make_model(tmp_path)
    settings.set("voice.recorder_command", f"{recorder_script(tmp_path)} {{output}}", save=False)
    settings.set("voice.stt_command", stt_script(tmp_path), save=False)
    settings.set("voice.stt_model", model, save=False)
    settings.set("voice.tts_command", tts_script(tmp_path), save=False)
    settings.set("voice.tts_model", model, save=False)
    settings.set("voice.player_command", f"{player_script(tmp_path)} {{input}}", save=False)
    from amadeus.voice.profiles import apply_voice_profile

    apply_voice_profile(settings, "default", save=False)
    settings.save()

    pipeline = VoicePipeline(settings)
    status = pipeline.status()
    assert all(ok for ok, _ in status.values())
    assert pipeline.microphone_ready()
    assert pipeline.tts_ready()

    pipeline.start_recording()
    time.sleep(0.1)
    wav = pipeline.finish_recording()
    assert wav.exists()
    assert pipeline.transcribe(wav) == "привет мир"
    assert not wav.exists()

    output = pipeline.speak("ответ")
    assert output.exists()
    assert pipeline.player.is_playing
    pipeline.stop_speaking()
    pipeline.close()


def test_pipeline_reports_missing_tools(tmp_path, settings):
    settings.set("voice.stt_command", "/nonexistent-whisper", save=False)
    settings.set("voice.tts_command", "/nonexistent-piper", save=False)
    settings.set("voice.recorder_command", "/nonexistent-recorder", save=False)
    settings.set("voice.player_command", "/nonexistent-player", save=False)
    pipeline = VoicePipeline(settings)
    status = pipeline.status()
    assert not status["recorder"][0]
    assert not status["stt"][0]
    assert not status["tts"][0]
    assert not status["player"][0]


def test_piper_command_includes_profile_parameters(tmp_path, monkeypatch):
    model = make_model(tmp_path)
    tts = PiperTTS(
        command=tts_script(tmp_path),
        model=model,
        length_scale=0.92,
        noise_scale=0.75,
        noise_w=0.85,
        pitch_semitones=0.0,
    )
    captured = {}
    import subprocess

    real_run = subprocess.run

    def fake_run(command, **kwargs):
        captured["command"] = command
        return real_run(command, **kwargs)

    monkeypatch.setattr("amadeus.voice.tts.subprocess.run", fake_run)
    tts.synthesize("тест", tmp_path / "out.wav")
    joined = " ".join(captured["command"])
    assert "--length_scale 0.92" in joined
    assert "--noise_scale 0.75" in joined
    assert "--noise_w 0.85" in joined


def test_pitch_shift_keeps_valid_wav(tmp_path):
    import math
    import shutil
    import struct
    import wave

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg не установлен")
    path = tmp_path / "tone.wav"
    rate = 22050
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(rate // 4)
        )
        audio.writeframes(frames)
    tts = PiperTTS(command=tts_script(tmp_path), model=make_model(tmp_path), pitch_semitones=2)
    tts._shift_pitch(path)
    with wave.open(str(path), "rb") as audio:
        assert audio.getframerate() == rate
        assert audio.getnframes() > 0
