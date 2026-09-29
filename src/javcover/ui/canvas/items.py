"""Graphics items for regions and design elements."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QWidget
from javcover.services.image_ops import composition_mode, decode_png, paint_region_background, paint_text_element
from javcover.core.models import DesignElement, Region
from javcover.ui.canvas.handles import draw_handles



class RegionItem(QGraphicsRectItem):
    def __init__(self, region: Region, background: QImage | None) -> None:
        super().__init__()
        self.region_id = region.id
        self.region_name = region.name
        self.background = background
        self.locked = region.locked
        self.opacity = region.opacity
        self.fit = region.fit
        self.blend_mode = region.blend_mode
        self.bg_dx = region.bg_dx
        self.bg_dy = region.bg_dy
        self.setRect(0, 0, region.rect.width, region.rect.height)
        self.setPos(region.rect.x, region.rect.y)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(2)
        self.setVisible(region.visible)
        self.selected = False
        self._hovered = False
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, _event: object) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, _event: object) -> None:
        self._hovered = False
        self.update()

    def paint(self, painter: QPainter, option: object, widget: QWidget | None = None) -> None:
        bounds = self.rect()
        if self.background is not None:
            paint_region_background(
                painter,
                self.background,
                QRectF(0, 0, bounds.width(), bounds.height()),
                self.fit,
                self.opacity,
                self.blend_mode,
                (self.bg_dx, self.bg_dy),
            )

        color = QColor("#ffd400") if self.selected else QColor("#ff3b30")
        line_width = 1.6 if self.selected else 1.2
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPen(QColor(0, 0, 0, 150), line_width + 1.0)
        halo.setCosmetic(True)
        painter.setPen(halo)
        painter.drawRect(bounds)
        border = QPen(color, line_width)
        border.setCosmetic(True)
        painter.setPen(border)
        if self.selected:
            painter.setBrush(QColor(255, 212, 0, 40))
            painter.drawRect(bounds)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(border)
        painter.drawRect(bounds)
        label_width = min(bounds.width(), 180)
        if (
            (self.selected or self._hovered)
            and bounds.width() >= 28
            and bounds.height() >= 16
            and label_width > 12
        ):
            painter.save()
            painter.setClipRect(bounds)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QColor(15, 19, 27, 220))
            painter.drawRect(QRectF(2, 2, label_width, 18))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(6, 2, max(0, label_width - 8), 18),
                Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                self.region_name,
            )
            painter.restore()
        if self.selected and not self.locked:
            draw_handles(painter, bounds, painter.worldTransform().m11(), color)


class DesignElementItem(QGraphicsRectItem):
    def __init__(self, element: DesignElement, selected: bool = False) -> None:
        super().__init__(0, 0, element.width, element.height)
        self.element = element
        self.selected = selected
        self.image = decode_png(element.png) if element.kind == "image" and element.png else None
        self.setPos(element.x, element.y)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(4)
        self.setVisible(element.visible)

    def paint(self, painter: QPainter, option: object, widget: QWidget | None = None) -> None:
        bounds = self.rect()
        opacity = max(0, min(100, self.element.opacity)) / 100
        painter.setCompositionMode(composition_mode(self.element.blend_mode))
        if opacity < 1:
            painter.setOpacity(opacity)
        try:
            if self.image is not None:
                painter.drawImage(bounds, self.image)
            elif self.element.kind == "text":
                paint_text_element(painter, self.element, bounds)
        finally:
            if opacity < 1:
                painter.setOpacity(1.0)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.selected:
            color = "#9aa6b2" if self.element.locked else "#00e0ff"
            halo = QPen(QColor(0, 0, 0, 150), 2.4)
            halo.setCosmetic(True)
            painter.setPen(halo)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bounds)
            border = QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine)
            border.setCosmetic(True)
            painter.setPen(border)
            painter.drawRect(bounds)
            if self.element.locked:
                return
            draw_handles(
                painter, bounds, painter.worldTransform().m11(), QColor("#00e0ff")
            )
