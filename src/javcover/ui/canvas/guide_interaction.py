"""Shared guide interaction + drawing for the cover canvas and image editor.

Both the main :class:`~javcover.ui.canvas.view.CoverView` and the
:class:`~javcover.ui.canvas.image_editor.ImageEditor` host a
:class:`GuideInteraction`. The host only has to expose a small protocol
(guide list, axis limit, repaint, edit begin/end); the drag-out-from-ruler,
drag-to-move and live-preview behaviour lives here once.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from javcover.core.models import Guide

GUIDE_HIT_PX = 7.0
GUIDE_COLOR = QColor("#00d9ff")
GUIDE_PREVIEW_COLOR = QColor("#ffd54a")
GUIDE_ALIGN_COLOR = QColor("#c04bff")
_AXES = ("x", "y")


class GuideHost(Protocol):
    """Minimal surface a canvas/editor must provide to use the shared logic."""

    def guide_limit(self, axis: str) -> int: ...

    def guide_list(self) -> list[Guide]: ...

    def guide_changed(self) -> None: ...

    def guide_edit_begin(self) -> None: ...

    def guide_edit_end(self) -> None: ...


def _draw_guide_label(painter: QPainter, visible: QRectF, guide: Guide) -> None:
    transform = painter.worldTransform()
    if guide.axis == "x":
        anchor = transform.map(QPointF(guide.position, visible.top()))
    else:
        anchor = transform.map(QPointF(visible.left(), guide.position))
    painter.save()
    painter.resetTransform()
    metrics = painter.fontMetrics()
    text = guide.name
    width = metrics.horizontalAdvance(text) + 6
    height = metrics.height() + 2
    rect = QRectF(anchor.x() + 3, anchor.y() + 3, width, height)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 150))
    painter.drawRect(rect)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(rect.adjusted(3, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter, text)
    painter.restore()


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
    if guide.name:
        _draw_guide_label(painter, visible, guide)


def draw_guides(
    painter: QPainter,
    visible: QRectF,
    guides: list[Guide],
    *,
    preview: Guide | None = None,
    alignment: tuple[tuple[str, int], ...] | list[tuple[str, int]] = (),
) -> None:
    """Draw guides spanning ``visible`` (the full exposed view, to the rulers)."""
    for guide in guides:
        _draw_guide(painter, visible, guide, GUIDE_COLOR)
    if preview is not None:
        _draw_guide(painter, visible, preview, GUIDE_PREVIEW_COLOR)
    for axis, position in alignment:
        pen = QPen(GUIDE_ALIGN_COLOR, 0, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if axis == "x":
            painter.drawLine(
                QPointF(position, visible.top()), QPointF(position, visible.bottom())
            )
        else:
            painter.drawLine(
                QPointF(visible.left(), position), QPointF(visible.right(), position)
            )


class GuideInteraction:
    """State machine: ruler drag-out, live preview, and dragging existing guides."""

    def __init__(self, host: GuideHost) -> None:
        self.host = host
        self.preview: Guide | None = None
        self._drag_index: int | None = None
        self._original: Guide | None = None

    @property
    def dragging(self) -> bool:
        return self._drag_index is not None

    # -- queries ----------------------------------------------------------
    def guide_at(self, point: QPointF, tolerance: float) -> int | None:
        guides = self.host.guide_list()
        for index in range(len(guides) - 1, -1, -1):
            guide = guides[index]
            distance = (
                abs(point.x() - guide.position)
                if guide.axis == "x"
                else abs(point.y() - guide.position)
            )
            if distance <= tolerance:
                return index
        return None

    # -- preview ----------------------------------------------------------
    def set_preview(self, axis: str, position: int | None) -> None:
        if axis in _AXES and position is not None:
            self.preview = Guide(self._axis(axis), self._clamp(axis, position))
        else:
            self.preview = None
        self.host.guide_changed()

    def clear_preview(self) -> None:
        if self.preview is not None:
            self.preview = None
            self.host.guide_changed()

    # -- mutations --------------------------------------------------------
    def add(self, axis: str, position: int) -> None:
        if axis not in _AXES:
            return
        self.host.guide_edit_begin()
        self.host.guide_list().append(Guide(self._axis(axis), self._clamp(axis, position)))
        self.preview = None
        self.host.guide_edit_end()
        self.host.guide_changed()

    def remove(self, index: int) -> None:
        guides = self.host.guide_list()
        if not 0 <= index < len(guides):
            return
        self.host.guide_edit_begin()
        del guides[index]
        self.host.guide_edit_end()
        self.host.guide_changed()

    def rename(self, index: int, name: str) -> None:
        guides = self.host.guide_list()
        if not 0 <= index < len(guides) or guides[index].name == name:
            return
        old = guides[index]
        self.host.guide_edit_begin()
        guides[index] = Guide(old.axis, old.position, name)
        self.host.guide_edit_end()
        self.host.guide_changed()

    def move_to(self, index: int, position: int) -> None:
        guides = self.host.guide_list()
        if not 0 <= index < len(guides):
            return
        old = guides[index]
        position = self._clamp(old.axis, position)
        if old.position == position:
            return
        self.host.guide_edit_begin()
        guides[index] = Guide(old.axis, position, old.name)
        self.host.guide_edit_end()
        self.host.guide_changed()

    # -- canvas dragging --------------------------------------------------
    def press(self, point: QPointF, tolerance: float) -> bool:
        index = self.guide_at(point, tolerance)
        if index is None:
            return False
        self.host.guide_edit_begin()
        self._drag_index = index
        self._original = self.host.guide_list()[index]
        return True

    def move(self, point: QPointF) -> None:
        if self._drag_index is None or self._original is None:
            return
        guide = self._original
        raw = round(point.x() if guide.axis == "x" else point.y())
        position = self._clamp(guide.axis, raw)
        guides = self.host.guide_list()
        if guides[self._drag_index].position != position:
            guides[self._drag_index] = Guide(guide.axis, position, guide.name)
            self.host.guide_changed()

    def release(self) -> None:
        if self._drag_index is None:
            return
        self._drag_index = None
        self._original = None
        self.host.guide_edit_end()

    # -- helpers ----------------------------------------------------------
    def _clamp(self, axis: str, position: int) -> int:
        return min(max(0, int(position)), self.host.guide_limit(axis))

    @staticmethod
    def _axis(axis: str) -> str:
        return "x" if axis == "x" else "y"
