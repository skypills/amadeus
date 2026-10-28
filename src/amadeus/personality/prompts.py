from __future__ import annotations

from pathlib import Path

from ..settings import DEFAULT_PERSONA, Settings
from .mood import MoodState, load_mood


def load_persona(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PERSONA.strip()
    return text or DEFAULT_PERSONA.strip()


def build_system_prompt(
    settings: Settings,
    persona_text: str,
    mood: MoodState | None = None,
    cloud: bool = False,
) -> str:
    mood = mood or load_mood(settings)
    parts = [persona_text.strip()]

    style = [
        "Текущий стиль:",
        f"- настроение: {mood.mood} ({mood.description})",
        f"- близость к пользователю: {mood.familiarity:.1f} из 1.0",
        f"- подробность ответов: {mood.verbosity:.1f} из 1.0",
        f"- инициативность: {mood.initiative:.1f} из 1.0",
        "Не выдумывай чувства, воспоминания и факты ради стиля.",
    ]
    parts.append("\n".join(style))

    if cloud:
        parts.append(
            "Внимание: запрос обрабатывается облачным провайдером. "
            "Не включай в ответ лишние персональные данные."
        )

    return "\n\n".join(part for part in parts if part.strip())
