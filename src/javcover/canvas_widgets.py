from __future__ import annotations

from math import ceil, floor, log10

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsView, QGridLayout, QWidget

RULER_SIZE = 24


class CanvasRuler(QWidget):
    guideRequested = Signal(str, int)
    guidePreviewChanged = Signal(str, object)

    def __init__(self, axis: str, view: QGraphicsView) -> None:
        super().__init__()
        self.axis = axis
        self.view = view
        self._dragging = False
        self.setMouseTracking(True)
        if axis == "x":
            self.setFixedHeight(RULER_SIZE)
            self.setMinimumWidth(RULER_SIZE)
        else:
            self.setFixedWidth(RULER_SIZE)
            self.setMinimumHeight(RULER_SIZE)
        self.setCursor(
            Qt.CursorShape.SizeVerCursor if axis == "x" else Qt.CursorShape.SizeHorCursor
        )

    def paintEvent(self, _event: object) -> None:
        del _event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#303640"))
        painter.setPen(QPen(QColor("#697381"), 1))
        if self.axis == "x":
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        scale = max(self.view.transform().m11(), 0.01)
        step = self._tick_step(scale)
        if self.axis == "x":
            start = self.view.mapToScene(QPoint(0, 0)).x()
            end = self.view.mapToScene(QPoint(self.view.viewport().width(), 0)).x()
            first = ceil(min(start, end) / step) * step
            for tick in range(first, int(max(start, end)) + step, step):
                x = self.view.mapFromScene(QPointF(tick, 0)).x()
                major = (tick // step) % 5 == 0
                painter.setPen(QPen(QColor("#c5ccd5"), 1))
                painter.drawLine(x, self.height() - (10 if major else 5), x, self.height())
                if major:
                    painter.drawText(QRectF(x + 2, 1, 54, self.height() - 9),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     str(tick))
        else:
            start = self.view.mapToScene(QPoint(0, 0)).y()
            end = self.view.mapToScene(QPoint(0, self.view.viewport().height())).y()
            first = ceil(min(start, end) / step) * step
            for tick in range(first, int(max(start, end)) + step, step):
                y = self.view.mapFromScene(QPointF(0, tick)).y()
                major = (tick // step) % 5 == 0
                painter.setPen(QPen(QColor("#c5ccd5"), 1))
                painter.drawLine(self.width() - (10 if major else 5), y, self.width(), y)
                if major:
                    painter.save()
                    painter.translate(1, y - 2)
                    painter.rotate(-90)
                    painter.drawText(QRectF(-38, -2, 48, 14), Qt.AlignmentFlag.AlignLeft, str(tick))
                    painter.restore()
        painter.end()

    @staticmethod
    def _tick_step(scale: float) -> int:
        desired = 65 / scale
        magnitude = 10 ** floor(log10(max(desired, 1)))
        for multiplier in (1, 2, 5, 10):
            step = multiplier * magnitude
            if step * scale >= 45:
                return max(1, int(step))
        return max(1, int(10 * magnitude))

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: object) -> None:
        if self._dragging:
            position = self._position_from_global(event.globalPosition().toPoint())
            self.guidePreviewChanged.emit(self.axis, position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            position = self._position_from_global(event.globalPosition().toPoint())
            if position is not None:
                self.guideRequested.emit(self.axis, position)
            self.guidePreviewChanged.emit(self.axis, None)
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _position_from_global(self, global_position: QPoint) -> int | None:
        viewport_position = self.view.viewport().mapFromGlobal(global_position)
        if not self.view.viewport().rect().contains(viewport_position):
            return None
        scene_position = self.view.mapToScene(viewport_position)
        if self.axis == "x":
            value = round(scene_position.x())
            limit = self.view.scene().sceneRect().width()
        else:
            value = round(scene_position.y())
            limit = self.view.scene().sceneRect().height()
        if not 0 <= value <= limit:
            return None
        return value


class RulerFrame(QWidget):
    guideRequested = Signal(str, int)
    guidePreviewChanged = Signal(str, object)

    def __init__(self, view: QGraphicsView) -> None:
        super().__init__()
        self.view = view
        self.horizontal_ruler = CanvasRuler("x", view)
        self.vertical_ruler = CanvasRuler("y", view)
        corner = QWidget()
        corner.setFixedSize(RULER_SIZE, RULER_SIZE)
        corner.setStyleSheet("background-color: #303640; border: 1px solid #697381;")
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(corner, 0, 0)
        layout.addWidget(self.horizontal_ruler, 0, 1)
        layout.addWidget(self.vertical_ruler, 1, 0)
        layout.addWidget(view, 1, 1)
        self.horizontal_ruler.guideRequested.connect(self.guideRequested)
        self.vertical_ruler.guideRequested.connect(self.guideRequested)
        self.horizontal_ruler.guidePreviewChanged.connect(self.guidePreviewChanged)
        self.vertical_ruler.guidePreviewChanged.connect(self.guidePreviewChanged)
        view.horizontalScrollBar().valueChanged.connect(self.update_rulers)
        view.verticalScrollBar().valueChanged.connect(self.update_rulers)
        if hasattr(view, "viewportChanged"):
            view.viewportChanged.connect(self.update_rulers)
        self.update_rulers()

    def update_rulers(self, *_args: object) -> None:
        del _args
        self.horizontal_ruler.update()
        self.vertical_ruler.update()
