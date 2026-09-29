"""Feature mixin: RegionPanelMixin."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QToolButton, QWidget
from javcover.core.constants import _BLEND_MODE_LABELS
from javcover.core.errors import ImageError
from javcover.services.image_ops import encode_png, load_image
from javcover.core.models import BLEND_MODES, Rect, Region
from javcover.ui.widgets.scrub import ScrubSpinBox
from uuid import uuid4
import copy


class RegionPanelMixin:
    def _create_region_dock(self) -> None:
        self._create_inspector_dock()
        self.region_dock, layout, region_splitter = self._new_inspector_card(
            "区域", "regionDock"
        )
        self.region_name = QLineEdit()
        self.region_name.editingFinished.connect(self._rename_region)
        layout.addWidget(QLabel("区域名称"))
        layout.addWidget(self.region_name)
        form = QFormLayout()
        self.position_fields: dict[str, QSpinBox] = {}
        for key, label in (
            ("x", "X"),
            ("y", "Y"),
            ("width", "宽"),
            ("height", "高"),
        ):
            spin = ScrubSpinBox()
            spin.setRange(0, 100_000)
            spin.setSuffix(" px")
            spin.editingFinished.connect(self._geometry_changed)
            self.position_fields[key] = spin
            form.addRow(label, spin)
        layout.addLayout(form)
        fit_form = QFormLayout()
        self.region_fit = QComboBox()
        self.region_fit.addItem("填充并裁剪 (cover)", "cover")
        self.region_fit.addItem("完整显示 (contain)", "contain")
        self.region_fit.addItem("拉伸填满 (stretch)", "stretch")
        self.region_fit.currentIndexChanged.connect(self._region_fit_changed)
        fit_form.addRow("背景填充", self.region_fit)
        layout.addLayout(fit_form)
        blend_form = QFormLayout()
        self.region_blend = QComboBox()
        for mode in BLEND_MODES:
            self.region_blend.addItem(_BLEND_MODE_LABELS.get(mode, mode), mode)
        self.region_blend.currentIndexChanged.connect(self._region_blend_changed)
        blend_form.addRow("混合模式", self.region_blend)
        layout.addLayout(blend_form)
        opacity_form = QFormLayout()
        self.region_opacity = ScrubSpinBox()
        self.region_opacity.setRange(0, 100)
        self.region_opacity.setSuffix(" %")
        self.region_opacity.editingFinished.connect(self._region_opacity_changed)
        opacity_form.addRow("不透明度", self.region_opacity)
        layout.addLayout(opacity_form)
        self.replace_background_button = QPushButton("替换所选区背景…")
        self.replace_background_button.clicked.connect(self.replace_region_background)
        layout.addWidget(self.replace_background_button)
        self.remove_region_button = QPushButton("删除所选区域")
        self.remove_region_button.clicked.connect(self.remove_selected_region)
        layout.addWidget(self.remove_region_button)
        self.duplicate_region_button = QPushButton("复制所选区域")
        self.duplicate_region_button.clicked.connect(self.duplicate_selected_region)
        layout.addWidget(self.duplicate_region_button)
        layout.addStretch(1)
        self.region_list = QListWidget()
        self.region_list.setObjectName("regionList")
        self.region_list.currentItemChanged.connect(self._region_list_changed)
        self.region_list.itemDoubleClicked.connect(self._rename_region_from_list)
        region_splitter.addWidget(self.region_list)
        region_splitter.setSizes([320, 200])
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.region_dock)
        self._bind_panel_action(self.region_panel_action, self.region_dock)

    def _refresh_region_list(self) -> None:
        selected = self.view.selected_id
        scroll = self.region_list.verticalScrollBar().value()
        self.region_list.blockSignals(True)
        self.region_list.clear()
        self.region_row_controls: dict[str, tuple[QToolButton, QToolButton]] = {}
        self.region_rows: dict[str, QWidget] = {}
        selected_item = None
        for region in self.project.regions:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, region.id)
            item.setSizeHint(QSize(160, 32))
            self.region_list.addItem(item)
            row = QWidget(self.region_list)
            row.setObjectName("regionListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(7, 1, 3, 1)
            row_layout.setSpacing(3)
            name_label = QLabel(region.name, row)
            name_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            if not region.visible:
                name_label.setStyleSheet("color: #929ba3;")
            row_layout.addWidget(name_label, 1)
            lock_button = self._region_row_button(
                "lock-closed.svg" if region.locked else "lock-open.svg",
                "解锁区域" if region.locked else "锁定区域",
            )
            visibility_button = self._region_row_button(
                "eye-visible.svg" if region.visible else "eye-hidden.svg",
                "隐藏区域" if region.visible else "显示区域",
            )
            lock_button.clicked.connect(
                lambda _checked=False, region_id=region.id: self._toggle_region_locked(region_id)
            )
            visibility_button.clicked.connect(
                lambda _checked=False, region_id=region.id: self._toggle_region_visible(region_id)
            )
            row_layout.addWidget(lock_button)
            row_layout.addWidget(visibility_button)
            self.region_list.setItemWidget(item, row)
            row.setProperty("active", region.id == selected)
            self.region_rows[region.id] = row
            self.region_row_controls[region.id] = (lock_button, visibility_button)
            if region.id == selected:
                selected_item = item
        if selected_item:
            self.region_list.setCurrentItem(selected_item)
        self.region_list.blockSignals(False)
        self.region_list.verticalScrollBar().setValue(scroll)
        self._update_region_controls(selected)

    def _toggle_region_locked(self, region_id: str) -> None:
        region = next(
            (region for region in self.project.regions if region.id == region_id),
            None,
        )
        if region is None:
            return
        self._begin_edit()
        region.locked = not region.locked
        self.view.refresh_overlays()
        self._finish_edit()

    def _toggle_region_visible(self, region_id: str) -> None:
        region = next(
            (region for region in self.project.regions if region.id == region_id),
            None,
        )
        if region is None:
            return
        self._begin_edit()
        region.visible = not region.visible
        self.view.refresh_overlays()
        self._finish_edit()

    def _update_region_controls(self, region_id: str | None) -> None:
        region = next((item for item in self.project.regions if item.id == region_id), None)
        enabled = region is not None
        editable = enabled and region is not None and not region.locked
        self.region_name.setEnabled(editable)
        self.replace_background_button.setEnabled(editable)
        self.remove_region_button.setEnabled(editable)
        self.duplicate_region_button.setEnabled(enabled)
        self.region_fit.setEnabled(editable)
        self.region_opacity.setEnabled(editable)
        self.region_blend.setEnabled(editable)
        for spin in self.position_fields.values():
            spin.setEnabled(editable)
        if region is None:
            self.region_name.clear()
            for spin in self.position_fields.values():
                spin.setValue(0)
            self.region_fit.blockSignals(True)
            self.region_fit.setCurrentIndex(0)
            self.region_fit.blockSignals(False)
            self.region_opacity.blockSignals(True)
            self.region_opacity.setValue(100)
            self.region_opacity.blockSignals(False)
            self.region_blend.blockSignals(True)
            self.region_blend.setCurrentIndex(0)
            self.region_blend.blockSignals(False)
            return
        self.region_name.setText(region.name)
        self.region_fit.blockSignals(True)
        fit_index = self.region_fit.findData(region.fit)
        self.region_fit.setCurrentIndex(fit_index if fit_index >= 0 else 0)
        self.region_fit.blockSignals(False)
        self.region_opacity.blockSignals(True)
        self.region_opacity.setValue(region.opacity)
        self.region_opacity.blockSignals(False)
        self.region_blend.blockSignals(True)
        blend_index = self.region_blend.findData(region.blend_mode)
        self.region_blend.setCurrentIndex(blend_index if blend_index >= 0 else 0)
        self.region_blend.blockSignals(False)
        values = {
            "x": region.rect.x,
            "y": region.rect.y,
            "width": region.rect.width,
            "height": region.rect.height,
        }
        for key, spin in self.position_fields.items():
            spin.setMaximum(self.project.width if key in ("x", "width") else self.project.height)
            spin.setValue(values[key])

    def _region_list_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        region_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.view.select_region(region_id)
        self._update_region_controls(region_id)
        self._set_active_region_row(region_id)

    def _set_active_region_row(self, region_id: str | None) -> None:
        for row_id, row in self.region_rows.items():
            row.setProperty("active", row_id == region_id)
            row.style().unpolish(row)
            row.style().polish(row)

    def _select_region(self, region_id: str) -> None:
        self.element_list.blockSignals(True)
        self.element_list.setCurrentRow(-1)
        self.element_list.blockSignals(False)
        self._update_element_controls(None)
        self._update_region_controls(region_id)
        for index in range(self.region_list.count()):
            item = self.region_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.region_list.setCurrentItem(item)
                self._set_active_region_row(region_id)
                return

    def _created_region(self, region_id: str) -> None:
        self._refresh_region_list()
        self._select_region(region_id)

    def _rename_region(self) -> None:
        region = self._selected_region()
        name = self.region_name.text().strip()
        if region is None or region.locked or not name or name == region.name:
            return
        self._begin_edit()
        region.name = name
        self.view.refresh_overlays()
        self._finish_edit()

    def _rename_region_from_list(self, item: QListWidgetItem) -> None:
        region_id = item.data(Qt.ItemDataRole.UserRole)
        region = next(
            (r for r in self.project.regions if r.id == region_id), None
        )
        if region is None or region.locked:
            return
        name, accepted = QInputDialog.getText(
            self, "重命名区域", "区域名称", text=region.name
        )
        name = name.strip()
        if not accepted or not name or name == region.name:
            return
        self._begin_edit()
        region.name = name
        self.view.refresh_overlays()
        self._finish_edit()

    def _geometry_changed(self) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        x = self.position_fields["x"].value()
        y = self.position_fields["y"].value()
        width = self.position_fields["width"].value()
        height = self.position_fields["height"].value()
        if width < 1 or height < 1:
            return
        rect = Rect(x, y, width, height).bounded(self.project.width, self.project.height)
        if rect == region.rect:
            return
        self._begin_edit()
        region.rect = rect
        self.view.reclamp_linked_elements()
        self.view.refresh_overlays()
        self._finish_edit()

    def _selected_region(self) -> Region | None:
        region_id = self.view.selected_id
        return next((region for region in self.project.regions if region.id == region_id), None)

    def _region_fit_changed(self, _index: int) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        fit = self.region_fit.currentData()
        if not isinstance(fit, str) or fit == region.fit:
            return
        self._begin_edit()
        region.fit = fit
        self.view.refresh_overlays()
        self._finish_edit()

    def _region_opacity_changed(self) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        value = self.region_opacity.value()
        if value == region.opacity:
            return
        self._begin_edit()
        region.opacity = value
        self.view.refresh_overlays()
        self._finish_edit()

    def _region_blend_changed(self, _index: int) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        blend = self.region_blend.currentData()
        if not isinstance(blend, str) or blend == region.blend_mode:
            return
        self._begin_edit()
        region.blend_mode = blend
        self.view.refresh_overlays()
        self._finish_edit()

    def replace_region_background(self) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择区域背景", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)"
        )
        if not path:
            return
        try:
            image = load_image(path)
            encoded = encode_png(image)
        except ImageError as error:
            self._error("图片读取失败", str(error))
            return
        self._begin_edit()
        region.background_png = encoded
        self.view.refresh_overlays()
        self._finish_edit()

    def remove_selected_region(self) -> None:
        region = self._selected_region()
        if region is None or region.locked:
            return
        self._begin_edit()
        self.project.regions.remove(region)
        for element in self.project.elements:
            if element.region_id == region.id:
                element.region_id = None
        self.view.selected_id = None
        self.view.refresh_overlays()
        self._finish_edit()

    def duplicate_selected_region(self) -> None:
        region = self._selected_region()
        if region is None:
            return
        clone = copy.deepcopy(region)
        clone.id = uuid4().hex
        clone.name = f"{region.name} 副本"
        offset = 12
        clone.rect = Rect(
            region.rect.x + offset,
            region.rect.y + offset,
            region.rect.width,
            region.rect.height,
        ).bounded(self.project.width, self.project.height)
        self._begin_edit()
        self.project.regions.append(clone)
        self.view.refresh_overlays()
        self.view.select_region(clone.id)
        self._finish_edit()

