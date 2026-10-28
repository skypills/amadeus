from __future__ import annotations

from dataclasses import dataclass

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

ALLOWED_APPS = frozenset(
    {
        "firefox",
        "chromium",
        "code",
        "kitty",
        "alacritty",
        "thunar",
        "dolphin",
        "telegram-desktop",
        "spotify",
    }
)

DANGEROUS_ACTIONS = frozenset(
    {
        "delete_files",
        "install_packages",
        "change_system_settings",
        "sudo",
    }
)


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class PermissionPolicy:
    allowed_apps: frozenset[str] = ALLOWED_APPS
    confirm_apps: bool = True
    allow_high_risk: bool = False

    def is_app_allowed(self, app: str) -> bool:
        return app in self.allowed_apps

    def check_app(self, app: str) -> None:
        if not self.is_app_allowed(app):
            raise PermissionDenied(
                f"Приложение «{app}» не разрешено. Добавьте его в allowlist осознанно."
            )

    def requires_confirmation(self, risk: str, action: str = "") -> bool:
        if risk == RISK_HIGH:
            return True
        if risk == RISK_MEDIUM:
            return True
        return action in DANGEROUS_ACTIONS

    def check_risk(self, risk: str, action: str, confirmed: bool) -> None:
        if risk not in (RISK_LOW, RISK_MEDIUM, RISK_HIGH):
            raise ValueError(f"Неизвестный уровень риска: {risk}")
        if risk == RISK_HIGH and not self.allow_high_risk:
            raise PermissionDenied(f"Действие «{action}» запрещено политикой.")
        if self.requires_confirmation(risk, action) and not confirmed:
            raise PermissionDenied(
                f"Действие «{action}» требует явного подтверждения пользователя."
            )
