"""Feature mixin: PreferencesMixin."""

from __future__ import annotations

from PySide6.QtCore import QStandardPaths, QSize, Qt
from PySide6.QtGui import QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import QCheckBox, QColorDialog, QDialog, QToolBar, QToolButton, QWidget
from javcover.ui.dialogs.preferences import PreferencesDialog
from javcover.ui.widgets.flow_layout import FlowLayout
from javcover.ui.widgets.panel import PanelDock
from javcover.ui.widgets.scrub import ScrubSpinBox
from javcover.ui.widgets.controls import _DelayedToolTip, _ToolButtonFeedback
from javcover.services.image_ops import load_image
from javcover.core.errors import ImageError
from pathlib import Path


class PreferencesMixin:
    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(
            self._preference_values(), self._shortcut_bindings, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._store_preferences(dialog)

    def _store_preferences(self, dialog: PreferencesDialog) -> None:
        for key, value in dialog.preference_values().items():
            self.settings.setValue(key, value)
        for shortcut_id, sequence in dialog.shortcut_sequences().items():
            label, action, default = self._shortcut_bindings[shortcut_id]
            action.setShortcut(sequence)
            self.settings.setValue(
                f"shortcuts/{shortcut_id}",
                sequence.toString(QKeySequence.SequenceFormat.PortableText),
            )
            self._shortcut_bindings[shortcut_id] = (label, action, default)
        self.settings.sync()
        self._apply_preferences(dialog.preference_values())

    def _preference_values(self) -> dict[str, bool | int | str]:
        return {
            "canvas/gridVisible": self.grid_checkbox.isChecked(),
            "canvas/snapping": self.snap_checkbox.isChecked(),
            "canvas/gridSnapping": self.grid_snap_checkbox.isChecked(),
            "inspector/guidesVisible": self.guides_panel_action.isChecked(),
            "canvas/gridSize": self.grid_size.value(),
            "canvas/gridSubdivisions": self.grid_subdivisions.value(),
            "canvas/wheelZoomModifier": str(
                self.settings.value("canvas/wheelZoomModifier", "none") or "none"
            ),
            "canvas/printGuidesVisible": self.print_guides_action.isChecked(),
            "canvas/bleedMargin": self._setting_int("canvas/bleedMargin", 3, 0, 100_000),
            "canvas/safeMargin": self._setting_int("canvas/safeMargin", 5, 0, 100_000),
            "canvas/defaultWidth": self._setting_int(
                "canvas/defaultWidth", 1200, 1, 100_000
            ),
            "canvas/defaultHeight": self._setting_int(
                "canvas/defaultHeight", 800, 1, 100_000
            ),
            "canvas/pasteboardColor": self.view.backgroundBrush().color().name(),
            "canvas/pasteboardImage": str(
                self.settings.value("canvas/pasteboardImage", "") or ""
            ),
            "canvas/pasteboardOpacity": self._setting_int(
                "canvas/pasteboardOpacity", 100, 0, 100
            ),
            "export/jpegQuality": self._setting_int("export/jpegQuality", 95, 1, 100),
            "recovery/directory": str(self.settings.value("recovery/directory", "") or ""),
            "export/iccProfile": str(self.settings.value("export/iccProfile", "") or ""),
            "export/cmykProfile": str(self.settings.value("export/cmykProfile", "") or ""),
        }

    def _apply_preferences(self, preferences: dict[str, bool | int | str]) -> None:
        self.grid_size.setValue(int(preferences["canvas/gridSize"]))
        self.grid_subdivisions.setValue(int(preferences["canvas/gridSubdivisions"]))
        self.snap_checkbox.setChecked(bool(preferences["canvas/snapping"]))
        self.grid_snap_checkbox.setChecked(bool(preferences["canvas/gridSnapping"]))
        self.grid_checkbox.setChecked(bool(preferences["canvas/gridVisible"]))
        self.guides_panel_action.setChecked(
            bool(preferences["inspector/guidesVisible"])
        )
        self.print_guides_action.setChecked(
            bool(preferences["canvas/printGuidesVisible"])
        )
        self.view.set_print_guides(
            bool(preferences["canvas/printGuidesVisible"]),
            int(preferences["canvas/bleedMargin"]),
            int(preferences["canvas/safeMargin"]),
        )
        self.view.wheel_zoom_modifier = str(
            preferences.get("canvas/wheelZoomModifier", "none")
        )
        color = QColor(str(preferences["canvas/pasteboardColor"]))
        if color.isValid():
            self._apply_pasteboard_color(color)
        self.load_pasteboard()
        self._update_recovery_path()

    def load_pasteboard(self) -> None:
        color = QColor(str(self.settings.value("canvas/pasteboardColor", "#e8ebee")))
        if color.isValid():
            self.view.set_background_color(color)
        opacity = self._setting_int("canvas/pasteboardOpacity", 100, 0, 100)
        path = str(self.settings.value("canvas/pasteboardImage", "") or "")
        image = None
        if path:
            try:
                image = load_image(path)
            except (ImageError, OSError):
                image = None
        self.view.set_background_image(image, opacity)

    def _update_recovery_path(self) -> None:
        custom = str(self.settings.value("recovery/directory", "") or "").strip()
        if custom:
            directory = Path(custom)
        else:
            directory = Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            directory = Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
        self._recovery_path = directory / "recovery.javcover"

    def _set_print_guides_visibility(self, enabled: bool) -> None:
        self.view.set_print_guides(
            enabled,
            self._setting_int("canvas/bleedMargin", 3, 0, 100_000),
            self._setting_int("canvas/safeMargin", 5, 0, 100_000),
        )

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("视图与吸附")
        toolbar.setObjectName("viewOptionsToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)
        self.view_options_toolbar = toolbar
        options_toggle = toolbar.toggleViewAction()
        options_toggle.setText("视图与吸附工具条")
        self.view_menu.addAction(options_toggle)
        self.snap_checkbox = QCheckBox("磁吸")
        self.snap_checkbox.setChecked(self._setting_bool("canvas/snapping", True))
        self.snap_checkbox.toggled.connect(self._set_snapping)
        self.snap_checkbox.setToolTip("吸附到画布边缘、参考线和其他区域")
        toolbar.addWidget(self.snap_checkbox)
        self.grid_checkbox = QCheckBox("显示网格")
        self.grid_checkbox.setChecked(self._setting_bool("canvas/gridVisible", True))
        self.grid_checkbox.toggled.connect(self._set_grid_visibility)
        toolbar.addWidget(self.grid_checkbox)
        self.grid_snap_checkbox = QCheckBox("吸附到网格")
        self.grid_snap_checkbox.setChecked(
            self._setting_bool("canvas/gridSnapping", False)
        )
        self.grid_snap_checkbox.setToolTip("独立于常规磁吸，将选框位置吸附到网格细分线")
        self.grid_snap_checkbox.toggled.connect(self._set_grid_snapping)
        toolbar.addWidget(self.grid_snap_checkbox)
        self.grid_size = ScrubSpinBox()
        self.grid_size.setRange(1, 1000)
        self.grid_size.setSingleStep(1)
        self.grid_size.setValue(self._setting_int("canvas/gridSize", 100, 1, 1000))
        self.grid_size.setSuffix(" px")
        self.grid_size.setToolTip("主网格间距（像素）")
        self.grid_size.setObjectName("gridSizeSpinBox")
        self.grid_size.valueChanged.connect(self._refresh_grid)
        toolbar.addWidget(self.grid_size)
        self.grid_subdivisions = ScrubSpinBox()
        self.grid_subdivisions.setRange(1, 20)
        self.grid_subdivisions.setSingleStep(1)
        self.grid_subdivisions.setValue(
            self._setting_int("canvas/gridSubdivisions", 4, 1, 20)
        )
        self.grid_subdivisions.setSuffix(" 分格")
        self.grid_subdivisions.setToolTip("每个主网格区间内的细分格数")
        self.grid_subdivisions.setObjectName("gridSubdivisionsSpinBox")
        self.grid_subdivisions.valueChanged.connect(self._refresh_grid)
        toolbar.addWidget(self.grid_subdivisions)
        self.view.snapping = self.snap_checkbox.isChecked()
        self.view.set_grid_snapping(self.grid_snap_checkbox.isChecked())
        self.view.wheel_zoom_modifier = str(
            self.settings.value("canvas/wheelZoomModifier", "none") or "none"
        )
        self._set_grid_visibility(self.grid_checkbox.isChecked())

    def _create_tool_rail(self) -> None:
        dock = PanelDock("工具", "toolRailDock", self)
        panel = QWidget(dock)
        flow = FlowLayout(panel, margin=5, hspacing=2, vspacing=2)
        dock.setWidget(panel)
        self.tool_rail = dock
        self.tool_rail_dock = dock
        self.tool_buttons: dict[str, QToolButton] = {}
        rail_toggle = dock.toggleViewAction()
        rail_toggle.setText("工具面板")
        self.view_menu.addAction(rail_toggle)

        select_action = self._tool_action(
            "选择", "click.svg", "选择并移动区域或图层", lambda: None,
            "select-tool", QKeySequence("V")
        )
        select_action.setCheckable(True)
        region_action = self._tool_action(
            "框选", "rectangle-one.svg", "拖动创建矩形区域", lambda: None,
            "region-tool", QKeySequence("R")
        )
        region_action.setCheckable(True)
        crop_action = self._tool_action(
            "裁剪", "scissors.svg", "在区域/图层内拖动裁剪图片", lambda: None,
            "crop-tool", QKeySequence("C")
        )
        crop_action.setCheckable(True)
        group = QActionGroup(self)
        group.setExclusive(True)
        for action in (select_action, region_action, crop_action):
            group.addAction(action)
        draw_enabled = self._setting_bool("canvas/drawMode", True)
        crop_enabled = self._setting_bool("canvas/cropMode", False)
        self.view.draw_mode = draw_enabled and not crop_enabled
        self.view.crop_mode = crop_enabled
        if crop_enabled:
            crop_action.setChecked(True)
        elif draw_enabled:
            region_action.setChecked(True)
        else:
            select_action.setChecked(True)
        region_action.toggled.connect(
            lambda checked: checked and self._set_canvas_tool("region")
        )
        select_action.toggled.connect(
            lambda checked: checked and self._set_canvas_tool("select")
        )
        crop_action.toggled.connect(
            lambda checked: checked and self._set_canvas_tool("crop")
        )

        other_tools = [
            (
                "色块", "color-filter.svg", "分析封面中的大色块",
                self.run_color_block_assist, "color-block", QKeySequence("Ctrl+Shift+B")
            ),
            (
                "OCR", "scan-setting.svg", "识别日文文字并生成候选框",
                self.run_ocr_assist, "run-ocr", QKeySequence("Ctrl+Shift+R")
            ),
            (
                "文字", "add-text.svg", "添加可编辑文字图层",
                self.add_text_element, "add-text-tool", QKeySequence()
            ),
            (
                "素材", "pic-one.svg", "打开本机图片素材库",
                self.open_asset_library, "asset-library-tool", QKeySequence()
            ),
        ]
        actions = [select_action, region_action, crop_action]
        for text, icon_name, tooltip, callback, shortcut_id, shortcut in other_tools:
            actions.append(
                self._tool_action(text, icon_name, tooltip, callback, shortcut_id, shortcut)
            )
        for index, action in enumerate(actions):
            button = QToolButton(panel)
            button.setObjectName("toolCard")
            button.setDefaultAction(action)
            button.setFixedSize(34, 34)
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setProperty("javcoverAnimated", True)
            button.setAccessibleName(action.text())
            _ToolButtonFeedback(button)
            _DelayedToolTip(button, str(action.data() or action.text()))
            flow.addWidget(button)
            self.tool_buttons[action.text()] = button
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._tool_actions = (select_action, region_action, crop_action)

    def _set_canvas_tool(self, tool: str) -> None:
        self.view.draw_mode = tool == "region"
        self.view.crop_mode = tool == "crop"
        if tool != "crop":
            self.view.cancel_crop()

    def _set_snapping(self, enabled: bool) -> None:
        self.view.snapping = enabled

    def _refresh_grid(self, _value: int) -> None:
        self.grid_menu_action.blockSignals(True)
        self.grid_menu_action.setChecked(self.grid_checkbox.isChecked())
        self.grid_menu_action.blockSignals(False)
        self.view.set_grid_display(
            self.grid_checkbox.isChecked(),
            self.grid_size.value(),
            self.grid_subdivisions.value(),
        )

    def _set_grid_visibility(self, enabled: bool) -> None:
        if self.grid_checkbox.isChecked() != enabled:
            self.grid_checkbox.blockSignals(True)
            self.grid_checkbox.setChecked(enabled)
            self.grid_checkbox.blockSignals(False)
        if self.grid_menu_action.isChecked() != enabled:
            self.grid_menu_action.blockSignals(True)
            self.grid_menu_action.setChecked(enabled)
            self.grid_menu_action.blockSignals(False)
        self.view.set_grid_display(
            enabled, self.grid_size.value(), self.grid_subdivisions.value()
        )

    def _set_guides_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "guide_dock"):
            self.guide_dock.setVisible(visible)

    def choose_pasteboard_color(self) -> None:
        current = self.view.backgroundBrush().color()
        color = QColorDialog.getColor(current, self, "选择画布外围背景颜色")
        if not color.isValid():
            return
        self._apply_pasteboard_color(color)

    def _apply_pasteboard_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.view.set_background_color(color)
        self.settings.setValue("canvas/pasteboardColor", color.name())
        self.settings.sync()

    def _set_grid_snapping(self, enabled: bool) -> None:
        self.view.set_grid_snapping(enabled)

