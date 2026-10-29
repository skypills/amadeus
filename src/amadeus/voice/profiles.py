from __future__ import annotations

from dataclasses import dataclass

from ..settings import Settings


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    length_scale: float
    noise_scale: float
    noise_w: float
    pitch_semitones: float


VOICE_PROFILES: dict[str, VoiceProfile] = {
    "default": VoiceProfile("default", 1.0, 0.667, 0.8, 0.0),
    "kurisu": VoiceProfile("kurisu", 0.92, 0.75, 0.85, 2.0),
}


def apply_voice_profile(settings: Settings, name: str, save: bool = True) -> VoiceProfile:
    key = name.strip().lower()
    if key not in VOICE_PROFILES:
        raise ValueError(
            f"Неизвестный голосовой профиль «{name}». Доступно: {', '.join(VOICE_PROFILES)}."
        )
    profile = VOICE_PROFILES[key]
    settings.set("voice.profile", profile.name, save=False)
    settings.set("voice.length_scale", profile.length_scale, save=False)
    settings.set("voice.noise_scale", profile.noise_scale, save=False)
    settings.set("voice.noise_w", profile.noise_w, save=False)
    settings.set("voice.pitch_semitones", profile.pitch_semitones, save=False)
    if save:
        settings.save()
    return profile
