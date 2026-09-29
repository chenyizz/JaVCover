"""Reusable image-in-frame editor widget (wheel zoom, pan, crop with snapping).

This replaces the old modal ``ImageEditDialog``: it is a plain widget that can
live inside a tab next to the main canvas. It reuses the crop overlay
(:class:`javcover.ui.canvas.crop.CropOverlay`) and the shared image mapping
(:func:`javcover.core.crop.image_rect_mapping`); it never touches project data.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from javcover.core.crop import image_rect_mapping
from javcover.core.errors import ImageError
from javcover.ui.canvas.crop import HIT_TOLERANCE_PX, CropOverlay

_MARGIN = 24
_MIN_ZOOM = 0.2
_MAX_ZOOM = 12.0
_SNAP_PX = 6.0


class ImageEditor(QWidget):
    changed = Signal()
    zoomChanged = Signal(float)

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
        super().__init__(parent)
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
        self.zoom = 1.0
        self.crop_overlay = CropOverlay(QRectF(0, 0, self.frame_w, self.frame_h), 0)
        self._scale = 1.0
        self._origin = QPointF()
        self._view_offset = QPointF()
        self._drag: str | None = None
        self._drag_start = QPointF()
        self._rect_start = QRectF()
        self._offset_start = (0, 0)
        self._pan_start = QPointF()
        self._pan_origin = QPointF()
        self.setMinimumSize(360, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # -- public state -----------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._drag = None
        self.update()

    def set_zoom(self, zoom: float) -> None:
        zoom = min(max(zoom, _MIN_ZOOM), _MAX_ZOOM)
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.zoom = zoom
        self._layout()
        self.update()
        self.zoomChanged.emit(zoom)

    def result_offset(self) -> tuple[int, int]:
        return (int(round(self.offset[0])), int(round(self.offset[1])))

    def crop_rect(self) -> QRectF:
        return QRectF(self.crop_overlay.rect)

    # -- geometry ---------------------------------------------------------
    def _layout(self) -> None:
        available_w = max(1, self.width() - 2 * _MARGIN)
        available_h = max(1, self.height() - 2 * _MARGIN)
        fit_scale = min(available_w / self.frame_w, available_h / self.frame_h)
        self._scale = max(fit_scale * self.zoom, 0.01)
        origin_x = (self.width() - self.frame_w * self._scale) / 2 + self._view_offset.x()
        origin_y = (self.height() - self.frame_h * self._scale) / 2 + self._view_offset.y()
        self._origin = QPointF(origin_x, origin_y)

    def _frame_rect(self) -> QRectF:
        return QRectF(
            self._origin.x(), self._origin.y(),
            self.frame_w * self._scale, self.frame_h * self._scale,
        )

    def _to_frame(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self._origin.x()) / self._scale,
            (point.y() - self._origin.y()) / self._scale,
        )

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event: object) -> None:
        self._layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#2b2f36"))
        frame = self._frame_rect()
        painter.save()
        painter.setClipRect(frame)
        painter.fillRect(frame, QColor("#ffffff"))
        painter.translate(frame.topLeft())
        painter.scale(self._scale, self._scale)
        bounds = QRectF(0, 0, self.frame_w, self.frame_h)
        drawn, source = image_rect_mapping(
            self.image, bounds, self.fit, tuple(self.offset)
        )
        painter.drawImage(drawn, self.image, source)
        if self.grid_step > 0 and self.grid_step * self._scale >= 5:
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
        if self.mode == "crop" and self.allow_crop:
            self.crop_overlay.paint(painter)
        painter.restore()
        pen = QPen(QColor("#8a94a3"), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        painter.end()

    # -- snapping ---------------------------------------------------------
    def _snap(self, rect: QRectF) -> QRectF:
        if not self.snap_enabled:
            return rect
        tolerance = _SNAP_PX / self._scale
        bounds = QRectF(0, 0, self.frame_w, self.frame_h)
        x_targets = (0.0, self.frame_w / 2, float(self.frame_w))
        y_targets = (0.0, self.frame_h / 2, float(self.frame_h))

        def best(edges: tuple[float, ...], targets: tuple[float, ...]) -> float:
            found = 0.0
            distance = tolerance + 1
            for edge in edges:
                for target in targets:
                    delta = target - edge
                    if abs(delta) <= tolerance and abs(delta) < distance:
                        distance = abs(delta)
                        found = delta
                if self.grid_step > 0:
                    target = round(edge / self.grid_step) * self.grid_step
                    delta = target - edge
                    if abs(delta) <= tolerance and abs(delta) < distance:
                        distance = abs(delta)
                        found = delta
            return found

        dx = best((rect.left(), rect.center().x(), rect.right()), x_targets)
        dy = best((rect.top(), rect.center().y(), rect.bottom()), y_targets)
        return QRectF(
            rect.x() + dx, rect.y() + dy, rect.width(), rect.height()
        ).intersected(bounds)

    # -- pointer interaction ---------------------------------------------
    def mousePressEvent(self, event: object) -> None:
        self._layout()
        button = event.button()
        position = event.position()
        if button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._drag = "pan"
            self._pan_start = position
            self._pan_origin = QPointF(self._view_offset)
            event.accept()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        frame_point = self._to_frame(position)
        if self.mode == "crop" and self.allow_crop:
            tolerance = HIT_TOLERANCE_PX / self._scale
            handle = self.crop_overlay.handle_at(frame_point, tolerance)
            if handle is not None:
                self._drag = handle
                self._rect_start = QRectF(self.crop_overlay.rect)
            elif self.crop_overlay.contains(frame_point):
                self._drag = "move"
                self._rect_start = QRectF(self.crop_overlay.rect)
            else:
                self._drag = "new"
                self._rect_start = QRectF(frame_point, frame_point)
            self._drag_start = frame_point
        elif self.allow_pan:
            self._drag = "image"
            self._drag_start = frame_point
            self._offset_start = (self.offset[0], self.offset[1])
        event.accept()

    def mouseMoveEvent(self, event: object) -> None:
        if self._drag is None:
            return
        position = event.position()
        if self._drag == "pan":
            self._view_offset = self._pan_origin + (position - self._pan_start)
            self.update()
            return
        frame_point = self._to_frame(position)
        if self._drag == "image":
            self.offset = [
                self._offset_start[0] + (frame_point.x() - self._drag_start.x()),
                self._offset_start[1] + (frame_point.y() - self._drag_start.y()),
            ]
            self.update()
            self.changed.emit()
            return
        modifiers = event.modifiers()
        if self._drag == "new":
            rect = QRectF(self._drag_start, frame_point).normalized()
        elif self._drag == "move":
            delta = frame_point - self._drag_start
            rect = self._rect_start.translated(delta)
        else:
            rect = self.crop_overlay.resized(
                self._rect_start,
                self._drag,
                frame_point,
                keep_aspect=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                from_center=bool(modifiers & Qt.KeyboardModifier.AltModifier),
            )
        self.crop_overlay.set_crop(self._snap(rect))
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._drag = None

    def wheelEvent(self, event: object) -> None:
        if event.angleDelta().y() == 0:
            return
        self._layout()
        position = event.position()
        before = self._to_frame(position)
        factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self.set_zoom(self.zoom * factor)
        after = self._frame_rect()
        widget_after = QPointF(
            after.x() + before.x() * self._scale, after.y() + before.y() * self._scale
        )
        self._view_offset += position - widget_after
        self._layout()
        self.update()
        event.accept()

    def crop_result(self) -> tuple[bytes, QRectF] | None:
        """Return cropped PNG + new frame rect when the crop is smaller."""
        if not self.allow_crop:
            return None
        frame = QRectF(0, 0, self.frame_w, self.frame_h)
        crop = self.crop_overlay.rect.intersected(frame)
        if crop == frame or crop.width() < 1 or crop.height() < 1:
            return None
        from javcover.core.crop import crop_image_to_rect
        from javcover.services.image_ops import encode_png

        try:
            sub, rect = crop_image_to_rect(
                self.image, frame, self.fit, crop, tuple(self.offset)
            )
        except ImageError:
            return None
        return encode_png(sub), rect
