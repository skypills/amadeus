from __future__ import annotations

import os
import random
import shutil
import subprocess

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

CHIBI_SIZE = 104
CHIBI_TITLE = "AmadeusChibi"
CHIBI_SELECTOR = f"title:^({CHIBI_TITLE})$"


class ChibiWindow(QWidget):
    open_requested = Signal()
    settings_requested = Signal()
    hide_requested = Signal()
    quit_requested = Signal()

    def __init__(self, use_hyprland: bool | None = None) -> None:
        super().__init__()
        self.setWindowTitle(CHIBI_TITLE)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(CHIBI_SIZE, CHIBI_SIZE)
        self.setToolTip("Курису — Amadeus. Двойной клик: открыть ассистента.")

        self._screen = QGuiApplication.primaryScreen()
        geometry = (
            self._screen.availableGeometry() if self._screen is not None else QRect(0, 0, 1280, 720)
        )
        self._area = geometry
        self._x = float(max(geometry.left(), geometry.right() - CHIBI_SIZE - 30))
        self._y = float(max(geometry.top(), geometry.bottom() - CHIBI_SIZE - 12))
        self._target_x = self._x
        self._target_y = self._y
        self._frame = 0
        self._direction = -1
        self._pause = 0
        self._dragging = False
        self._drag_offset = QPoint()

        self._use_hyprland = (
            bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
            and shutil.which("hyprctl") is not None
            if use_hyprland is None
            else use_hyprland
        )
        self._hypr: subprocess.Popen | None = None
        self._hypr_failed = False

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._choose_target()
        self.move(int(self._x), int(self._y))
        QTimer.singleShot(250, self._configure_hyprland)

        self._menu = QMenu()
        open_action = self._menu.addAction("Открыть Amadeus")
        open_action.triggered.connect(self.open_requested.emit)
        settings_action = self._menu.addAction("Настройки…")
        settings_action.triggered.connect(self.settings_requested.emit)
        hide_action = self._menu.addAction("Скрыть чиби")
        hide_action.triggered.connect(self.hide_requested.emit)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("Выход")
        quit_action.triggered.connect(self.quit_requested.emit)

    def _hypr_command(self, code: str) -> None:
        if not self._use_hyprland or self._hypr_failed:
            return
        try:
            if self._hypr is None or self._hypr.poll() is not None:
                self._hypr = subprocess.Popen(
                    ["hyprctl", "repl"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            assert self._hypr.stdin is not None
            self._hypr.stdin.write(code + "\n")
            self._hypr.stdin.flush()
        except (OSError, BrokenPipeError):
            self._hypr_failed = True
            self._hypr = None

    def _dispatch_move(self, x: int, y: int) -> None:
        self._hypr_command(
            f'hl.dispatch(hl.dsp.window.move({{window="{CHIBI_SELECTOR}", x={x}, y={y}}}))'
        )

    def _configure_hyprland(self) -> None:
        if not self._use_hyprland:
            return
        self._hypr_command(
            f'hl.dispatch(hl.dsp.window.float({{window="{CHIBI_SELECTOR}", action="enable"}}))'
        )
        self._hypr_command(
            f'hl.dispatch(hl.dsp.window.resize({{window="{CHIBI_SELECTOR}", '
            f"x={CHIBI_SIZE}, y={CHIBI_SIZE}}}))"
        )
        self._dispatch_move(int(self._x), int(self._y))

    def _move_to(self, x: float, y: float) -> None:
        self._x = x
        self._y = y
        if self._use_hyprland:
            self._dispatch_move(round(x), round(y))
        else:
            self.move(round(x), round(y))

    def _choose_target(self) -> None:
        margin = 12
        left = self._area.left() + margin
        right = max(left, self._area.right() - CHIBI_SIZE - margin)
        top = self._area.top() + 72
        bottom = max(top, self._area.bottom() - CHIBI_SIZE - margin)
        self._target_x = float(random.randint(left, right))
        self._target_y = float(random.randint(top, bottom))

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % 4
        self.update()
        if self._dragging:
            return
        if self._pause > 0:
            self._pause -= 1
            return
        dx = self._target_x - self._x
        dy = self._target_y - self._y
        distance = (dx * dx + dy * dy) ** 0.5
        if distance < 4:
            self._pause = random.randint(8, 26)
            self._choose_target()
            return
        step = min(4.0, distance)
        self._direction = 1 if dx >= 0 else -1
        self._move_to(self._x + dx / distance * step, self._y + dy / distance * step)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            global_pos = event.globalPosition().toPoint()
            self._drag_offset = global_pos - QPoint(round(self._x), round(self._y))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._dragging:
            point = event.globalPosition().toPoint() - self._drag_offset
            x = max(
                self._area.left(),
                min(point.x(), self._area.right() - CHIBI_SIZE),
            )
            y = max(
                self._area.top(),
                min(point.y(), self._area.bottom() - CHIBI_SIZE),
            )
            self._target_x = float(x)
            self._target_y = float(y)
            self._move_to(float(x), float(y))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._choose_target()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._menu.exec(event.globalPos())
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawEllipse(24, 95, 56, 7)

        phase = self._frame
        bounce = (0, -2, 0, -1)[phase]
        leg = (-4, 0, 4, 0)[phase]
        arm = (4, 0, -4, 0)[phase]
        cx = 52
        cy = 41 + bounce

        painter.save()
        if self._direction < 0:
            painter.translate(CHIBI_SIZE, 0)
            painter.scale(-1, 1)

        outline = QPen(QColor("#3b2a20"), 1.4)
        hair = QColor("#6b4328")
        hair_light = QColor("#8a5a38")
        coat = QColor("#f7f7f5")
        coat_shadow = QColor("#d8dce2")
        skin = QColor("#f3c9a7")
        skirt = QColor("#3f5f8f")
        accent = QColor("#4f8fd6")

        # legs (under the coat)
        painter.setPen(QPen(skin, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(cx - 9, cy + 34, cx - 12 + leg, cy + 48)
        painter.drawLine(cx + 9, cy + 34, cx + 12 - leg, cy + 48)
        painter.setPen(QPen(QColor("#51372a"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(cx - 12 + leg, cy + 48, cx - 15 + leg, cy + 50)
        painter.drawLine(cx + 12 - leg, cy + 48, cx + 15 - leg, cy + 50)

        # arms
        painter.setPen(QPen(skin, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(cx - 18, cy + 25, cx - 27, cy + 38 + arm)
        painter.drawLine(cx + 18, cy + 25, cx + 27, cy + 38 - arm)

        # hair back
        painter.setPen(outline)
        painter.setBrush(hair)
        painter.drawEllipse(cx - 23, cy - 24, 46, 47)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hair_light)
        painter.drawEllipse(cx - 21, cy - 20, 14, 20)

        # body / skirt / lab coat
        painter.setPen(outline)
        painter.setBrush(skirt)
        painter.drawRoundedRect(cx - 16, cy + 29, 32, 15, 5, 5)
        painter.setBrush(coat)
        painter.drawPolygon(
            [
                QPoint(cx - 16, cy + 13),
                QPoint(cx + 16, cy + 13),
                QPoint(cx + 21, cy + 37),
                QPoint(cx + 7, cy + 41),
                QPoint(cx, cy + 35),
                QPoint(cx - 7, cy + 41),
                QPoint(cx - 21, cy + 37),
            ]
        )
        painter.setPen(QPen(coat_shadow, 1))
        painter.drawLine(cx - 3, cy + 20, cx - 3, cy + 38)
        painter.drawLine(cx + 3, cy + 20, cx + 3, cy + 38)

        # collar ribbon
        painter.setPen(outline)
        painter.setBrush(accent)
        painter.drawPolygon(
            [
                QPoint(cx - 10, cy + 13),
                QPoint(cx, cy + 20),
                QPoint(cx + 10, cy + 13),
                QPoint(cx, cy + 26),
            ]
        )

        # head
        painter.setBrush(skin)
        painter.drawEllipse(cx - 18, cy - 20, 36, 36)

        # bangs and side locks
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hair)
        painter.drawEllipse(cx - 20, cy - 22, 40, 20)
        painter.drawPolygon(
            [QPoint(cx - 20, cy - 12), QPoint(cx - 14, cy + 2), QPoint(cx - 20, cy + 12)]
        )
        painter.drawPolygon(
            [QPoint(cx + 20, cy - 12), QPoint(cx + 14, cy + 2), QPoint(cx + 20, cy + 12)]
        )
        painter.setBrush(hair_light)
        painter.drawEllipse(cx - 14, cy - 19, 16, 8)

        # eyes and face
        painter.setBrush(QColor("#3a7fb8"))
        painter.drawEllipse(cx - 9, cy - 1, 5, 7)
        painter.drawEllipse(cx + 4, cy - 1, 5, 7)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(cx - 8, cy, 2, 2)
        painter.drawEllipse(cx + 5, cy, 2, 2)
        painter.setPen(QPen(QColor("#b9766b"), 1.4))
        painter.drawLine(cx - 4, cy + 11, cx + 3, cy + 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(235, 150, 150, 90))
        painter.drawEllipse(cx - 14, cy + 7, 7, 4)
        painter.drawEllipse(cx + 7, cy + 7, 7, 4)

        painter.restore()
        painter.end()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        if self._hypr is not None and self._hypr.poll() is None:
            self._hypr.terminate()
            try:
                self._hypr.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._hypr.kill()
        self._hypr = None
        super().closeEvent(event)
