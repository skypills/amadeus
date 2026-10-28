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


class Provider(ABC):
    name: str

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
