"""Reusable image-in-frame editor (QGraphicsView) with rulers, zoom, pan, crop.

Being a ``QGraphicsView`` lets it reuse :class:`javcover.services.canvas_widgets.RulerFrame`
for pixel rulers and guide creation, matching the main cover canvas. It reuses
the crop overlay and the shared image mapping; it never touches project data.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from javcover.core.crop import crop_image_to_rect, image_rect_mapping
from javcover.core.errors import ImageError
from javcover.core.models import Guide
from javcover.services.image_ops import encode_png
from javcover.ui.canvas.crop import HIT_TOLERANCE_PX, CropOverlay

_MIN_ZOOM = 0.2
_MAX_ZOOM = 12.0
_SNAP_PX = 6.0


class ImageEditor(QGraphicsView):
    changed = Signal()
    zoomChanged = Signal(float)
    pointerMoved = Signal(int, int)
    viewportChanged = Signal()

    def __init__(
        self,
        image: QImage,
        frame: QSize,
        fit: str,
        offset: tuple[int, int],
        *,
        allow_pan: bool = True,
        allow_crop: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.image = image
        self.frame_w = frame.width()
        self.frame_h = frame.height()
        self.fit = fit
        self.offset = [offset[0], offset[1]]
        self.allow_pan = allow_pan
        self.allow_crop = allow_crop
        self.mode = "pan" if allow_pan else "crop"
        self.grid_step = 50
        self.snap_enabled = True
        self.crop_overlay = CropOverlay(QRectF(0, 0, self.frame_w, self.frame_h), 0)
        self.guides: list[Guide] = []
        self._base_scale = 1.0
        self._fitted = False
        self._drag: str | None = None
        self._drag_start = QPointF()
        self._rect_start = QRectF()
        self._offset_start = (0, 0)
        self._pan_start = QPointF()
        self._scroll_start = (0, 0)
        self._scene.setSceneRect(0, 0, self.frame_w, self.frame_h)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#2b2f36"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QTimer.singleShot(0, self.fit_to_window)

    # -- public state -----------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._drag = None
        self.viewport().update()

    def fit_to_window(self) -> None:
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._base_scale = max(self.transform().m11(), 0.01)
        self._fitted = True
        self.zoomChanged.emit(1.0)
        self.viewportChanged.emit()

    def set_zoom(self, zoom: float) -> None:
        zoom = min(max(zoom, _MIN_ZOOM), _MAX_ZOOM)
        self.resetTransform()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._base_scale = max(self.transform().m11(), 0.01)
        self.scale(zoom, zoom)
        self.zoomChanged.emit(zoom)
        self.viewportChanged.emit()

    def current_zoom(self) -> float:
        return max(self.transform().m11(), 0.01) / max(self._base_scale, 0.01)

    def result_offset(self) -> tuple[int, int]:
        return (int(round(self.offset[0])), int(round(self.offset[1])))

    def crop_rect(self) -> QRectF:
        return QRectF(self.crop_overlay.rect)

    def add_guide(self, axis: str, position: int) -> None:
        if axis not in ("x", "y"):
            return
        limit = self.frame_w if axis == "x" else self.frame_h
        position = min(max(0, position), limit)
        self.guides.append(Guide(axis, position))
        self.viewport().update()

    def clear_guides(self) -> None:
        self.guides.clear()
        self.viewport().update()

    # -- events -----------------------------------------------------------
    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if not self._fitted:
            self.fit_to_window()
        self.viewportChanged.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewportChanged.emit()

    def wheelEvent(self, event: object) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.1 if delta > 0 else 1 / 1.1
        current = self.current_zoom()
        if not _MIN_ZOOM <= current * factor <= _MAX_ZOOM:
            return
        self.scale(factor, factor)
        self.zoomChanged.emit(self.current_zoom())
        self.viewportChanged.emit()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        bounds = QRectF(0, 0, self.frame_w, self.frame_h)
        painter.fillRect(bounds, QColor("#ffffff"))
        drawn, source = image_rect_mapping(
            self.image, bounds, self.fit, tuple(self.offset)
        )
        painter.save()
        painter.setClipRect(bounds)
        painter.drawImage(drawn, self.image, source)
        if self.grid_step > 0 and self.grid_step * self.transform().m11() >= 5:
            pen = QPen(QColor(30, 40, 55, 90), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            value = float(self.grid_step)
            while value < self.frame_w:
                painter.drawLine(QPointF(value, 0), QPointF(value, self.frame_h))
                value += self.grid_step
            value = float(self.grid_step)
            while value < self.frame_h:
                painter.drawLine(QPointF(0, value), QPointF(self.frame_w, value))
                value += self.grid_step
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if self.mode == "crop" and self.allow_crop:
            self.crop_overlay.paint(painter)
        for guide in self.guides:
            line = (
                (guide.position, 0, guide.position, self.frame_h)
                if guide.axis == "x"
                else (0, guide.position, self.frame_w, guide.position)
            )
            pen = QPen(QColor("#00d9ff"), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(*line)

    # -- snapping ---------------------------------------------------------
    def _snap(self, rect: QRectF) -> QRectF:
        if not self.snap_enabled:
            return rect
        tolerance = _SNAP_PX / max(self.transform().m11(), 0.1)
        x_targets = (0.0, self.frame_w / 2, float(self.frame_w))
        y_targets = (0.0, self.frame_h / 2, float(self.frame_h))
        for guide in self.guides:
            if guide.axis == "x":
                x_targets += (float(guide.position),)
            else:
                y_targets += (float(guide.position),)

        def best(edges: tuple[float, ...], targets: tuple[float, ...]) -> float:
            found, distance = 0.0, tolerance + 1
            for edge in edges:
                for target in targets:
                    delta = target - edge
                    if abs(delta) <= tolerance and abs(delta) < distance:
                        distance, found = abs(delta), delta
                if self.grid_step > 0:
                    target = round(edge / self.grid_step) * self.grid_step
                    delta = target - edge
                    if abs(delta) <= tolerance and abs(delta) < distance:
                        distance, found = abs(delta), delta
            return found

        dx = best((rect.left(), rect.center().x(), rect.right()), x_targets)
        dy = best((rect.top(), rect.center().y(), rect.bottom()), y_targets)
        return QRectF(
            rect.x() + dx, rect.y() + dy, rect.width(), rect.height()
        ).intersected(QRectF(0, 0, self.frame_w, self.frame_h))

    # -- pointer ----------------------------------------------------------
    def mousePressEvent(self, event: object) -> None:
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._drag = "pan"
            self._pan_start = event.position().toPoint()
            self._scroll_start = (
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        if self.mode == "crop" and self.allow_crop:
            tolerance = HIT_TOLERANCE_PX / max(self.transform().m11(), 0.01)
            handle = self.crop_overlay.handle_at(point, tolerance)
            if handle is not None:
                self._drag = handle
                self._rect_start = QRectF(self.crop_overlay.rect)
            elif self.crop_overlay.contains(point):
                self._drag = "move"
                self._rect_start = QRectF(self.crop_overlay.rect)
            else:
                self._drag = "new"
                self._rect_start = QRectF(point, point)
            self._drag_start = point
        elif self.allow_pan:
            self._drag = "image"
            self._drag_start = point
            self._offset_start = (self.offset[0], self.offset[1])
        event.accept()

    def mouseMoveEvent(self, event: object) -> None:
        point = self.mapToScene(event.position().toPoint())
        self.pointerMoved.emit(round(point.x()), round(point.y()))
        if self._drag is None:
            return
        if self._drag == "pan":
            delta = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(self._scroll_start[0] - delta.x())
            self.verticalScrollBar().setValue(self._scroll_start[1] - delta.y())
            return
        if self._drag == "image":
            self.offset = [
                self._offset_start[0] + (point.x() - self._drag_start.x()),
                self._offset_start[1] + (point.y() - self._drag_start.y()),
            ]
            self.viewport().update()
            self.changed.emit()
            return
        modifiers = event.modifiers()
        if self._drag == "new":
            rect = QRectF(self._drag_start, point).normalized()
        elif self._drag == "move":
            rect = self._rect_start.translated(point - self._drag_start)
        else:
            rect = self.crop_overlay.resized(
                self._rect_start,
                self._drag,
                point,
                keep_aspect=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                from_center=bool(modifiers & Qt.KeyboardModifier.AltModifier),
            )
        self.crop_overlay.set_crop(self._snap(rect))
        self.viewport().update()
        self.changed.emit()

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._drag = None

    def crop_result(self) -> tuple[bytes, QRectF] | None:
        if not self.allow_crop:
            return None
        frame = QRectF(0, 0, self.frame_w, self.frame_h)
        crop = self.crop_overlay.rect.intersected(frame)
        if crop == frame or crop.width() < 1 or crop.height() < 1:
            return None
        try:
            sub, rect = crop_image_to_rect(
                self.image, frame, self.fit, crop, tuple(self.offset)
            )
        except ImageError:
            return None
        return encode_png(sub), rect
