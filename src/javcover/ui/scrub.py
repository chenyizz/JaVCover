"""A QSpinBox that can be scrubbed (dragged) to change its value, like Photoshop."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSpinBox, QWidget


class ScrubSpinBox(QSpinBox):
    """Drag horizontally on the field to change the value; click to type."""

    PIXELS_PER_STEP = 4
    BUTTON_WIDTH = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scrubbing = False
        self._scrub_start_x = 0
        self._scrub_value = 0

    def _over_buttons(self, x: int) -> bool:
        return x >= self.width() - self.BUTTON_WIDTH

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._over_buttons(
            event.position().toPoint().x()
        ):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._scrubbing = True
            self._scrub_start_x = event.globalPosition().toPoint().x()
            self._scrub_value = self.value()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: object) -> None:
        if self._scrubbing:
            delta = event.globalPosition().toPoint().x() - self._scrub_start_x
            self.setValue(
                self._scrub_value + (delta // self.PIXELS_PER_STEP) * self.singleStep()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._scrubbing:
            self._scrubbing = False
            moved = abs(event.globalPosition().toPoint().x() - self._scrub_start_x)
            if moved < 3:
                self.selectAll()
            event.accept()
            return
        super().mouseReleaseEvent(event)
