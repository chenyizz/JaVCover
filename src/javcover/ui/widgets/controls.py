"""Small reusable Qt widgets/effects for the main window."""
from __future__ import annotations

import sys
from pathlib import Path

# Support both `python -m javcover.app` and editors that execute this file directly.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QIcon
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QToolButton, QToolTip, QWidget

from javcover.core.resources import ICON_DIR


class _ToolButtonFeedback(QObject):
    def __init__(self, button: QToolButton) -> None:
        super().__init__(button)
        self.button = button
        self._hovered = False
        self.shadow = QGraphicsDropShadowEffect(button)
        self.shadow.setBlurRadius(0)
        self.shadow.setOffset(0, 0)
        self.shadow.setColor(QColor(20, 28, 36, 70))
        button.setGraphicsEffect(self.shadow)
        self._blur_animation = QPropertyAnimation(self.shadow, b"blurRadius", self)
        self._blur_animation.setDuration(240)
        self._blur_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        button.toggled.connect(lambda _checked: self._animate_state())
        button.installEventFilter(self)
        self._animate_state()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.button:
            if event.type() == QEvent.Type.Enter:
                self._hovered = True
                self._animate_state()
            elif event.type() == QEvent.Type.Leave:
                self._hovered = False
                self._animate_state()
        return False

    def _animate_state(self) -> None:
        selected = self.button.isChecked()
        target = 6.0 if selected else (3.0 if self._hovered else 0.0)
        self._blur_animation.stop()
        self._blur_animation.setStartValue(self.shadow.blurRadius())
        self._blur_animation.setEndValue(target)
        self._blur_animation.start()


class _WindowControlButton(QToolButton):
    def __init__(
        self, control: str, accessible_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.control = control
        self._maximized = False
        self._fullscreen = False
        self._hovered = False
        self._icons: dict[str, QIcon] = {}
        self.setObjectName("windowControl")
        self.setAccessibleName(accessible_name)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(46, 36)
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.installEventFilter(self)
        self._refresh_icon()

    def set_maximized(self, maximized: bool) -> None:
        if self._maximized != maximized:
            self._maximized = maximized
            self._refresh_icon()

    def set_fullscreen(self, fullscreen: bool) -> None:
        if self._fullscreen != fullscreen:
            self._fullscreen = fullscreen
            self._refresh_icon()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self and event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            hovered = event.type() == QEvent.Type.Enter
            if self._hovered != hovered:
                self._hovered = hovered
                self._refresh_icon()
        return super().eventFilter(watched, event)

    def _refresh_icon(self) -> None:
        if self.control == "minimize":
            name = "window-minimize.svg"
        elif self.control == "maximize":
            name = "window-restore.svg" if self._maximized else "window-maximize.svg"
        elif self.control == "fullscreen":
            name = (
                "window-fullscreen-exit.svg"
                if self._fullscreen
                else "window-fullscreen.svg"
            )
        else:
            name = "window-close-hover.svg" if self._hovered else "window-close.svg"

        icon = self._icons.get(name)
        if icon is None:
            icon_path = ICON_DIR / name
            if not icon_path.is_file():
                raise FileNotFoundError(f"Window control icon not found: {icon_path}")
            icon = QIcon(str(icon_path))
            if icon.isNull():
                raise RuntimeError(f"Unable to load window control icon: {icon_path}")
            self._icons[name] = icon
        self.setIcon(icon)


class _DelayedToolTip(QObject):
    def __init__(self, widget: QWidget, text: str) -> None:
        super().__init__(widget)
        self.widget = widget
        self.text = text
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self._show)
        widget.setToolTip("")
        widget.installEventFilter(self)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.widget:
            if event.type() == QEvent.Type.Enter:
                self.timer.start()
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
                self.timer.stop()
                QToolTip.hideText()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return False

    def _show(self) -> None:
        if self.widget.underMouse():
            QToolTip.showText(QCursor.pos(), self.text, self.widget)


