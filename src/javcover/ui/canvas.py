"""Graphics scene, items and view for the cover canvas."""
from __future__ import annotations

import copy
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

# Support both `python -m javcover.app` and editors that execute this file directly.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import (
    QEvent,
    QLibraryInfo,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QStandardPaths,
    QSize,
    Qt,
    QThread,
    QTimer,
    QTranslator,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QColorSpace,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QFontComboBox,
    QFormLayout,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QToolTip,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from javcover.assist import (
    list_tesseract_languages,
    recognize_japanese_text,
    resolve_tesseract,
    suggest_color_blocks,
)
from javcover.canvas_widgets import RulerFrame
from javcover.image_ops import (
    ImageError,
    compose_project,
    composition_mode,
    decode_png,
    encode_png,
    load_image,
    paint_region_background,
    paint_text_element,
)
from javcover.models import BLEND_MODES, DesignElement, Guide, MAX_CANVAS_PIXELS, Project, Rect, Region, snap_rect
from javcover.psd_import import (
    PsdImportError,
    import_psd,
    rasterize_psd,
)
from javcover.template_io import TemplateError, load_project, save_project


from javcover.constants import IMAGE_SUFFIXES


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
        self.print_guides_visible = False
        self.bleed_margin = 0
        self.safe_margin = 0
        self.alignment_guides: list[tuple[str, int]] = []

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        canvas = QRectF(0, 0, self.canvas_width, self.canvas_height)
        visible = rect.intersected(canvas)
        if visible.isEmpty():
            return
        painter.save()
        painter.setClipRect(canvas)
        scale = max(painter.transform().m11(), 0.01)
        major_screen_spacing = self.grid_size * scale
        minor_spacing = self.grid_size / max(1, self.grid_subdivisions)
        if self.grid_visible and major_screen_spacing >= 2.5:
            draw_minor = minor_spacing * scale >= 5
            minor_pen = QPen(QColor(15, 19, 27, 150), 0)
            minor_light_pen = QPen(QColor(255, 255, 255, 125), 0)
            major_pen = QPen(QColor(15, 19, 27, 205), 0)
            major_light_pen = QPen(QColor(255, 255, 255, 235), 0)
            for pen in (minor_pen, major_pen):
                pen.setWidth(3)
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
        for guide in self.guides:
            self._draw_guide(painter, visible, guide, QColor("#00d9ff"))
        if self.print_guides_visible:
            self._draw_print_guides(painter)
        if self.preview_guide:
            self._draw_guide(painter, visible, self.preview_guide, QColor("#ffd54a"))
        for axis, position in self.alignment_guides:
            pen = QPen(QColor("#c04bff"), 0, Qt.PenStyle.SolidLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if axis == "x":
                painter.drawLine(QPointF(position, visible.top()), QPointF(position, visible.bottom()))
            else:
                painter.drawLine(QPointF(visible.left(), position), QPointF(visible.right(), position))
        painter.restore()

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
        shadow_pen = QPen(QColor("#17212b"), 3)
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
            )

        color = QColor("#ffd400") if self.selected else QColor("#ff3b30")
        line_width = 3.0 if self.selected else 2.0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPen(QColor(0, 0, 0, 170), line_width + 2)
        halo.setCosmetic(True)
        painter.setPen(halo)
        painter.drawRect(bounds)
        border = QPen(color, line_width)
        border.setCosmetic(True)
        painter.setPen(border)
        if self.selected:
            painter.setBrush(QColor(255, 212, 0, 45))
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
            painter.setBrush(color)
            for point in (
                bounds.topLeft(),
                QPointF(bounds.center().x(), bounds.top()),
                bounds.topRight(),
                QPointF(bounds.right(), bounds.center().y()),
                bounds.bottomRight(),
                QPointF(bounds.center().x(), bounds.bottom()),
                bounds.bottomLeft(),
                QPointF(bounds.left(), bounds.center().y()),
            ):
                painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 7, 7))


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
            halo = QPen(QColor(0, 0, 0, 170), 5)
            halo.setCosmetic(True)
            painter.setPen(halo)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bounds)
            border = QPen(QColor(color), 3, Qt.PenStyle.SolidLine)
            border.setCosmetic(True)
            painter.setPen(border)
            painter.drawRect(bounds)
            if self.element.locked:
                return
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#00e0ff"))
            for point in (
                bounds.topLeft(),
                QPointF(bounds.center().x(), bounds.top()),
                bounds.topRight(),
                QPointF(bounds.right(), bounds.center().y()),
                bounds.bottomRight(),
                QPointF(bounds.center().x(), bounds.bottom()),
                bounds.bottomLeft(),
                QPointF(bounds.left(), bounds.center().y()),
            ):
                painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 7, 7))


class CoverView(QGraphicsView):
    regionSelected = Signal(str)
    elementSelected = Signal(str)
    editStarted = Signal()
    editFinished = Signal()
    regionCreated = Signal(str)
    pointerMoved = Signal(int, int)
    viewportChanged = Signal()
    filesDropped = Signal(list, object)

    def __init__(self) -> None:
        self.cover_scene = CoverScene()
        super().__init__(self.cover_scene)
        self.project: Project | None = None
        self.image_item = None
        self.region_items: dict[str, RegionItem] = {}
        self.element_items: dict[str, DesignElementItem] = {}
        self.guide_items: list[QGraphicsLineItem] = []
        self.selected_id: str | None = None
        self.selected_element_id: str | None = None
        self.draw_mode = True
        self.snapping = True
        self.grid_visible = True
        self.grid_snapping = False
        self.grid_size = 100
        self.grid_subdivisions = 4
        self.print_guides_visible = False
        self.bleed_margin = 0
        self.safe_margin = 0
        self.wheel_zoom_modifier = "none"
        self.alignment_guides: list[tuple[str, int]] = []
        self._drag_kind: str | None = None
        self._start_scene = QPointF()
        self._original_rect: Rect | None = None
        self._resize_corner: str | None = None
        self._shift_down = False
        self._dragged_guide_index: int | None = None
        self._original_guide: Guide | None = None
        self.guide_preview: Guide | None = None
        self._preview: QGraphicsRectItem | None = None
        self._pan_start = QPointF()
        self._scroll_start = (0, 0)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#e8ebee"))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_background_color(self, color: QColor) -> None:
        if color.isValid():
            self.setBackgroundBrush(color)

    def set_project(self, project: Project, preserve_view: bool = False) -> None:
        saved_transform = self.transform() if preserve_view else None
        saved_scroll = (
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
        )
        self.project = project
        self.selected_id = None
        self.selected_element_id = None
        self.cover_scene.clear()
        self.region_items.clear()
        self.element_items.clear()
        self.guide_items.clear()
        self.image_item = None
        self.cover_scene.canvas_width = project.width
        self.cover_scene.canvas_height = project.height
        self.cover_scene.guides = project.guides
        if project.base_png:
            base = decode_png(project.base_png)
            if base.width() != project.width or base.height() != project.height:
                raise ImageError("模板底图尺寸与画布尺寸不一致。")
            self.image_item = self.cover_scene.addPixmap(QPixmap.fromImage(base))
            self.image_item.setZValue(-1)
        self.cover_scene.setSceneRect(0, 0, project.width, project.height)
        self.guide_preview = None
        self.cover_scene.preview_guide = None
        self.refresh_overlays()
        if saved_transform is not None:
            self.setTransform(saved_transform)
            self.horizontalScrollBar().setValue(saved_scroll[0])
            self.verticalScrollBar().setValue(saved_scroll[1])
        else:
            self.fitInView(self.cover_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.viewportChanged.emit()

    def refresh_overlays(self) -> None:
        if self.project is None:
            return
        for item in self.region_items.values():
            self.cover_scene.removeItem(item)
        for item in self.element_items.values():
            self.cover_scene.removeItem(item)
        for item in self.guide_items:
            self.cover_scene.removeItem(item)
        self.region_items.clear()
        self.element_items.clear()
        self.guide_items.clear()
        for region in self.project.regions:
            background = decode_png(region.background_png) if region.background_png else None
            item = RegionItem(region, background)
            item.selected = region.id == self.selected_id
            self.cover_scene.addItem(item)
            self.region_items[region.id] = item
        for element in self.project.elements:
            item = DesignElementItem(
                element, selected=element.id == self.selected_element_id
            )
            self.cover_scene.addItem(item)
            self.element_items[element.id] = item
        self.cover_scene.guides = self.project.guides
        self.cover_scene.canvas_width = self.project.width
        self.cover_scene.canvas_height = self.project.height
        self.cover_scene.grid_visible = self.grid_visible
        self.cover_scene.grid_size = self.grid_size
        self.cover_scene.grid_subdivisions = self.grid_subdivisions
        self.cover_scene.print_guides_visible = self.print_guides_visible
        self.cover_scene.bleed_margin = self.bleed_margin
        self.cover_scene.safe_margin = self.safe_margin
        self.cover_scene.update()

    def select_region(self, region_id: str | None) -> None:
        self.selected_id = region_id
        self.selected_element_id = None
        for item in self.element_items.values():
            item.selected = False
            item.update()
        for key, item in self.region_items.items():
            item.selected = key == region_id
            item.update()
        if region_id:
            self.regionSelected.emit(region_id)

    def select_element(self, element_id: str | None) -> None:
        self.selected_element_id = element_id
        self.selected_id = None
        for item in self.region_items.values():
            item.selected = False
            item.update()
        for key, item in self.element_items.items():
            item.selected = key == element_id
            item.update()
        if element_id:
            self.elementSelected.emit(element_id)

    def set_grid_display(self, enabled: bool, size: int, subdivisions: int) -> None:
        self.grid_visible = enabled
        self.grid_size = max(1, size)
        self.grid_subdivisions = max(1, subdivisions)
        self.cover_scene.grid_visible = self.grid_visible
        self.cover_scene.grid_size = self.grid_size
        self.cover_scene.grid_subdivisions = self.grid_subdivisions
        self.cover_scene.update()

    def set_grid_snapping(self, enabled: bool) -> None:
        self.grid_snapping = enabled

    def set_print_guides(self, visible: bool, bleed: int, safe: int) -> None:
        self.print_guides_visible = visible
        self.bleed_margin = max(0, bleed)
        self.safe_margin = max(0, safe)
        self.cover_scene.print_guides_visible = self.print_guides_visible
        self.cover_scene.bleed_margin = self.bleed_margin
        self.cover_scene.safe_margin = self.safe_margin
        self.cover_scene.update()

    def set_guide_preview(self, axis: str, position: int | None) -> None:
        if axis not in ("x", "y"):
            self.guide_preview = None
        elif position is not None:
            guide_axis: Literal["x", "y"] = "x" if axis == "x" else "y"
            self.guide_preview = Guide(guide_axis, position)
        else:
            self.guide_preview = None
        self.cover_scene.preview_guide = self.guide_preview
        self.cover_scene.update()

    def fit_canvas(self) -> None:
        if self.project:
            self.fitInView(self.cover_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.viewportChanged.emit()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self.viewportChanged.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewportChanged.emit()

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        if 0.04 <= current * factor <= 24:
            self.scale(factor, factor)
            self.viewportChanged.emit()

    def wheelEvent(self, event: object) -> None:
        mode = self.wheel_zoom_modifier
        if mode == "disabled":
            super().wheelEvent(event)
            return
        modifiers = event.modifiers()
        required = {
            "none": Qt.KeyboardModifier.NoModifier,
            "ctrl": Qt.KeyboardModifier.ControlModifier,
            "alt": Qt.KeyboardModifier.AltModifier,
            "shift": Qt.KeyboardModifier.ShiftModifier,
        }.get(mode, Qt.KeyboardModifier.NoModifier)
        if required == Qt.KeyboardModifier.NoModifier:
            matched = modifiers == Qt.KeyboardModifier.NoModifier
        else:
            matched = bool(modifiers & required)
        if not matched:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self.zoom_by(1.15 if delta > 0 else 1 / 1.15)

    def set_alignment_guides(self, guides: list[tuple[str, int]]) -> None:
        if self.alignment_guides == guides:
            return
        self.alignment_guides = guides
        self.cover_scene.alignment_guides = guides
        self.cover_scene.update()

    def _align_rect(
        self,
        rect: Rect,
        exclude_region_id: str | None,
        exclude_element_id: str | None,
    ) -> tuple[Rect, list[tuple[str, int]]]:
        if not self.snapping or self.project is None:
            return rect, []
        threshold = max(1, round(8 / max(self.transform().m11(), 0.01)))
        x_targets = [self.project.width / 2]
        y_targets = [self.project.height / 2]
        for region in self.project.regions:
            if region.id == exclude_region_id:
                continue
            x_targets.extend((region.rect.x, region.rect.center_x, region.rect.right))
            y_targets.extend((region.rect.y, region.rect.center_y, region.rect.bottom))
        for element in self.project.elements:
            if element.id == exclude_element_id:
                continue
            x_targets.extend((element.x, element.x + element.width / 2, element.x + element.width))
            y_targets.extend((element.y, element.y + element.height / 2, element.y + element.height))

        def best(edges: tuple[int, ...], targets: list[float]) -> tuple[int, int] | None:
            found: tuple[int, int] | None = None
            for edge in edges:
                for target in targets:
                    delta = target - edge
                    if abs(delta) <= threshold and (
                        found is None or abs(delta) < abs(found[0])
                    ):
                        found = (round(delta), round(target))
            return found

        guides: list[tuple[str, int]] = []
        x_best = best((rect.x, rect.center_x, rect.right), x_targets)
        y_best = best((rect.y, rect.center_y, rect.bottom), y_targets)
        dx = dy = 0
        if x_best is not None:
            dx, gx = x_best
            guides.append(("x", gx))
        if y_best is not None:
            dy, gy = y_best
            guides.append(("y", gy))
        moved = Rect(rect.x + dx, rect.y + dy, rect.width, rect.height)
        if exclude_element_id:
            element = self._element(exclude_element_id)
            if element is not None:
                moved = self._constrain_element_rect(element, moved)
        else:
            moved = moved.bounded(self.project.width, self.project.height)
        return moved, guides

    @staticmethod
    def _dropped_paths(mime: object) -> list[str]:
        if not mime.hasUrls():
            return []
        paths: list[str] = []
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in IMAGE_SUFFIXES:
                    paths.append(path)
        return paths

    def dragEnterEvent(self, event: object) -> None:
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: object) -> None:
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: object) -> None:
        paths = self._dropped_paths(event.mimeData())
        if not paths:
            super().dropEvent(event)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        self.filesDropped.emit(paths, scene_pos)
        event.acceptProposedAction()

    def _clear_drag_state(self) -> None:
        self._drag_kind = None
        self._original_rect = None
        self._resize_corner = None
        self._dragged_guide_index = None
        self._original_guide = None
        self._shift_down = False
        self.set_alignment_guides([])

    def _cancel_drawing(self) -> None:
        if self._preview is not None:
            self.cover_scene.removeItem(self._preview)
            self._preview = None
        self._clear_drag_state()
        self.editFinished.emit()

    def mouseMoveEvent(self, event: object) -> None:
        if self.project is None:
            return
        self._shift_down = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self._drag_kind == "pan":
            delta = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(self._scroll_start[0] - delta.x())
            self.verticalScrollBar().setValue(self._scroll_start[1] - delta.y())
            return
        scene_pos = self._clamp_to_canvas(self.mapToScene(event.position().toPoint()))
        px = min(max(0, round(scene_pos.x())), self.project.width)
        py = min(max(0, round(scene_pos.y())), self.project.height)
        self.pointerMoved.emit(px, py)

        if self._drag_kind == "guide" and self._dragged_guide_index is not None:
            old = self._original_guide
            if old is not None:
                position = round(scene_pos.x() if old.axis == "x" else scene_pos.y())
                position = min(
                    max(0, position),
                    self.project.width if old.axis == "x" else self.project.height,
                )
                if self.project.guides[self._dragged_guide_index].position != position:
                    self.project.guides[self._dragged_guide_index] = Guide(old.axis, position)
                    self.cover_scene.guides = self.project.guides
                    self.cover_scene.update()
            return
        if self._drag_kind == "draw" and self._preview is not None:
            rect = QRectF(self._start_scene, scene_pos).normalized()
            self._preview.setRect(rect)
            return
        if self._drag_kind in ("move", "resize") and self._original_rect is not None:
            region = self._region(self.selected_id)
            element = self._element(self.selected_element_id)
            if region is None and element is None:
                return
            proposed = self._dragged_rect(scene_pos)
            if self.snapping or self.grid_snapping:
                proposed = self._snap_rect(proposed, region.id if region else None)
            if self._drag_kind == "move":
                proposed, guides = self._align_rect(
                    proposed,
                    region.id if region else None,
                    element.id if element else None,
                )
                self.set_alignment_guides(guides)
            else:
                self.set_alignment_guides([])
            current = region.rect if region else element.rect
            if proposed != current:
                self._set_selected_rect(proposed)
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: object) -> None:
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            if self._drag_kind == "draw":
                self._cancel_drawing()
            elif self._drag_kind in ("move", "resize", "guide"):
                self._clear_drag_state()
                self.editFinished.emit()
            self._drag_kind = "pan"
            self._pan_start = event.position().toPoint()
            self._scroll_start = (
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            event.accept()
            return
        if self.project is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        raw_scene_pos = self.mapToScene(event.position().toPoint())
        guide_index = self._guide_at(raw_scene_pos)
        if guide_index is not None:
            self.editStarted.emit()
            self._drag_kind = "guide"
            self._dragged_guide_index = guide_index
            self._original_guide = self.project.guides[guide_index]
            event.accept()
            return
        scene_pos = self._clamp_to_canvas(raw_scene_pos)
        element = self._element_at(scene_pos)
        if element is not None and (
            not self.draw_mode or element.id == self.selected_element_id
        ):
            self.select_element(element.id)
            if element.locked:
                self._clear_drag_state()
                event.accept()
                return
            self.editStarted.emit()
            self._original_rect = element.rect
            self._start_scene = scene_pos
            self._resize_corner = self._hit_handle(scene_pos, element.rect)
            self._drag_kind = "resize" if self._resize_corner else "move"
            event.accept()
            return
        region = self._region_at(scene_pos)
        if region and not self.draw_mode:
            self.select_region(region.id)
            if region.locked:
                self._clear_drag_state()
                event.accept()
                return
            self.editStarted.emit()
            self._original_rect = region.rect
            self._start_scene = scene_pos
            self._resize_corner = self._hit_handle(scene_pos, region.rect)
            self._drag_kind = "resize" if self._resize_corner else "move"
            event.accept()
            return
        if not self.draw_mode or not self._point_in_canvas(scene_pos):
            super().mousePressEvent(event)
            return
        self.editStarted.emit()
        self._start_scene = scene_pos
        self._drag_kind = "draw"
        self._preview = QGraphicsRectItem()
        self._preview.setPen(QPen(QColor("#ff5757"), 0, Qt.PenStyle.DashLine))
        self._preview.setBrush(QColor(255, 87, 87, 45))
        self._preview.setZValue(10)
        self.cover_scene.addItem(self._preview)
        event.accept()

    def mouseReleaseEvent(self, event: object) -> None:
        if (
            event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton)
            and self._drag_kind == "pan"
        ):
            self._drag_kind = None
            event.accept()
            return
        if self.project is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._drag_kind == "draw":
            end = self._clamp_to_canvas(self.mapToScene(event.position().toPoint()))
            rect = Rect.from_points(
                round(self._start_scene.x()),
                round(self._start_scene.y()),
                round(end.x()),
                round(end.y()),
            ).bounded(self.project.width, self.project.height)
            if self.snapping or self.grid_snapping:
                rect = self._snap_rect(rect)
            if self._preview:
                self.cover_scene.removeItem(self._preview)
                self._preview = None
            if rect.width >= 2 and rect.height >= 2:
                region = self.project.add_region(rect)
                self.refresh_overlays()
                self.select_region(region.id)
                self.regionCreated.emit(region.id)
            self.editFinished.emit()
        elif self._drag_kind in ("move", "resize"):
            self.editFinished.emit()
        elif self._drag_kind == "guide":
            self.editFinished.emit()
        self._clear_drag_state()
        event.accept()

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Delete and self.selected_element_id and self.project:
            selected_element = self._element(self.selected_element_id)
            if selected_element is not None and selected_element.locked:
                event.accept()
                return
            self.editStarted.emit()
            self.project.elements = [
                element
                for element in self.project.elements
                if element.id != self.selected_element_id
            ]
            self.selected_element_id = None
            self.refresh_overlays()
            self.editFinished.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.selected_id and self.project:
            selected_region = self._region(self.selected_id)
            if selected_region is not None and selected_region.locked:
                event.accept()
                return
            self.editStarted.emit()
            removed_id = self.selected_id
            self.project.regions = [
                region for region in self.project.regions if region.id != removed_id
            ]
            for element in self.project.elements:
                if element.region_id == removed_id:
                    element.region_id = None
            self.selected_id = None
            self.refresh_overlays()
            self.editFinished.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _region(self, region_id: str | None) -> Region | None:
        if self.project is None or region_id is None:
            return None
        return next((region for region in self.project.regions if region.id == region_id), None)

    def _element(self, element_id: str | None) -> DesignElement | None:
        if self.project is None or element_id is None:
            return None
        return next(
            (element for element in self.project.elements if element.id == element_id),
            None,
        )

    def _element_at(self, point: QPointF) -> DesignElement | None:
        if self.project is None:
            return None
        tolerance = 9 / max(self.transform().m11(), 0.01)
        return next(
            (
                element
                for element in reversed(self.project.elements)
                if element.visible
                and element.x - tolerance <= point.x() <= element.x + element.width + tolerance
                and element.y - tolerance <= point.y() <= element.y + element.height + tolerance
            ),
            None,
        )

    def _region_at(self, point: QPointF) -> Region | None:
        if self.project is None:
            return None
        tolerance = 9 / max(self.transform().m11(), 0.01)
        return next(
            (
                region
                for region in reversed(self.project.regions)
                if region.visible
                and region.rect.x - tolerance <= point.x() <= region.rect.right + tolerance
                and region.rect.y - tolerance <= point.y() <= region.rect.bottom + tolerance
            ),
            None,
        )

    def _hit_handle(self, point: QPointF, rect: Rect) -> str | None:
        bounds = QRectF(rect.x, rect.y, rect.width, rect.height)
        tolerance = 9 / max(self.transform().m11(), 0.01)
        handles = {
            "nw": bounds.topLeft(),
            "n": QPointF(bounds.center().x(), bounds.top()),
            "ne": bounds.topRight(),
            "e": QPointF(bounds.right(), bounds.center().y()),
            "se": bounds.bottomRight(),
            "s": QPointF(bounds.center().x(), bounds.bottom()),
            "sw": bounds.bottomLeft(),
            "w": QPointF(bounds.left(), bounds.center().y()),
        }
        for name, handle in handles.items():
            if abs(point.x() - handle.x()) <= tolerance and abs(point.y() - handle.y()) <= tolerance:
                return name
        return None

    def _dragged_rect(self, point: QPointF) -> Rect:
        if self._original_rect is None:
            return Rect(0, 0, 1, 1)
        if self._drag_kind == "resize":
            return self._resize_rect(point)
        dx = round(point.x() - self._start_scene.x())
        dy = round(point.y() - self._start_scene.y())
        return Rect(
            self._original_rect.x + dx,
            self._original_rect.y + dy,
            self._original_rect.width,
            self._original_rect.height,
        ).bounded(self.project.width, self.project.height) if self.project else self._original_rect

    def _set_selected_rect(self, rect: Rect) -> None:
        if self.project is None:
            return
        region = self._region(self.selected_id)
        if region is not None:
            if region.locked:
                return
            region.rect = rect
            item = self.region_items[region.id]
            self.reclamp_linked_elements()
        else:
            element = self._element(self.selected_element_id)
            if element is None or element.locked:
                return
            rect = self._constrain_element_rect(element, rect)
            element.rect = rect
            item = self.element_items[element.id]
        item.setPos(rect.x, rect.y)
        item.setRect(0, 0, rect.width, rect.height)
        item.update()

    def _region_for_element(self, element: DesignElement) -> Region | None:
        if self.project is None or not element.region_id:
            return None
        return next(
            (region for region in self.project.regions if region.id == element.region_id),
            None,
        )

    def _constrain_element_rect(self, element: DesignElement, rect: Rect) -> Rect:
        region = self._region_for_element(element)
        return rect if region is None else rect.bounded_within(region.rect)

    def reclamp_linked_elements(self) -> None:
        if self.project is None:
            return
        linked = {region.id for region in self.project.regions}
        for element in self.project.elements:
            if element.region_id and element.region_id not in linked:
                element.region_id = None
            constrained = self._constrain_element_rect(element, element.rect)
            if constrained != element.rect:
                element.rect = constrained
                item = self.element_items.get(element.id)
                if item is not None:
                    item.setPos(constrained.x, constrained.y)
                    item.setRect(0, 0, constrained.width, constrained.height)
                    item.update()

    def _resize_rect(self, point: QPointF) -> Rect:
        if self._original_rect is None or self._resize_corner is None:
            return self._original_rect or Rect(0, 0, 1, 1)
        original = self._original_rect
        x = round(point.x())
        y = round(point.y())
        left, top, right, bottom = original.x, original.y, original.right, original.bottom
        corner = self._resize_corner
        if "w" in corner:
            left = min(max(0, x), right - 1)
        elif "e" in corner:
            right = min(max(left + 1, x), self.project.width if self.project else x)
        if "n" in corner:
            top = min(max(0, y), bottom - 1)
        elif "s" in corner:
            bottom = min(max(top + 1, y), self.project.height if self.project else y)
        if self._shift_down and corner in ("nw", "ne", "se", "sw") and original.height > 0:
            aspect = original.width / original.height
            width = max(1, right - left)
            height = max(1, bottom - top)
            if width / height > aspect:
                width = max(1, round(height * aspect))
            else:
                height = max(1, round(width / aspect))
            if self.project:
                width = min(width, self.project.width)
                height = min(height, self.project.height)
            if "w" in corner:
                left = right - width
            else:
                right = left + width
            if "n" in corner:
                top = bottom - height
            else:
                bottom = top + height
            if self.project:
                if left < 0:
                    right -= left
                    left = 0
                if top < 0:
                    bottom -= top
                    top = 0
                if right > self.project.width:
                    left -= right - self.project.width
                    right = self.project.width
                if bottom > self.project.height:
                    top -= bottom - self.project.height
                    bottom = self.project.height
            left = max(0, left)
            top = max(0, top)
        return Rect(left, top, right - left, bottom - top)

    def _point_in_canvas(self, point: QPointF) -> bool:
        return bool(
            self.project
            and 0 <= point.x() <= self.project.width
            and 0 <= point.y() <= self.project.height
        )

    def _clamp_to_canvas(self, point: QPointF) -> QPointF:
        if self.project is None:
            return point
        return QPointF(
            min(max(0.0, point.x()), float(self.project.width)),
            min(max(0.0, point.y()), float(self.project.height)),
        )

    def _guide_at(self, point: QPointF) -> int | None:
        if self.project is None:
            return None
        tolerance = 7 / max(self.transform().m11(), 0.01)
        for index in range(len(self.project.guides) - 1, -1, -1):
            guide = self.project.guides[index]
            distance = abs(point.x() - guide.position) if guide.axis == "x" else abs(point.y() - guide.position)
            if distance <= tolerance:
                return index
        return None

    def _snap_rect(self, rect: Rect, exclude_region_id: str | None = None) -> Rect:
        if self.project is None:
            return rect
        return snap_rect(
            rect,
            self.project.width,
            self.project.height,
            self.project.guides if self.snapping else [],
            [
                region.rect
                for region in self.project.regions
                if region.id != exclude_region_id
            ]
            if self.snapping
            else [],
            max(1, round(8 / max(self.transform().m11(), 0.01))),
            max(1, self.grid_size // self.grid_subdivisions)
            if self.grid_snapping
            else 0,
        )


