"""Interactive crop overlay (Photoshop-style) for the canvas.

``CropOverlay`` draws the preview (mask/grid/handles); ``CropTool`` owns the
interaction state and talks to the view for selection/refresh. No document data
changes while the user adjusts the box.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsObject,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from javcover.core.crop import crop_image_to_rect
from javcover.core.errors import ImageError
from javcover.services.image_ops import decode_png, encode_png
from javcover.core.models import Rect

MIN_CROP = 2.0
HANDLE_HALF_PX = 4.0
HIT_TOLERANCE_PX = 9.0
_MARGIN = 14


class CropOverlay(QGraphicsObject):
    HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def __init__(
        self,
        bounds: QRectF,
        grid_size: int = 100,
        grid_subdivisions: int = 4,
    ) -> None:
        super().__init__()
        self.bounds = QRectF(bounds)
        self.rect = QRectF(bounds)
        self.grid_size = max(1, grid_size)
        self.grid_subdivisions = max(1, grid_subdivisions)
        self.setZValue(30)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    # -- geometry ---------------------------------------------------------
    def boundingRect(self) -> QRectF:  # noqa: N802 (Qt API)
        return self.bounds.adjusted(-_MARGIN, -_MARGIN, _MARGIN, _MARGIN)

    def handle_points(self) -> dict[str, QPointF]:
        rect = self.rect
        return {
            "nw": rect.topLeft(),
            "n": QPointF(rect.center().x(), rect.top()),
            "ne": rect.topRight(),
            "e": QPointF(rect.right(), rect.center().y()),
            "se": rect.bottomRight(),
            "s": QPointF(rect.center().x(), rect.bottom()),
            "sw": rect.bottomLeft(),
            "w": QPointF(rect.left(), rect.center().y()),
        }

    def handle_at(self, point: QPointF, tolerance: float) -> str | None:
        for name, handle in self.handle_points().items():
            if (
                abs(point.x() - handle.x()) <= tolerance
                and abs(point.y() - handle.y()) <= tolerance
            ):
                return name
        return None

    def contains(self, point: QPointF) -> bool:
        return self.rect.contains(point)

    def resized(
        self,
        base: QRectF,
        handle: str,
        point: QPointF,
        *,
        keep_aspect: bool = False,
        from_center: bool = False,
    ) -> QRectF:
        rect = QRectF(base)
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        if "w" in handle:
            left = min(point.x(), right - MIN_CROP)
        elif "e" in handle:
            right = max(point.x(), left + MIN_CROP)
        if "n" in handle:
            top = min(point.y(), bottom - MIN_CROP)
        elif "s" in handle:
            bottom = max(point.y(), top + MIN_CROP)
        if from_center:
            cx, cy = rect.center().x(), rect.center().y()
            if "w" in handle:
                left = min(2 * cx - right, right - MIN_CROP)
            elif "e" in handle:
                right = max(2 * cx - left, left + MIN_CROP)
            if "n" in handle:
                top = min(2 * cy - bottom, bottom - MIN_CROP)
            elif "s" in handle:
                bottom = max(2 * cy - top, top + MIN_CROP)
        if keep_aspect and handle in ("nw", "ne", "se", "sw") and rect.height() > 0:
            aspect = rect.width() / rect.height()
            width = max(MIN_CROP, right - left)
            height = max(MIN_CROP, bottom - top)
            if width / height > aspect:
                width = height * aspect
            else:
                height = width / aspect
            if "w" in handle:
                left = right - width
            else:
                right = left + width
            if "n" in handle:
                top = bottom - height
            else:
                bottom = top + height
        result = QRectF(left, top, right - left, bottom - top).normalized()
        return result.intersected(self.bounds)

    def clamped(self, rect: QRectF) -> QRectF:
        """Keep ``rect`` (same size) inside the target bounds."""
        if rect.width() > self.bounds.width() or rect.height() > self.bounds.height():
            return self.rect
        x = min(max(rect.x(), self.bounds.left()), self.bounds.right() - rect.width())
        y = min(max(rect.y(), self.bounds.top()), self.bounds.bottom() - rect.height())
        return QRectF(x, y, rect.width(), rect.height())

    def set_crop(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self.rect = rect.intersected(self.bounds)
        self.update()

    # -- painting ---------------------------------------------------------
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        crop = self.rect
        bounds = self.bounds
        scale = max(painter.worldTransform().m11(), 0.01)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # Semi-transparent mask around the crop box (inside the target bounds).
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        for region in (
            QRectF(bounds.left(), bounds.top(), bounds.width(), crop.top() - bounds.top()),
            QRectF(bounds.left(), crop.bottom(), bounds.width(), bounds.bottom() - crop.bottom()),
            QRectF(bounds.left(), crop.top(), crop.left() - bounds.left(), crop.height()),
            QRectF(crop.right(), crop.top(), bounds.right() - crop.right(), crop.height()),
        ):
            if region.width() > 0 and region.height() > 0:
                painter.drawRect(region)
        # Rule-of-thirds style grid, configurable.
        spacing = self.grid_size / self.grid_subdivisions
        if spacing > 0 and self.rect.width() > 0:
            pen = QPen(QColor(255, 255, 255, 140), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            value = spacing
            while value < crop.width():
                x = crop.left() + value
                painter.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
                value += spacing
            value = spacing
            while value < crop.height():
                y = crop.top() + value
                painter.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))
                value += spacing
        pen = QPen(QColor("#ffd400"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(crop)
        half = HANDLE_HALF_PX / scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffd400"))
        for point in self.handle_points().values():
            painter.drawRect(QRectF(point.x() - half, point.y() - half, half * 2, half * 2))
        painter.restore()


class CropTool:
    """Owns crop interaction state; delegates selection/refresh to the view."""

    def __init__(self, view: object) -> None:
        self.view = view
        self.overlay: CropOverlay | None = None
        self.target: tuple[str, str] | None = None
        self.drag: str | None = None
        self.rect_start = QRectF()
        self.drag_origin = QPointF()

    # -- target resolution ------------------------------------------------
    def bounds(self) -> QRectF | None:
        if self.target is None:
            return None
        kind, target_id = self.target
        if kind == "element":
            element = self.view._element(target_id)
            if element is None or not element.png:
                return None
            return QRectF(element.x, element.y, element.width, element.height)
        region = self.view._region(target_id)
        if region is None or not region.background_png:
            return None
        return QRectF(
            region.rect.x, region.rect.y, region.rect.width, region.rect.height
        )

    def current_target(self) -> tuple[str, str] | None:
        element = self.view._element(self.view.selected_element_id)
        if element is not None and element.kind == "image" and element.png:
            return ("element", element.id)
        region = self.view._region(self.view.selected_id)
        if region is not None and region.background_png:
            return ("region", region.id)
        return None

    def target_at(self, point: QPointF) -> tuple[str, str] | None:
        element = self.view._element_at(point)
        if element is not None and element.kind == "image" and element.png:
            return ("element", element.id)
        region = self.view._region_at(point)
        if region is not None and region.background_png:
            return ("region", region.id)
        return None

    # -- lifecycle --------------------------------------------------------
    def start_at(self, point: QPointF) -> bool:
        target = self.target_at(point) or self.current_target()
        if target is None:
            return False
        kind, target_id = target
        if kind == "element":
            self.view.select_element(target_id)
        else:
            self.view.select_region(target_id)
        self.target = target
        bounds = self.bounds()
        if bounds is None or bounds.width() < 1 or bounds.height() < 1:
            self.target = None
            return False
        self.remove_overlay()
        self.overlay = CropOverlay(
            bounds, self.view.grid_size, self.view.grid_subdivisions
        )
        self.view.cover_scene.addItem(self.overlay)
        self.drag = None
        return True

    def remove_overlay(self) -> None:
        if self.overlay is not None:
            self.view.cover_scene.removeItem(self.overlay)
            self.overlay = None
        self.drag = None

    def cancel(self) -> None:
        if self.overlay is None and self.target is None:
            return
        self.remove_overlay()
        self.target = None
        self.view.cover_scene.update()

    def apply(self) -> None:
        if self.overlay is None or self.target is None or self.view.project is None:
            return
        crop = QRectF(self.overlay.rect)
        full = QRectF(self.overlay.bounds)
        target = self.target
        self.cancel()
        if crop.width() < 1 or crop.height() < 1 or crop == full:
            return
        self.view.editStarted.emit()
        self._apply_to(target, crop)
        self.view.editFinished.emit()

    def apply_to(self, crop: QRectF) -> None:
        if self.target is None or self.view.project is None:
            return
        self._apply_to(self.target, crop)

    def _apply_to(self, target: tuple[str, str], crop: QRectF) -> None:
        kind, target_id = target
        project = self.view.project
        if project is None:
            return
        if kind == "element":
            element = self.view._element(target_id)
            if element is None or not element.png:
                return
            target_rect = QRectF(element.x, element.y, element.width, element.height)
            try:
                image, new_rect = crop_image_to_rect(
                    decode_png(element.png), target_rect, "stretch", crop
                )
            except ImageError:
                return
            element.png = encode_png(image)
            element.rect = Rect(
                round(new_rect.x()),
                round(new_rect.y()),
                max(1, round(new_rect.width())),
                max(1, round(new_rect.height())),
            ).bounded(project.width, project.height)
        else:
            region = self.view._region(target_id)
            if region is None or not region.background_png:
                return
            target_rect = QRectF(
                region.rect.x, region.rect.y, region.rect.width, region.rect.height
            )
            try:
                image, new_rect = crop_image_to_rect(
                    decode_png(region.background_png),
                    target_rect,
                    region.fit,
                    crop,
                    (region.bg_dx, region.bg_dy),
                )
            except ImageError:
                return
            region.background_png = encode_png(image)
            region.bg_dx = 0
            region.bg_dy = 0
            region.rect = Rect(
                round(new_rect.x()),
                round(new_rect.y()),
                max(1, round(new_rect.width())),
                max(1, round(new_rect.height())),
            ).bounded(project.width, project.height)
        self.view.refresh_overlays()

    # -- pointer interaction ---------------------------------------------
    def press(self, point: QPointF) -> bool:
        overlay = self.overlay
        if overlay is None:
            return self.start_at(point)
        tolerance = HIT_TOLERANCE_PX / max(self.view.transform().m11(), 0.01)
        handle = overlay.handle_at(point, tolerance)
        if handle is not None:
            self.drag = handle
            self.rect_start = QRectF(overlay.rect)
        elif overlay.contains(point):
            self.drag = "move"
            self.rect_start = QRectF(overlay.rect)
        else:
            self.drag = "new"
            self.rect_start = QRectF(point, point)
        self.drag_origin = point
        overlay.update()
        return True

    def move(self, point: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        overlay = self.overlay
        if overlay is None or self.drag is None:
            return
        if self.drag == "new":
            rect = QRectF(self.drag_origin, point).normalized()
            overlay.set_crop(rect.intersected(overlay.bounds))
        elif self.drag == "move":
            delta = point - self.drag_origin
            overlay.set_crop(overlay.clamped(self.rect_start.translated(delta)))
        else:
            overlay.set_crop(
                overlay.resized(
                    self.rect_start,
                    self.drag,
                    point,
                    keep_aspect=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                    from_center=bool(modifiers & Qt.KeyboardModifier.AltModifier),
                )
            )

    def release(self) -> None:
        self.drag = None

    def menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self.view)
        apply_action = menu.addAction("应用裁剪 (Enter)")
        cancel_action = menu.addAction("取消 (Esc)")
        chosen = menu.exec(global_pos)
        if chosen == apply_action:
            self.apply()
        elif chosen == cancel_action:
            self.cancel()
