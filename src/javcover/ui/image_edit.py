"""Focused editor for an image placed in a frame (region background or image layer).

Opened by double-clicking a region/layer. Supports panning the image inside its
frame and cropping with a resizable rectangle (dimmed outside), with an
alignment grid. Enter applies, Esc cancels.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from javcover.image_ops import crop_image_to_rect, image_rect_mapping
from javcover.ui.scrub import ScrubSpinBox

_HANDLE = 5
_MARGIN = 24


class _Preview(QWidget):
    def __init__(
        self,
        image: QImage,
        frame: QSize,
        fit: str,
        offset: tuple[int, int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.image = image
        self.frame_w = frame.width()
        self.frame_h = frame.height()
        self.fit = fit
        self.offset = list(offset)
        self.mode = "pan"
        self.grid_size = 100
        self.grid_subdivisions = 4
        self.crop = QRectF(0, 0, self.frame_w, self.frame_h)
        self._drag: str | None = None
        self._drag_start = QPointF()
        self._crop_start = QRectF()
        self._offset_start = (0, 0)
        self._scale = 1.0
        self._origin = QPointF()
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)

    # -- geometry ---------------------------------------------------------
    def _layout(self) -> None:
        available_w = max(1, self.width() - 2 * _MARGIN)
        available_h = max(1, self.height() - 2 * _MARGIN)
        self._scale = min(available_w / self.frame_w, available_h / self.frame_h)
        origin_x = (self.width() - self.frame_w * self._scale) / 2
        origin_y = (self.height() - self.frame_h * self._scale) / 2
        self._origin = QPointF(origin_x, origin_y)

    def _frame_rect(self) -> QRectF:
        return QRectF(
            self._origin.x(),
            self._origin.y(),
            self.frame_w * self._scale,
            self.frame_h * self._scale,
        )

    def _to_widget(self, rect: QRectF) -> QRectF:
        return QRectF(
            self._origin.x() + rect.x() * self._scale,
            self._origin.y() + rect.y() * self._scale,
            rect.width() * self._scale,
            rect.height() * self._scale,
        )

    def _to_frame(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self._origin.x()) / max(self._scale, 1e-6),
            (point.y() - self._origin.y()) / max(self._scale, 1e-6),
        )

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event: object) -> None:
        self._layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#2b2f36"))
        frame = self._frame_rect()
        painter.save()
        painter.setClipRect(frame)
        painter.fillRect(frame, QColor("#ffffff"))
        drawn, source = image_rect_mapping(
            self.image,
            QRectF(0, 0, self.frame_w, self.frame_h),
            self.fit,
            tuple(self.offset),
        )
        painter.drawImage(self._to_widget(drawn), self.image, source)
        painter.restore()
        if self.grid_size > 0:
            step = self.grid_size / max(1, self.grid_subdivisions)
            pen = QPen(QColor(30, 40, 55, 90), 1)
            painter.setPen(pen)
            value = step
            while value < self.frame_w:
                x = self._origin.x() + value * self._scale
                painter.drawLine(QPointF(x, frame.top()), QPointF(x, frame.bottom()))
                value += step
            value = step
            while value < self.frame_h:
                y = self._origin.y() + value * self._scale
                painter.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))
                value += step
        pen = QPen(QColor("#8a94a3"), 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        if self.mode == "crop":
            crop = self._to_widget(self.crop)
            shadow = QColor(0, 0, 0, 140)
            painter.fillRect(QRectF(frame.left(), frame.top(), frame.width(), crop.top() - frame.top()), shadow)
            painter.fillRect(QRectF(frame.left(), crop.bottom(), frame.width(), frame.bottom() - crop.bottom()), shadow)
            painter.fillRect(QRectF(frame.left(), crop.top(), crop.left() - frame.left(), crop.height()), shadow)
            painter.fillRect(QRectF(crop.right(), crop.top(), frame.right() - crop.right(), crop.height()), shadow)
            pen = QPen(QColor("#ffd400"), 1)
            painter.setPen(pen)
            painter.drawRect(crop)
            painter.setBrush(QColor("#ffd400"))
            painter.setPen(Qt.PenStyle.NoPen)
            for point in self._handle_points(crop):
                painter.drawRect(QRectF(point.x() - _HANDLE, point.y() - _HANDLE, _HANDLE * 2, _HANDLE * 2))
        painter.end()

    def _handle_points(self, crop: QRectF) -> list[QPointF]:
        return [
            crop.topLeft(),
            QPointF(crop.center().x(), crop.top()),
            crop.topRight(),
            QPointF(crop.right(), crop.center().y()),
            crop.bottomRight(),
            QPointF(crop.center().x(), crop.bottom()),
            crop.bottomLeft(),
            QPointF(crop.left(), crop.center().y()),
        ]

    # -- interaction ------------------------------------------------------
    def _handle_at(self, point: QPointF) -> str | None:
        crop = self._to_widget(self.crop)
        names = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
        for name, handle in zip(names, self._handle_points(crop)):
            if abs(point.x() - handle.x()) <= _HANDLE + 3 and abs(point.y() - handle.y()) <= _HANDLE + 3:
                return name
        return None

    def mousePressEvent(self, event: object) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self.mode == "pan":
            self._drag = "pan"
            self._drag_start = pos
            self._offset_start = tuple(self.offset)
            return
        handle = self._handle_at(pos)
        if handle is not None:
            self._drag = handle
        elif self._to_widget(self.crop).contains(pos):
            self._drag = "move"
        else:
            self._drag = "new"
            self._crop_start = QRectF(self._to_frame(pos), self._to_frame(pos))
        self._drag_start = pos
        self._crop_start = QRectF(self.crop) if self._drag != "new" else self._crop_start

    def mouseMoveEvent(self, event: object) -> None:
        if self._drag is None:
            return
        pos = event.position()
        if self._drag == "pan":
            delta = pos - self._drag_start
            self.offset = [
                int(self._offset_start[0] + delta.x() / max(self._scale, 1e-6)),
                int(self._offset_start[1] + delta.y() / max(self._scale, 1e-6)),
            ]
            self.update()
            return
        frame = QRectF(0, 0, self.frame_w, self.frame_h)
        start = self._to_frame(self._drag_start)
        current = self._to_frame(pos)
        original = self._crop_start
        if self._drag == "new":
            rect = QRectF(start, current).normalized()
        elif self._drag == "move":
            dx = current.x() - start.x()
            dy = current.y() - start.y()
            rect = QRectF(original.x() + dx, original.y() + dy, original.width(), original.height())
        else:
            left, top, right, bottom = original.x(), original.y(), original.right(), original.bottom()
            if "w" in self._drag:
                left = min(current.x(), right - 1)
            elif "e" in self._drag:
                right = max(current.x(), left + 1)
            if "n" in self._drag:
                top = min(current.y(), bottom - 1)
            elif "s" in self._drag:
                bottom = max(current.y(), top + 1)
            rect = QRectF(left, top, right - left, bottom - top)
        rect = rect.intersected(frame)
        if rect.width() >= 1 and rect.height() >= 1:
            self.crop = rect
            self.update()

    def mouseReleaseEvent(self, event: object) -> None:
        self._drag = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.update()


class ImageEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        image: QImage,
        frame: QSize,
        fit: str,
        offset: tuple[int, int],
        *,
        allow_pan: bool,
        allow_crop: bool,
        title: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._result_png: bytes | None = None
        self._result_rect: QRectF | None = None
        self.frame_w = frame.width()
        self.frame_h = frame.height()
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        if allow_pan:
            self.mode.addItem("平移图片", "pan")
        if allow_crop:
            self.mode.addItem("裁剪", "crop")
        controls.addWidget(self.mode)
        self.grid_size = ScrubSpinBox()
        self.grid_size.setRange(0, 5000)
        self.grid_size.setValue(100)
        self.grid_size.setSuffix(" px")
        self.grid_subdivisions = ScrubSpinBox()
        self.grid_subdivisions.setRange(1, 50)
        self.grid_subdivisions.setValue(4)
        self.grid_subdivisions.setSuffix(" 分格")
        controls.addWidget(QLabel("网格"))
        controls.addWidget(self.grid_size)
        controls.addWidget(QLabel("分格"))
        controls.addWidget(self.grid_subdivisions)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.preview = _Preview(image, frame, fit, offset, self)
        layout.addWidget(self.preview, 1)
        hint = QLabel("拖动调整；裁剪模式下可拖边/角改大小；Enter 应用，Esc 取消。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.mode.currentIndexChanged.connect(
            lambda _i: self.preview.set_mode(str(self.mode.currentData()))
        )
        self.grid_size.valueChanged.connect(self._grid_changed)
        self.grid_subdivisions.valueChanged.connect(self._grid_changed)
        self.preview.set_mode(str(self.mode.currentData()))

    def _grid_changed(self, _value: int) -> None:
        self.preview.grid_size = self.grid_size.value()
        self.preview.grid_subdivisions = self.grid_subdivisions.value()
        self.preview.update()

    def offset(self) -> tuple[int, int]:
        return (self.preview.offset[0], self.preview.offset[1])

    def cropped(self) -> tuple[bytes, QRectF] | None:
        if self._result_png is None or self._result_rect is None:
            return None
        return self._result_png, self._result_rect

    def accept(self) -> None:
        if self.preview.mode == "crop":
            frame = QRectF(0, 0, self.frame_w, self.frame_h)
            crop = self.preview.crop.intersected(frame)
            if 1 <= crop.width() < self.frame_w or 1 <= crop.height() < self.frame_h:
                try:
                    png, rect = crop_image_to_rect(
                        self.preview.image,
                        frame,
                        self.preview.fit,
                        crop,
                        tuple(self.preview.offset),
                    )
                except Exception:  # noqa: BLE001 - invalid crop just keeps image
                    png, rect = None, None
                if png is not None:
                    self._result_png = png
                    self._result_rect = rect
        super().accept()
