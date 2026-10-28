from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

Messages = Sequence[dict[str, str]]
ChunkCallback = Callable[[str], None]


class ProviderError(RuntimeError):
    pass


class ProviderConnectionError(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    ok: bool
    detail: str
    models: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolChatResult:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class Provider(ABC):
    name: str
    supports_tools: bool = False

    @abstractmethod
    def chat(
        self,
        messages: Messages,
        stream: bool = True,
        on_chunk: ChunkCallback | None = None,
    ) -> str:
        """Return the full answer, optionally emitting chunks as they arrive."""

    @abstractmethod
    def status(self) -> ProviderStatus:
        pass

    def chat_tools(
        self,
        messages: Messages,
        tools: list[dict[str, object]],
        on_chunk: ChunkCallback | None = None,
    ) -> ToolChatResult:
        raise NotImplementedError("Провайдер не поддерживает вызов инструментов.")

    def format_tool_messages(
        self,
        result: ToolChatResult,
        executed: Sequence[tuple[ToolCall, str]],
    ) -> list[dict[str, object]]:
        raise NotImplementedError("Провайдер не поддерживает вызов инструментов.")
