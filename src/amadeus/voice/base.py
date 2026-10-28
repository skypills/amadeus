from __future__ import annotations

import shlex
import shutil
from pathlib import Path


class VoiceError(RuntimeError):
    pass


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise VoiceError(f"Некорректная команда «{command}»: {exc}") from exc


def resolve_executable(command: str) -> str:
    parts = split_command(command)
    if not parts:
        raise VoiceError("Команда не задана.")
    candidate = Path(parts[0]).expanduser()
    if candidate.exists():
        return str(candidate)
    found = shutil.which(parts[0])
    if found is None:
        raise VoiceError(
            f"Программа «{parts[0]}» не найдена в PATH. "
            "Установите её и укажите путь в настройках [voice]."
        )
    return found


def tail(text: str, limit: int = 400) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]
