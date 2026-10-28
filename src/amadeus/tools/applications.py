from __future__ import annotations

import shutil
import subprocess

from ..security.permissions import PermissionPolicy
from .registry import Tool, ToolError

MAX_ARGS = 20
MAX_ARG_LENGTH = 500


def _validate_args(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolError("Аргументы приложения должны быть списком строк.")
    if len(raw) > MAX_ARGS:
        raise ToolError(f"Слишком много аргументов (максимум {MAX_ARGS}).")
    result: list[str] = []
    for item in raw:
        value = str(item)
        if len(value) > MAX_ARG_LENGTH:
            raise ToolError("Слишком длинный аргумент приложения.")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ToolError("Недопустимые символы в аргументах приложения.")
        result.append(value)
    return result


def launch_application(arguments: dict[str, object], policy: PermissionPolicy) -> str:
    app = str(arguments.get("app", "")).strip()
    if not app:
        raise ToolError("Не указано приложение.")
    policy.check_app(app)
    args = _validate_args(arguments.get("args"))
    executable = shutil.which(app)
    if executable is None:
        raise ToolError(f"Приложение «{app}» не найдено в PATH.")
    try:
        subprocess.Popen(
            [executable, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ToolError(f"Не удалось запустить «{app}»: {exc}") from exc
    suffix = " с аргументами" if args else ""
    return f"Запущено приложение «{app}»{suffix}."


def application_tool(policy: PermissionPolicy) -> Tool:
    return Tool(
        name="launch_application",
        description=(
            "Запустить разрешённое приложение из allowlist. "
            "Требует подтверждения пользователя, если оно включено."
        ),
        risk="medium",
        handler=lambda arguments: launch_application(arguments, policy),
        requires_confirmation=policy.confirm_apps,
        parameters={
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Имя приложения из allowlist"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Безопасные аргументы без shell",
                },
            },
            "required": ["app"],
            "additionalProperties": False,
        },
    )
