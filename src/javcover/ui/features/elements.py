"""Feature mixin: ElementPanelMixin."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QWidget
from javcover.core.constants import _BLEND_MODE_LABELS
from javcover.services.image_ops import decode_png
from javcover.core.models import BLEND_MODES, DesignElement, Rect
from javcover.ui.dialogs.text_element import TextElementDialog
from javcover.ui.dialogs.image_edit import ImageEditDialog
from javcover.ui.widgets.scrub import ScrubSpinBox
from uuid import uuid4
import copy


class ElementPanelMixin:
    def _create_element_dock(self) -> None:
        self.element_dock, layout, element_splitter = self._new_inspector_card(
            "图层", "elementDock"
        )
        self.element_list = QListWidget()
        self.element_list.currentItemChanged.connect(self._element_list_changed)
        self.element_name = QLineEdit()
        self.element_name.editingFinished.connect(self._rename_element)
        layout.addWidget(QLabel("图层名称"))
        layout.addWidget(self.element_name)
        form = QFormLayout()
        self.element_fields: dict[str, QSpinBox] = {}
        for key, label in (
            ("x", "X"),
            ("y", "Y"),
            ("width", "宽"),
            ("height", "高"),
        ):
            spin = ScrubSpinBox()
            spin.setRange(0, 100_000)
            spin.setSuffix(" px")
            spin.editingFinished.connect(self._element_geometry_changed)
            self.element_fields[key] = spin
            form.addRow(label, spin)
        layout.addLayout(form)
        self.element_locked = QCheckBox("锁定图层")
        self.element_locked.toggled.connect(self._element_locked_toggled)
        layout.addWidget(self.element_locked)
        self.element_visible = QCheckBox("显示图层")
        self.element_visible.toggled.connect(self._element_visible_toggled)
        layout.addWidget(self.element_visible)
        opacity_form = QFormLayout()
        self.element_opacity = ScrubSpinBox()
        self.element_opacity.setRange(0, 100)
        self.element_opacity.setSuffix(" %")
        self.element_opacity.editingFinished.connect(self._element_opacity_changed)
        opacity_form.addRow("不透明度", self.element_opacity)
        layout.addLayout(opacity_form)
        element_blend_form = QFormLayout()
        self.element_blend = QComboBox()
        for mode in BLEND_MODES:
            self.element_blend.addItem(_BLEND_MODE_LABELS.get(mode, mode), mode)
        self.element_blend.currentIndexChanged.connect(self._element_blend_changed)
        element_blend_form.addRow("混合模式", self.element_blend)
        layout.addLayout(element_blend_form)
        region_link_form = QFormLayout()
        self.element_region = QComboBox()
        self.element_region.currentIndexChanged.connect(self._element_region_changed)
        region_link_form.addRow("关联区域", self.element_region)
        layout.addLayout(region_link_form)
        order_row = QHBoxLayout()
        self.element_up_button = QPushButton("上移一层")
        self.element_down_button = QPushButton("下移一层")
        self.element_duplicate_button = QPushButton("复制图层")
        self.element_up_button.clicked.connect(lambda: self.move_selected_element(1))
        self.element_down_button.clicked.connect(lambda: self.move_selected_element(-1))
        self.element_duplicate_button.clicked.connect(self.duplicate_selected_element)
        order_row.addWidget(self.element_up_button)
        order_row.addWidget(self.element_down_button)
        layout.addLayout(order_row)
        layout.addWidget(self.element_duplicate_button)
        edit_button = QPushButton("编辑所选文字…")
        edit_button.clicked.connect(self.edit_text_element)
        layout.addWidget(edit_button)
        self.edit_element_button = edit_button
        refresh_asset_button = QPushButton("刷新所选素材…")
        refresh_asset_button.clicked.connect(self.refresh_selected_asset)
        layout.addWidget(refresh_asset_button)
        self.refresh_asset_button = refresh_asset_button
        relink_asset_button = QPushButton("重新链接素材…")
        relink_asset_button.clicked.connect(self.relink_selected_asset)
        layout.addWidget(relink_asset_button)
        self.relink_asset_button = relink_asset_button
        remove_button = QPushButton("删除所选图层")
        remove_button.clicked.connect(self.remove_selected_element)
        layout.addWidget(remove_button)
        self.remove_element_button = remove_button
        layout.addStretch(1)
        element_splitter.addWidget(self.element_list)
        element_splitter.setSizes([300, 200])
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.element_dock)
        self._bind_panel_action(self.element_panel_action, self.element_dock)
        self.resizeDocks(
            [self.region_dock, self.guide_dock, self.element_dock],
            [320, 180, 300],
            Qt.Orientation.Vertical,
        )

    def _refresh_element_list(self) -> None:
        selected_id = self.view.selected_element_id
        scroll = self.element_list.verticalScrollBar().value()
        self.element_list.blockSignals(True)
        self.element_list.clear()
        selected_item = None
        for element in self.project.elements:
            prefix = "T" if element.kind == "text" else "▧"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, element.id)
            item.setSizeHint(QSize(160, 32))
            self.element_list.addItem(item)
            row = QWidget(self.element_list)
            row.setObjectName("regionListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(7, 1, 3, 1)
            row_layout.setSpacing(3)
            name_label = QLabel(f"{prefix}  {element.name}", row)
            name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            if not element.visible:
                name_label.setStyleSheet("color: #929ba3;")
            row_layout.addWidget(name_label, 1)
            lock_button = self._list_row_button(
                self.element_list,
                "lock-closed.svg" if element.locked else "lock-open.svg",
                "解锁图层" if element.locked else "锁定图层",
            )
            visibility_button = self._list_row_button(
                self.element_list,
                "eye-visible.svg" if element.visible else "eye-hidden.svg",
                "隐藏图层" if element.visible else "显示图层",
            )
            lock_button.clicked.connect(
                lambda _checked=False, element_id=element.id: self._toggle_element_locked(element_id)
            )
            visibility_button.clicked.connect(
                lambda _checked=False, element_id=element.id: self._toggle_element_visible(element_id)
            )
            row_layout.addWidget(lock_button)
            row_layout.addWidget(visibility_button)
            self.element_list.setItemWidget(item, row)
            if element.id == selected_id:
                selected_item = item
        if selected_item:
            self.element_list.setCurrentItem(selected_item)
        self.element_list.blockSignals(False)
        self.element_list.verticalScrollBar().setValue(scroll)
        self._update_element_controls(selected_id)

    def _toggle_element_locked(self, element_id: str) -> None:
        element = self.view._element(element_id)
        if element is None:
            return
        self._begin_edit()
        element.locked = not element.locked
        self.view.refresh_overlays()
        self._finish_edit()

    def _toggle_element_visible(self, element_id: str) -> None:
        element = self.view._element(element_id)
        if element is None:
            return
        self._begin_edit()
        element.visible = not element.visible
        self.view.refresh_overlays()
        self._finish_edit()

    def _update_element_controls(self, element_id: str | None) -> None:
        element = self.view._element(element_id)
        enabled = element is not None
        editable = enabled and element is not None and not element.locked
        self.element_name.setEnabled(editable)
        self.remove_element_button.setEnabled(editable)
        self.edit_element_button.setEnabled(
            bool(element and element.kind == "text" and not element.locked)
        )
        asset_backed = bool(element and element.kind == "image" and element.asset_name)
        self.refresh_asset_button.setEnabled(asset_backed and not (element and element.locked))
        self.relink_asset_button.setEnabled(
            bool(element and element.kind == "image" and not element.locked)
        )
        for spin in self.element_fields.values():
            spin.setEnabled(editable)
        self.element_locked.setEnabled(enabled)
        self.element_visible.setEnabled(enabled)
        self.element_opacity.setEnabled(enabled)
        self.element_blend.setEnabled(enabled)
        self.element_region.setEnabled(enabled)
        self.element_duplicate_button.setEnabled(editable)
        if element is None:
            self.element_name.clear()
            self.element_locked.blockSignals(True)
            self.element_locked.setChecked(False)
            self.element_locked.blockSignals(False)
            self.element_visible.blockSignals(True)
            self.element_visible.setChecked(True)
            self.element_visible.blockSignals(False)
            self.element_opacity.blockSignals(True)
            self.element_opacity.setValue(100)
            self.element_opacity.blockSignals(False)
            self.element_blend.blockSignals(True)
            self.element_blend.setCurrentIndex(0)
            self.element_blend.blockSignals(False)
            self.element_region.blockSignals(True)
            self.element_region.clear()
            self.element_region.addItem("（不关联区域）", None)
            self.element_region.blockSignals(False)
            for spin in self.element_fields.values():
                spin.setValue(0)
            return
        self.element_name.setText(element.name)
        self.element_locked.blockSignals(True)
        self.element_locked.setChecked(element.locked)
        self.element_locked.blockSignals(False)
        self.element_visible.blockSignals(True)
        self.element_visible.setChecked(element.visible)
        self.element_visible.blockSignals(False)
        self.element_opacity.blockSignals(True)
        self.element_opacity.setValue(element.opacity)
        self.element_opacity.blockSignals(False)
        self.element_blend.blockSignals(True)
        blend_index = self.element_blend.findData(element.blend_mode)
        self.element_blend.setCurrentIndex(blend_index if blend_index >= 0 else 0)
        self.element_blend.blockSignals(False)
        self.element_region.blockSignals(True)
        self.element_region.clear()
        self.element_region.addItem("（不关联区域）", None)
        for region in self.project.regions:
            self.element_region.addItem(region.name, region.id)
        region_index = self.element_region.findData(element.region_id)
        self.element_region.setCurrentIndex(region_index if region_index >= 0 else 0)
        self.element_region.blockSignals(False)
        values = {
            "x": element.x,
            "y": element.y,
            "width": element.width,
            "height": element.height,
        }
        for key, spin in self.element_fields.items():
            spin.setMaximum(
                self.project.width if key in ("x", "width") else self.project.height
            )
            spin.setValue(values[key])

    def _element_list_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        element_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.view.select_element(element_id)
        self._update_element_controls(element_id)

    def _select_element(self, element_id: str) -> None:
        self.region_list.blockSignals(True)
        self.region_list.setCurrentRow(-1)
        self.region_list.blockSignals(False)
        self._update_region_controls(None)
        self._update_element_controls(element_id)
        for index in range(self.element_list.count()):
            item = self.element_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == element_id:
                self.element_list.setCurrentItem(item)
                return

    def add_text_element(self) -> None:
        dialog = TextElementDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size, color, outline_color, outline_width, vertical = dialog.values()
        if not text.strip():
            self._error("文字内容为空", "请输入要放置到封面的文字。")
            return
        if not QColor(color).isValid() or not QColor(outline_color).isValid():
            self._error("颜色格式无效", "颜色请使用有效的十六进制值，例如 #ffffff。")
            return
        width = min(self.project.width, 600)
        height = min(self.project.height, 260)
        element = DesignElement(
            kind="text",
            x=(self.project.width - width) // 2,
            y=(self.project.height - height) // 2,
            width=width,
            height=height,
            name=text.strip().splitlines()[0][:24],
            text=text,
            font_family=family,
            font_size=size,
            color=color,
            outline_color=outline_color,
            outline_width=outline_width,
            vertical=vertical,
        )
        self._begin_edit()
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def edit_text_element(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.kind != "text" or element.locked:
            return
        dialog = TextElementDialog(self, element)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        text, family, size, color, outline_color, outline_width, vertical = dialog.values()
        if not text.strip() or not QColor(color).isValid() or not QColor(outline_color).isValid():
            self._error("文字设置无效", "请填写文字，并为填充色和描边色输入有效颜色。")
            return
        self._begin_edit()
        element.text = text
        element.font_family = family
        element.font_size = size
        element.color = color
        element.outline_color = outline_color
        element.outline_width = outline_width
        element.vertical = vertical
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def _on_edit_requested(self, _kind: str, _target_id: str) -> None:
        self.edit_selected_image()

    def edit_selected_image(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        region = self._selected_region()
        image = None
        frame = None
        fit = "stretch"
        offset = (0, 0)
        target: tuple[str, object] | None = None
        allow_pan, allow_crop = False, True
        if element is not None and element.kind == "image" and element.png:
            image = decode_png(element.png)
            frame = QSize(element.width, element.height)
            target = ("element", element)
        elif region is not None and region.background_png:
            image = decode_png(region.background_png)
            frame = QSize(region.rect.width, region.rect.height)
            fit = region.fit
            offset = (region.bg_dx, region.bg_dy)
            target = ("region", region)
            allow_pan = True
        if target is None or image is None or frame is None:
            self._error("无可编辑图片", "请选择带图片的图层，或有背景的区域。")
            return
        dialog = ImageEditDialog(
            self,
            image,
            frame,
            fit,
            offset,
            allow_pan=allow_pan,
            allow_crop=allow_crop,
            title="编辑图片",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        cropped = dialog.cropped()
        new_offset = dialog.offset()
        self._begin_edit()
        kind, obj = target
        if kind == "element":
            if cropped is not None:
                png, rect = cropped
                obj.png = png
                obj.rect = Rect(
                    obj.x + round(rect.x()),
                    obj.y + round(rect.y()),
                    max(1, round(rect.width())),
                    max(1, round(rect.height())),
                ).bounded(self.project.width, self.project.height)
        else:
            if cropped is not None:
                png, rect = cropped
                obj.background_png = png
                obj.rect = Rect(
                    obj.rect.x + round(rect.x()),
                    obj.rect.y + round(rect.y()),
                    max(1, round(rect.width())),
                    max(1, round(rect.height())),
                ).bounded(self.project.width, self.project.height)
                obj.bg_dx = 0
                obj.bg_dy = 0
            else:
                obj.bg_dx, obj.bg_dy = new_offset
        self.view.refresh_overlays()
        self._finish_edit()

    def _rename_element(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        name = self.element_name.text().strip()
        if element is None or element.locked or not name or name == element.name:
            return
        self._begin_edit()
        element.name = name
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_geometry_changed(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.locked:
            return
        values = {key: spin.value() for key, spin in self.element_fields.items()}
        if values["width"] < 1 or values["height"] < 1:
            return
        proposed = Rect(
            values["x"], values["y"], values["width"], values["height"]
        ).bounded(self.project.width, self.project.height)
        if proposed == element.rect:
            return
        self._begin_edit()
        element.rect = proposed
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_locked_toggled(self, checked: bool) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.locked == checked:
            return
        self._begin_edit()
        element.locked = checked
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_visible_toggled(self, checked: bool) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.visible == checked:
            return
        self._begin_edit()
        element.visible = checked
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_opacity_changed(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None:
            return
        value = self.element_opacity.value()
        if value == element.opacity:
            return
        self._begin_edit()
        element.opacity = value
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_blend_changed(self, _index: int) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None:
            return
        blend = self.element_blend.currentData()
        if not isinstance(blend, str) or blend == element.blend_mode:
            return
        self._begin_edit()
        element.blend_mode = blend
        self.view.refresh_overlays()
        self._finish_edit()

    def _element_region_changed(self, _index: int) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None:
            return
        region_id = self.element_region.currentData()
        if region_id == element.region_id:
            return
        self._begin_edit()
        element.region_id = region_id
        self.view.reclamp_linked_elements()
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def move_selected_element(self, delta: int) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.locked:
            return
        index = self.project.elements.index(element)
        target = index + delta
        if not 0 <= target < len(self.project.elements):
            return
        self._begin_edit()
        self.project.elements.insert(target, self.project.elements.pop(index))
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def duplicate_selected_element(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.locked:
            return
        clone = copy.deepcopy(element)
        clone.id = uuid4().hex
        clone.name = f"{element.name} 副本"
        clone.x = min(element.x + 20, max(0, self.project.width - element.width))
        clone.y = min(element.y + 20, max(0, self.project.height - element.height))
        self._begin_edit()
        self.project.elements.append(clone)
        self.view.refresh_overlays()
        self.view.select_element(clone.id)
        self._finish_edit()

    def remove_selected_element(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.locked:
            return
        self._begin_edit()
        self.project.elements.remove(element)
        self.view.selected_element_id = None
        self.view.refresh_overlays()
        self._finish_edit()

