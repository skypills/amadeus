from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

ROLE_LABELS = {
    "user": "Вы",
    "assistant": "Amadeus",
    "system": "Система",
    "tool": "Инструмент",
}


class MessageBubble(QFrame):
    def __init__(self, role: str, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.setObjectName("bubbleUser" if role == "user" else "bubbleAssistant")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(4)

        header = QLabel(ROLE_LABELS.get(role, role))
        header.setObjectName("bubbleRole")
        self.body = QLabel(text)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout.addWidget(header)
        layout.addWidget(self.body)

    def set_text(self, text: str) -> None:
        self.body.setText(text)

    def text(self) -> str:
        return self.body.text()


class ChatView(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.setWidget(container)

    def add_message(self, role: str, text: str = "") -> MessageBubble:
        bubble = MessageBubble(role, text)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        self._scroll_to_bottom()
        return bubble

    def update_message(self, bubble: MessageBubble, text: str) -> None:
        bubble.set_text(text)
        self._scroll_to_bottom()

    def clear(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def is_empty(self) -> bool:
        return self._layout.count() <= 1

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()),
        )


class ChatInput(QPlainTextEdit):
    submitted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Сообщение… Enter — отправить, Shift+Enter — новая строка")
        self.setTabChangesFocus(True)
        self.setFixedHeight(84)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.submitted.emit()
                event.accept()
                return
        super().keyPressEvent(event)
