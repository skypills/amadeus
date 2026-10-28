from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ..storage import paths
from .registry import Tool, ToolError

CLIPBOARD_LIMIT = 200_000


def _run(command: list[str], *, timeout: float = 10, input_text: str | None = None):
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Команда {Path(command[0]).name} не завершилась вовремя.") from exc
    except OSError as exc:
        raise ToolError(f"Не удалось запустить {Path(command[0]).name}: {exc}") from exc


def copy_to_clipboard(arguments: dict[str, object]) -> str:
    text = str(arguments.get("text", ""))
    if not text.strip():
        raise ToolError("Нечего копировать: пустой текст.")
    if len(text) > CLIPBOARD_LIMIT:
        raise ToolError("Текст слишком длинный для буфера обмена.")
    candidates = (
        ("wl-copy", []),
        ("xclip", ["-selection", "clipboard"]),
        ("xsel", ["--clipboard", "--input"]),
    )
    errors: list[str] = []
    for name, extra in candidates:
        executable = shutil.which(name)
        if executable is None:
            continue
        process = _run([executable, *extra], timeout=5, input_text=text)
        if process.returncode == 0:
            return f"Скопировано символов: {len(text)}."
        errors.append(f"{name}: {process.stderr.strip()[:120]}")
    detail = "; ".join(errors) if errors else "не найдены wl-copy, xclip или xsel"
    raise ToolError(f"Не удалось скопировать в буфер обмена ({detail}).")


def take_screenshot(arguments: dict[str, object] | None = None) -> str:
    directory = paths.data_dir() / "screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"amadeus-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    candidates = (
        ("grim", lambda exe: [exe, str(target)]),
        ("spectacle", lambda exe: [exe, "-b", "-n", "-o", str(target)]),
        ("gnome-screenshot", lambda exe: [exe, "-f", str(target)]),
        ("scrot", lambda exe: [exe, str(target)]),
    )
    errors: list[str] = []
    for name, build in candidates:
        executable = shutil.which(name)
        if executable is None:
            continue
        process = _run(build(executable), timeout=20)
        if process.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return f"Скриншот сохранён: {target}"
        errors.append(f"{name}: {process.stderr.strip()[:120]}")
    detail = (
        "; ".join(errors) if errors else "не найдены grim, spectacle, gnome-screenshot или scrot"
    )
    raise ToolError(f"Не удалось сделать скриншот ({detail}).")


def get_volume(arguments: dict[str, object] | None = None) -> str:
    executable = shutil.which("wpctl")
    if executable is None:
        raise ToolError("wpctl не найден. Установите wireplumber.")
    process = _run([executable, "get-volume", "@DEFAULT_AUDIO_SINK@"])
    if process.returncode != 0:
        raise ToolError(
            "Не удалось прочитать громкость: "
            + (process.stderr.strip()[:200] or "нет аудиоустройства")
        )
    return process.stdout.strip() or "громкость неизвестна"


def set_volume(arguments: dict[str, object]) -> str:
    try:
        percent = int(arguments.get("percent", 50))
    except (TypeError, ValueError) as exc:
        raise ToolError("Громкость должна быть целым числом от 0 до 150.") from exc
    if not 0 <= percent <= 150:
        raise ToolError("Громкость должна быть от 0 до 150.")
    executable = shutil.which("wpctl")
    if executable is None:
        raise ToolError("wpctl не найден. Установите wireplumber.")
    process = _run([executable, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"])
    if process.returncode != 0:
        raise ToolError(
            "Не удалось изменить громкость: "
            + (process.stderr.strip()[:200] or "нет аудиоустройства")
        )
    return f"Громкость: {percent}%."


MEDIA_ACTIONS = {
    "play-pause": "play-pause",
    "play": "play",
    "pause": "pause",
    "next": "next",
    "previous": "previous",
    "prev": "previous",
    "stop": "stop",
}


def media_control(arguments: dict[str, object]) -> str:
    action = str(arguments.get("action", "")).strip().lower()
    if action not in MEDIA_ACTIONS:
        raise ToolError("Действие должно быть одним из: " + ", ".join(sorted(MEDIA_ACTIONS)))
    executable = shutil.which("playerctl")
    if executable is None:
        raise ToolError("playerctl не найден. Установите playerctl.")
    process = _run([executable, MEDIA_ACTIONS[action]])
    if process.returncode != 0:
        raise ToolError(
            "Не удалось управлять плеером: "
            + (process.stderr.strip()[:200] or "нет активного плеера")
        )
    return f"Медиа: {action}."


def open_url(arguments: dict[str, object]) -> str:
    url = str(arguments.get("url", "")).strip()
    if len(url) > 2000 or any(char in url for char in ("\x00", "\n", "\r")):
        raise ToolError("Некорректный URL.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("Разрешены только http/https URL.")
    executable = shutil.which("xdg-open")
    if executable is None:
        raise ToolError("xdg-open не найден. Установите xdg-utils.")
    try:
        subprocess.Popen(
            [executable, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ToolError(f"Не удалось открыть URL: {exc}") from exc
    return f"Открываю: {url}"


def clipboard_tool() -> Tool:
    return Tool(
        name="copy_clipboard",
        description="Скопировать текст в системный буфер обмена.",
        risk="low",
        handler=copy_to_clipboard,
        allow_model=False,
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )


def screenshot_tool() -> Tool:
    return Tool(
        name="screenshot",
        description="Сделать скриншот экрана (Wayland/X11).",
        risk="medium",
        handler=take_screenshot,
        requires_confirmation=True,
        allow_model=False,
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )


def volume_tools() -> tuple[Tool, Tool]:
    get_tool = Tool(
        name="get_volume",
        description="Показать текущую громкость аудиовыхода.",
        risk="low",
        handler=get_volume,
        allow_model=True,
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )
    set_tool = Tool(
        name="set_volume",
        description="Установить громкость аудиовыхода в процентах (0–150).",
        risk="low",
        handler=set_volume,
        allow_model=False,
        parameters={
            "type": "object",
            "properties": {
                "percent": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 150,
                }
            },
            "required": ["percent"],
            "additionalProperties": False,
        },
    )
    return get_tool, set_tool


def media_tool() -> Tool:
    return Tool(
        name="media_control",
        description="Управлять активным медиаплеером: play-pause, next, previous, stop.",
        risk="low",
        handler=media_control,
        allow_model=False,
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(MEDIA_ACTIONS),
                }
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    )


def open_url_tool() -> Tool:
    return Tool(
        name="open_url",
        description="Открыть http/https ссылку в браузере по умолчанию.",
        risk="medium",
        handler=open_url,
        requires_confirmation=True,
        allow_model=False,
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    )
