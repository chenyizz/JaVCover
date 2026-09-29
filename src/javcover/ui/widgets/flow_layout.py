"""A wrapping layout: items flow left-to-right and wrap to the next row."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QStyle, QWidget


class FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        hspacing: int = 2,
        vspacing: int = 2,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _smart_spacing(self, metric: QStyle.PixelMetric) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        if isinstance(parent, QWidget):
            return parent.style().pixelMetric(metric, None, parent)
        return parent.spacing()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            hspacing = (
                self._hspacing
                if self._hspacing >= 0
                else self._smart_spacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)
            )
            vspacing = (
                self._vspacing
                if self._vspacing >= 0
                else self._smart_spacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)
            )
            hint = item.sizeHint()
            next_x = x + hint.width() + hspacing
            if next_x - hspacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + vspacing
                next_x = x + hint.width() + hspacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
