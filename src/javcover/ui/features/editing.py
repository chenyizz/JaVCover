"""Feature mixin: tabbed image editor for regions / image layers.

The double-click editor is a normal tab in the central tab widget (next to the
cover canvas) instead of a modal dialog, so you can switch back and forth.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from javcover.core.models import Rect
from javcover.services.image_ops import decode_png
from javcover.ui.editor_tab import EditorTab


class EditingMixin:
    # -- tab infrastructure ----------------------------------------------
    def build_central_tabs(self, cover_widget: QWidget) -> QTabWidget:
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.addTab(cover_widget, "封面")
        self.tabs.tabBar().setTabButton(
            0, QTabBar.ButtonPosition.RightSide, None
        )
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._editor_tabs: dict[tuple[str, str], EditorTab] = {}
        return self.tabs

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None or widget is self.tabs.widget(0):
            return
        for key, tab in list(self._editor_tabs.items()):
            if tab is widget:
                self._close_editor(key)
                return

    def close_all_editor_tabs(self) -> None:
        for key in list(self._editor_tabs):
            self._close_editor(key)

    # -- open / close ----------------------------------------------------
    def _on_edit_requested(self, _kind: str, _target_id: str) -> None:
        self.edit_selected_image()

    def edit_selected_image(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is not None and element.kind == "image" and element.png:
            self._open_editor("element", element.id)
            return
        region = self._selected_region()
        if region is not None and region.background_png:
            self._open_editor("region", region.id)
            return
        self._error("无可编辑图片", "请选择带图片的图层，或有背景的区域。")

    def _open_editor(self, kind: str, target_id: str) -> None:
        key = (kind, target_id)
        existing = self._editor_tabs.get(key)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return
        if kind == "element":
            element = self.view._element(target_id)
            if element is None or element.kind != "image" or not element.png:
                return
            image = decode_png(element.png)
            frame = QSize(element.width, element.height)
            fit, offset, allow_pan = "stretch", (0, 0), False
            title = f"编辑：{element.name}"
        else:
            region = self.view._region(target_id)
            if region is None or not region.background_png:
                return
            image = decode_png(region.background_png)
            frame = QSize(region.rect.width, region.rect.height)
            fit, offset, allow_pan = region.fit, (region.bg_dx, region.bg_dy), True
            title = f"编辑：{region.name}"
        tab = EditorTab(
            image, frame, fit, offset,
            allow_pan=allow_pan, allow_crop=True, parent=self,
        )
        tab.applied.connect(lambda k=key: self._apply_editor(k))
        tab.cancelled.connect(lambda k=key: self._close_editor(k))
        self._editor_tabs[key] = tab
        self.tabs.addTab(tab, title)
        self.tabs.setCurrentWidget(tab)

    def _close_editor(self, key: tuple[str, str]) -> None:
        tab = self._editor_tabs.pop(key, None)
        if tab is None:
            return
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.removeTab(index)
        tab.deleteLater()

    # -- apply -----------------------------------------------------------
    def _apply_editor(self, key: tuple[str, str]) -> None:
        tab = self._editor_tabs.get(key)
        if tab is None:
            return
        kind, target_id = key
        cropped = tab.result()
        offset = tab.offset()
        self._begin_edit()
        if kind == "element":
            element = self.view._element(target_id)
            if element is not None and cropped is not None:
                png, rect = cropped
                element.png = png
                element.rect = Rect(
                    element.x + round(rect.x()),
                    element.y + round(rect.y()),
                    max(1, round(rect.width())),
                    max(1, round(rect.height())),
                ).bounded(self.project.width, self.project.height)
        else:
            region = self.view._region(target_id)
            if region is not None:
                if cropped is not None:
                    png, rect = cropped
                    region.background_png = png
                    region.rect = Rect(
                        region.rect.x + round(rect.x()),
                        region.rect.y + round(rect.y()),
                        max(1, round(rect.width())),
                        max(1, round(rect.height())),
                    ).bounded(self.project.width, self.project.height)
                    region.bg_dx = 0
                    region.bg_dy = 0
                else:
                    region.bg_dx, region.bg_dy = offset
        self.view.refresh_overlays()
        self._finish_edit()
        self._close_editor(key)
