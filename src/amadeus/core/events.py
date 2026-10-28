from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

EventListener = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    kind: str
    message: str
    data: dict[str, object] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def emit(self, kind: str, message: str, **data: object) -> None:
        event = Event(kind=kind, message=message, data=dict(data))
        for listener in self._listeners:
            listener(event)
