from __future__ import annotations

from ..security.permissions import ALLOWED_APPS, PermissionPolicy
from ..settings import Settings
from .applications import application_tool
from .notifications import notification_tool
from .registry import ToolRegistry
from .system_info import system_info_tool


def build_registry(settings: Settings | None = None) -> ToolRegistry:
    policy = PermissionPolicy()
    if settings is not None:
        raw_apps = settings.get("security.allowed_apps", sorted(ALLOWED_APPS))
        if isinstance(raw_apps, list):
            apps = frozenset(str(item).strip() for item in raw_apps if str(item).strip())
        else:
            apps = ALLOWED_APPS
        policy = PermissionPolicy(
            allowed_apps=apps,
            confirm_apps=bool(settings.get("security.confirm_app_launch", True)),
        )
    registry = ToolRegistry(policy)
    registry.register(notification_tool())
    registry.register(application_tool(policy))
    registry.register(system_info_tool())
    return registry
