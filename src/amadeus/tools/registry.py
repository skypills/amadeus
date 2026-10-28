from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..security.permissions import PermissionPolicy


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: str
    handler: Callable[[dict[str, object]], str]
    requires_confirmation: bool = False


class ToolRegistry:
    def __init__(self, policy: PermissionPolicy | None = None) -> None:
        self.policy = policy or PermissionPolicy()
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"Инструмент «{tool.name}» уже зарегистрирован.")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Инструмент «{name}» не зарегистрирован.") from exc

    def execute(self, name: str, arguments: dict[str, object], confirmed: bool = False) -> str:
        tool = self.get(name)
        if tool.requires_confirmation:
            self.policy.check_risk(tool.risk, tool.name, confirmed)
        else:
            self.policy.check_risk(tool.risk, tool.name, confirmed=True)
        return tool.handler(arguments)
