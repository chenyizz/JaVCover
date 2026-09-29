"""Shared selection-handle drawing for canvas items and crop overlays.

Handles are drawn as small circles at a constant *screen* size (independent of
zoom) with a dark outline so they stay readable over any content.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen

HANDLE_RADIUS_PX = 2.8


def handle_points(bounds: QRectF) -> tuple[QPointF, ...]:
    return (
        bounds.topLeft(),
        QPointF(bounds.center().x(), bounds.top()),
        bounds.topRight(),
        QPointF(bounds.right(), bounds.center().y()),
        bounds.bottomRight(),
        QPointF(bounds.center().x(), bounds.bottom()),
        bounds.bottomLeft(),
        QPointF(bounds.left(), bounds.center().y()),
    )


def draw_handles(
    painter: QPainter, bounds: QRectF, scale: float, color: QColor
) -> None:
    radius = HANDLE_RADIUS_PX / max(scale, 0.01)
    outline = QPen(QColor(0, 0, 0, 180), 1)
    outline.setCosmetic(True)
    painter.setPen(outline)
    painter.setBrush(color)
    for point in handle_points(bounds):
        painter.drawEllipse(point, radius, radius)
