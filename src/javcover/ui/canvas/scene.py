"""Cover canvas scene (grid, guides, disc/print overlays)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsScene
from javcover.core.models import Guide



class CoverScene(QGraphicsScene):
    def __init__(self) -> None:
        super().__init__()
        self.grid_visible = False
        self.grid_size = 100
        self.grid_subdivisions = 4
        self.guides: list[Guide] = []
        self.preview_guide: Guide | None = None
        self.canvas_width = 0
        self.canvas_height = 0
        self.canvas_shape = "rect"
        self.print_guides_visible = False
        self.bleed_margin = 0
        self.safe_margin = 0
        self.alignment_guides: list[tuple[str, int]] = []

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        canvas = QRectF(0, 0, self.canvas_width, self.canvas_height)
        visible = rect.intersected(canvas)
        painter.save()
        if not visible.isEmpty():
            painter.setClipRect(canvas)
            scale = max(painter.transform().m11(), 0.01)
            major_screen_spacing = self.grid_size * scale
            minor_spacing = self.grid_size / max(1, self.grid_subdivisions)
            if self.grid_visible and major_screen_spacing >= 2.5:
                draw_minor = minor_spacing * scale >= 5
                minor_pen = QPen(QColor(15, 19, 27, 110), 0)
                minor_light_pen = QPen(QColor(255, 255, 255, 90), 0)
                major_pen = QPen(QColor(15, 19, 27, 170), 0)
                major_light_pen = QPen(QColor(255, 255, 255, 200), 0)
                for pen in (minor_pen, minor_light_pen, major_pen, major_light_pen):
                    pen.setWidth(1)
                    pen.setCosmetic(True)
                if draw_minor:
                    painter.setPen(minor_pen)
                    self._draw_grid_lines(
                        painter, visible, minor_spacing, self.grid_size, False
                    )
                    painter.setPen(minor_light_pen)
                    self._draw_grid_lines(
                        painter, visible, minor_spacing, self.grid_size, False
                    )
                painter.setPen(major_pen)
                self._draw_grid_lines(
                    painter, visible, self.grid_size, self.grid_size, True
                )
                painter.setPen(major_light_pen)
                self._draw_grid_lines(
                    painter, visible, self.grid_size, self.grid_size, True
                )
            if self.canvas_shape == "disc":
                diameter = min(self.canvas_width, self.canvas_height)
                circle = QRectF(
                    (self.canvas_width - diameter) / 2,
                    (self.canvas_height - diameter) / 2,
                    diameter,
                    diameter,
                )
                outer = QPainterPath()
                outer.addRect(canvas)
                inner = QPainterPath()
                inner.addEllipse(circle)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 90))
                painter.drawPath(outer.subtracted(inner))
                pen = QPen(QColor("#c04bff"), 1)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(circle)
            if self.print_guides_visible:
                self._draw_print_guides(painter)
        painter.restore()
        # Guides span the whole exposed viewport (not just the canvas) so they
        # always reach the rulers and are never clipped by dock resizing.
        for guide in self.guides:
            self._draw_guide(painter, rect, guide, QColor("#00d9ff"))
        if self.preview_guide:
            self._draw_guide(painter, rect, self.preview_guide, QColor("#ffd54a"))
        for axis, position in self.alignment_guides:
            pen = QPen(QColor("#c04bff"), 0, Qt.PenStyle.SolidLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if axis == "x":
                painter.drawLine(QPointF(position, rect.top()), QPointF(position, rect.bottom()))
            else:
                painter.drawLine(QPointF(rect.left(), position), QPointF(rect.right(), position))

    def _draw_print_guides(self, painter: QPainter) -> None:
        canvas = QRectF(0, 0, self.canvas_width, self.canvas_height)
        trim = canvas.adjusted(
            self.bleed_margin, self.bleed_margin, -self.bleed_margin, -self.bleed_margin
        )
        safe = trim.adjusted(
            self.safe_margin, self.safe_margin, -self.safe_margin, -self.safe_margin
        )
        if trim.isValid() and not trim.isEmpty():
            pen = QPen(QColor("#00b0ff"), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(trim)
        if safe.isValid() and not safe.isEmpty():
            pen = QPen(QColor("#00c853"), 0, Qt.PenStyle.DotLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(safe)

    @staticmethod
    def _draw_guide(
        painter: QPainter, visible: QRectF, guide: Guide, color: QColor
    ) -> None:
        if guide.axis == "x":
            line = (guide.position, visible.top(), guide.position, visible.bottom())
        else:
            line = (visible.left(), guide.position, visible.right(), guide.position)
        shadow_pen = QPen(QColor(23, 33, 43, 140), 1)
        shadow_pen.setCosmetic(True)
        painter.setPen(shadow_pen)
        painter.drawLine(*line)
        painter.setPen(QPen(color, 0, Qt.PenStyle.DashLine))
        painter.drawLine(*line)

    @staticmethod
    def _draw_grid_lines(
        painter: QPainter,
        visible: QRectF,
        spacing: float,
        major_spacing: int,
        major: bool,
    ) -> None:
        left = max(0, int(visible.left() // spacing) * int(spacing))
        top = max(0, int(visible.top() // spacing) * int(spacing))
        step = max(1, int(spacing))
        for x in range(left, int(visible.right()) + step, step):
            if not major and x % major_spacing == 0:
                continue
            painter.drawLine(QPointF(x, visible.top()), QPointF(x, visible.bottom()))
        for y in range(top, int(visible.bottom()) + step, step):
            if not major and y % major_spacing == 0:
                continue
            painter.drawLine(QPointF(visible.left(), y), QPointF(visible.right(), y))
