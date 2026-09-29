"""Interactive cover view (tools, drag, crop, zoom, drop)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsView
from javcover.core.constants import IMAGE_SUFFIXES
from javcover.core.errors import ImageError
from javcover.services.image_ops import decode_png
from javcover.core.models import DesignElement, Guide, Project, Rect, Region, snap_rect
from javcover.ui.canvas.crop import CropOverlay, CropTool
from javcover.ui.canvas.guide_interaction import GUIDE_HIT_PX, GuideInteraction
from pathlib import Path
from javcover.ui.canvas.items import DesignElementItem
from javcover.ui.canvas.items import RegionItem
from javcover.ui.canvas.scene import CoverScene


class CoverView(QGraphicsView):
    regionSelected = Signal(str)
    elementSelected = Signal(str)
    editStarted = Signal()
    editFinished = Signal()
    regionCreated = Signal(str)
    pointerMoved = Signal(int, int)
    viewportChanged = Signal()
    filesDropped = Signal(list, object)
    editRequested = Signal(str, str)

    def __init__(self) -> None:
        self.cover_scene = CoverScene()
        super().__init__(self.cover_scene)
        self.project: Project | None = None
        self.image_item = None
        self.region_items: dict[str, RegionItem] = {}
        self.element_items: dict[str, DesignElementItem] = {}
        self.selected_id: str | None = None
        self.selected_element_id: str | None = None
        self.draw_mode = True
        self.crop_mode = False
        self.crop_tool = CropTool(self)
        self.guide_interaction = GuideInteraction(self)
        self._bg_origin = QPointF()
        self._bg_offsets = (0, 0)
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
        self._preview: QGraphicsRectItem | None = None
        self._pan_start = QPointF()
        self._scroll_start = (0, 0)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#e8ebee"))
        self._pasteboard_image: QImage | None = None
        self._pasteboard_opacity = 100
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

    def set_background_image(self, image: QImage | None, opacity: int = 100) -> None:
        self._pasteboard_image = image if image is not None and not image.isNull() else None
        self._pasteboard_opacity = min(max(0, opacity), 100)
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        image = self._pasteboard_image
        if image is None or image.isNull() or rect.isEmpty():
            return
        painter.save()
        if self._pasteboard_opacity < 100:
            painter.setOpacity(self._pasteboard_opacity / 100)
        scale = max(rect.width() / image.width(), rect.height() / image.height())
        source = QRectF(
            (image.width() - rect.width() / scale) / 2,
            (image.height() - rect.height() / scale) / 2,
            rect.width() / scale,
            rect.height() / scale,
        )
        painter.drawImage(rect, image, source)
        painter.restore()

    def set_project(self, project: Project, preserve_view: bool = False) -> None:
        self.cancel_crop()
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
        self.image_item = None
        self.cover_scene.canvas_width = project.width
        self.cover_scene.canvas_height = project.height
        self.cover_scene.canvas_shape = project.shape
        self.cover_scene.guides = project.guides
        if project.base_png:
            base = decode_png(project.base_png)
            if base.width() != project.width or base.height() != project.height:
                raise ImageError("模板底图尺寸与画布尺寸不一致。")
            self.image_item = self.cover_scene.addPixmap(QPixmap.fromImage(base))
            self.image_item.setZValue(-1)
        self.cover_scene.setSceneRect(0, 0, project.width, project.height)
        self.guide_interaction.preview = None
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
        self.region_items.clear()
        self.element_items.clear()
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
        self.cover_scene.canvas_shape = self.project.shape
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

    # -- guide interaction host (see GuideHost protocol) -----------------
    def guide_limit(self, axis: str) -> int:
        if self.project is None:
            return 0
        return self.project.width if axis == "x" else self.project.height

    def guide_list(self) -> list[Guide]:
        return self.project.guides if self.project is not None else []

    def guide_changed(self) -> None:
        self.cover_scene.guides = self.guide_list()
        self.cover_scene.preview_guide = self.guide_interaction.preview
        self.cover_scene.update()

    def guide_edit_begin(self) -> None:
        self.editStarted.emit()

    def guide_edit_end(self) -> None:
        self.editFinished.emit()

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

    def mouseDoubleClickEvent(self, event: object) -> None:
        if self.project is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        point = self._clamp_to_canvas(self.mapToScene(event.position().toPoint()))
        if self.crop_overlay is not None and self.crop_overlay.contains(point):
            self.apply_crop()
            event.accept()
            return
        element = self._element_at(point)
        if element is not None and element.kind == "image" and element.png:
            self.select_element(element.id)
            self.editRequested.emit("element", element.id)
            event.accept()
            return
        region = self._region_at(point)
        if region is not None and region.background_png:
            self.select_region(region.id)
            self.editRequested.emit("region", region.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _clear_drag_state(self) -> None:
        self._drag_kind = None
        self._original_rect = None
        self._resize_corner = None
        self.guide_interaction.release()
        self._shift_down = False
        self.crop_tool.release()
        self.set_alignment_guides([])

    # -- crop tool delegation --------------------------------------------
    @property
    def crop_overlay(self) -> CropOverlay | None:
        return self.crop_tool.overlay

    @property
    def _crop_target(self) -> tuple[str, str] | None:
        return self.crop_tool.target

    @_crop_target.setter
    def _crop_target(self, value: tuple[str, str] | None) -> None:
        self.crop_tool.target = value

    @property
    def _crop_drag(self) -> str | None:
        return self.crop_tool.drag

    @property
    def _crop_rect_start(self) -> QRectF:
        return self.crop_tool.rect_start

    @property
    def _crop_drag_origin(self) -> QPointF:
        return self.crop_tool.drag_origin

    def start_crop_at(self, point: QPointF) -> bool:
        return self.crop_tool.start_at(point)

    def cancel_crop(self) -> None:
        self.crop_tool.cancel()

    def apply_crop(self) -> None:
        self.crop_tool.apply()

    def _apply_crop(self, crop: QRectF) -> None:
        self.crop_tool.apply_to(crop)

    def _crop_press(self, point: QPointF) -> bool:
        return self.crop_tool.press(point)

    def _show_crop_menu(self, global_pos: QPoint) -> None:
        self.crop_tool.menu(global_pos)

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

        if self.crop_overlay is not None and self._crop_drag is not None:
            self.crop_tool.move(scene_pos, event.modifiers())
            return
        if self._drag_kind == "bgpan":
            region = self._region(self.selected_id)
            if region is not None:
                dx = self._bg_offsets[0] + round(scene_pos.x() - self._bg_origin.x())
                dy = self._bg_offsets[1] + round(scene_pos.y() - self._bg_origin.y())
                if (dx, dy) != (region.bg_dx, region.bg_dy):
                    region.bg_dx = dx
                    region.bg_dy = dy
                    self.cover_scene.update()
            return
        if self._drag_kind == "guide":
            self.guide_interaction.move(scene_pos)
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
            if (
                self.crop_overlay is not None
                and event.button() == Qt.MouseButton.RightButton
            ):
                self._show_crop_menu(event.globalPosition().toPoint())
                event.accept()
                return
            if self._drag_kind in ("draw", "crop"):
                self._cancel_drawing()
            elif self._drag_kind in ("move", "resize", "guide", "bgpan"):
                if self._drag_kind == "guide":
                    self.guide_interaction.release()
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
        if self.crop_mode:
            if self._crop_press(self._clamp_to_canvas(raw_scene_pos)):
                event.accept()
                return
        if (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and not self.draw_mode
            and not self.crop_mode
        ):
            region = self._region(self.selected_id)
            scene_pos = self._clamp_to_canvas(raw_scene_pos)
            if (
                region is not None
                and region.background_png
                and not region.content_locked
                and region.rect.x <= scene_pos.x() <= region.rect.right
                and region.rect.y <= scene_pos.y() <= region.rect.bottom
            ):
                self.editStarted.emit()
                self._drag_kind = "bgpan"
                self._bg_origin = scene_pos
                self._bg_offsets = (region.bg_dx, region.bg_dy)
                event.accept()
                return
        if self.guide_interaction.press(
            raw_scene_pos, GUIDE_HIT_PX / max(self.transform().m11(), 0.01)
        ):
            self._drag_kind = "guide"
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
        if self.crop_overlay is not None and self._crop_drag is not None:
            self.crop_tool.release()
            event.accept()
            return
        if self._drag_kind == "bgpan":
            self.editFinished.emit()
            self._clear_drag_state()
            event.accept()
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
            self.guide_interaction.release()
        self._clear_drag_state()
        event.accept()

    def keyPressEvent(self, event: object) -> None:
        if self.crop_overlay is not None:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.apply_crop()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_crop()
                event.accept()
                return
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
