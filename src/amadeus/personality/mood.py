from __future__ import annotations

from dataclasses import dataclass

from ..settings import Settings

MOODS: dict[str, str] = {
    "calm": "Спокойный, точный и структурированный тон. Без панибратства.",
    "friendly": "Дружелюбный и естественный тон, как у внимательного собеседника.",
    "technical": "Максимально краткий технический стиль: факты, команды, шаги.",
    "supportive": "Поддерживающий тон, но без ложных обещаний и выдуманных чувств.",
}

DEFAULT_PARAMETERS = {
    "mood": "calm",
    "familiarity": 0.4,
    "verbosity": 0.5,
    "initiative": 0.3,
}


@dataclass(frozen=True)
class MoodState:
    mood: str
    familiarity: float
    verbosity: float
    initiative: float

    @property
    def description(self) -> str:
        return MOODS.get(self.mood, MOODS["calm"])


def _clamp(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, number))


def load_mood(settings: Settings) -> MoodState:
    mood = str(settings.get("personality.mood", "calm"))
    if mood not in MOODS:
        mood = "calm"
    return MoodState(
        mood=mood,
        familiarity=_clamp(settings.get("personality.familiarity"), 0.4),
        verbosity=_clamp(settings.get("personality.verbosity"), 0.5),
        initiative=_clamp(settings.get("personality.initiative"), 0.3),
    )


def set_mood(settings: Settings, mood: str) -> MoodState:
    mood = mood.strip().lower()
    if mood not in MOODS:
        raise ValueError(f"Неизвестное настроение «{mood}». Доступно: {', '.join(MOODS)}.")
    settings.set("personality.mood", mood)
    return load_mood(settings)


def set_parameter(settings: Settings, name: str, value: object) -> MoodState:
    if name not in ("familiarity", "verbosity", "initiative"):
        raise ValueError("Можно менять familiarity, verbosity или initiative.")
    settings.set(f"personality.{name}", _clamp(value, DEFAULT_PARAMETERS[name]))
    return load_mood(settings)


def reset_mood(settings: Settings) -> MoodState:
    for key, value in DEFAULT_PARAMETERS.items():
        settings.set(f"personality.{key}", value, save=False)
    settings.save()
    return load_mood(settings)
