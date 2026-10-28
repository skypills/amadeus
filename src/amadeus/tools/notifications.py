from __future__ import annotations

import shutil
import subprocess

from .registry import Tool, ToolError


def _clean(value: object, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def send_notification(arguments: dict[str, object]) -> str:
    executable = shutil.which("notify-send")
    if executable is None:
        raise ToolError(
            "notify-send не найден. Установите libnotify и проверьте демон уведомлений."
        )
    title = _clean(arguments.get("title", "Amadeus"), 120) or "Amadeus"
    text = _clean(arguments.get("text", ""), 2000)
    if not text:
        raise ToolError("Текст уведомления не может быть пустым.")
    try:
        process = subprocess.run(
            [executable, "-a", "Amadeus", "--", title, text],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"Не удалось отправить уведомление: {exc}") from exc
    if process.returncode != 0:
        detail = " ".join((process.stderr or process.stdout).split())[:300]
        raise ToolError(f"notify-send завершился с ошибкой: {detail}")
    return f"Уведомление отправлено: {title}"


def notification_tool() -> Tool:
    return Tool(
        name="send_notification",
        description="Показать пользователю системное уведомление на рабочем столе.",
        risk="low",
        handler=send_notification,
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Короткий заголовок"},
                "text": {"type": "string", "description": "Текст уведомления"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    )
