"""Main application window shell (menus, panels, window chrome).

Feature behaviour lives in :mod:`javcover.ui.features` mixins; each module
has one responsibility."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressDialog, QScrollArea, QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget
from javcover.services.canvas_widgets import RulerFrame
from javcover.core.models import MAX_CANVAS_PIXELS, Project
from javcover.core.resources import ICON_DIR
from javcover.ui.canvas.view import CoverView
from javcover.ui.widgets.panel import PanelDock
from javcover.ui.widgets.controls import _WindowControlButton
from javcover.ui.widgets.worker import _BackgroundWorker
from pathlib import Path

from javcover.ui.features.preferences import PreferencesMixin
from javcover.ui.features.project import ProjectMixin
from javcover.ui.features.exporting import ExportMixin
from javcover.ui.features.assets import AssetMixin
from javcover.ui.features.assist import AssistMixin
from javcover.ui.features.regions import RegionPanelMixin
from javcover.ui.features.guides import GuidePanelMixin
from javcover.ui.features.elements import ElementPanelMixin


class MainWindow(
    PreferencesMixin,
    ProjectMixin,
    ExportMixin,
    AssetMixin,
    AssistMixin,
    RegionPanelMixin,
    GuidePanelMixin,
    ElementPanelMixin,
    QMainWindow,
):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = (
            settings if settings is not None else QSettings("JAVCover", "JAVCover")
        )
        self._recovery_enabled = settings is None
        default_width = self._setting_int("canvas/defaultWidth", 1200, 1, 100_000)
        default_height = self._setting_int("canvas/defaultHeight", 800, 1, 100_000)
        if default_width * default_height > MAX_CANVAS_PIXELS:
            default_width, default_height = 1200, 800
        self.project = Project(default_width, default_height)
        self._shortcut_bindings: dict[
            str, tuple[str, QAction, QKeySequence]
        ] = {}
        self.current_path: Path | None = None
        self.dirty = False
        self.undo_stack: list[Project] = []
        self.redo_stack: list[Project] = []
        self._edit_before: Project | None = None
        self._background_worker: _BackgroundWorker | None = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setContentsMargins(1, 1, 1, 1)
        self.setWindowTitle("JAVCover")
        self.resize(1440, 900)
        self._base_style_sheet = (
            """
            QMainWindow { background: transparent; color: #202936; border: none; }
            QMenuBar { background: #ffffff; border: none; spacing: 3px; padding: 1px 4px; border-top-left-radius: 5px; border-top-right-radius: 5px; }
            QMenuBar::item { background: transparent; padding: 5px 7px; border-radius: 3px; }
            QMenuBar::item:selected { background: #edf3f7; }
            QToolBar { background: #ffffff; border: none; spacing: 5px; }
            QToolBar QToolButton { padding: 2px; border: 1px solid transparent; border-radius: 5px; }
            QToolBar QToolButton:hover { background: #f1f3f5; border-color: #d4d9de; }
            QToolBar#canvasToolRail { border-right: 1px solid #dfe4e9; }
            QToolBar#canvasToolRail QToolButton {
                background: transparent; border: 1px solid transparent; padding: 2px;
            }
            QToolBar#canvasToolRail QToolButton:hover {
                background: #eef4ff; border: 1px solid #b9d0ff; border-radius: 5px;
            }
            QToolBar#canvasToolRail QToolButton:checked {
                background: #d8e6ff; border: 2px solid #2f6df6; border-radius: 5px;
            }
            QToolBar#canvasToolRail QToolButton:checked:hover {
                background: #c6dbff; border: 2px solid #1d4ed8; border-radius: 5px;
            }
            QDockWidget::title { background: #e7ebee; padding: 4px 8px; border-bottom: 1px solid #d7dde2; }
            #panelTitleBar { background: #eef1f4; border-bottom: 1px solid #dbe0e4; }
            #panelTitleLabel { color: #526171; font-weight: 600; }
            QToolButton#toolCard { padding: 0px; border: 1px solid transparent; border-radius: 4px; }
            QFrame#inspectorCard { background: #ffffff; border: 1px solid #e1e5e9; border-radius: 6px; }
            QLabel#inspectorCardTitle { color: #526171; font-weight: 600; }
            QScrollArea#inspectorScrollArea { border: none; background: transparent; }
            QListWidget, QLineEdit, QSpinBox { border: 1px solid #e1e5e9; border-radius: 4px; background: #ffffff; }
            QSpinBox { padding-right: 18px; }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border; subcontrol-position: right; width: 17px;
                border-left: 1px solid #e1e5e9; background: #f8f9fa;
            }
            QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 4px; }
            QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 4px; }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #eceff1; }
            QPushButton { border: 1px solid #d9dee3; border-radius: 5px; padding: 5px 9px; background: #ffffff; }
            QPushButton:hover { background: #f3f5f6; border-color: #bfc7ce; }
            QSplitter::handle { background: #e2e6ea; }
            QSplitter::handle:hover { background: #d3d9df; }
            QSplitter::handle:vertical { height: 7px; }
            QSplitter::handle:horizontal { width: 7px; }
            QToolButton#windowControl { background: transparent; border: none; border-radius: 5px; }
            QToolButton#windowControl:hover { background: #edf0f2; }
            QToolButton#windowClose { background: transparent; border: none; border-radius: 5px; }
            QToolButton#windowClose:hover { background: #d94c4c; }
            QWidget#regionListRow[active="true"] { background: #edf3f7; }
            QToolButton#regionRowAction { background: transparent; border: none; border-radius: 4px; padding: 2px; }
            QToolButton#regionRowAction:hover { background: #edf0f2; }
            QStatusBar { background: #ffffff; border: none; border-top: 1px solid #dce1e5; padding: 3px 6px; border-bottom-left-radius: 5px; border-bottom-right-radius: 5px; }
            QStatusBar::item { border: none; }
            QStatusBar QLabel { padding: 4px 2px; }
            """
        )
        self.setStyleSheet(self._base_style_sheet)

        self.view = CoverView()
        pasteboard = QColor(
            str(self.settings.value("canvas/pasteboardColor", "#e8ebee"))
        )
        if not pasteboard.isValid():
            pasteboard = QColor("#e8ebee")
        self.view.set_background_color(pasteboard)
        self.view.set_project(self.project)
        self.view.regionSelected.connect(self._select_region)
        self.view.elementSelected.connect(self._select_element)
        self.view.regionCreated.connect(self._created_region)
        self.view.editStarted.connect(self._begin_edit)
        self.view.editFinished.connect(self._finish_edit)
        self.view.pointerMoved.connect(self._show_pointer)
        self.view.filesDropped.connect(self._on_files_dropped)
        self.view.editRequested.connect(self._on_edit_requested)
        self.ruler_frame = RulerFrame(self.view)
        self.ruler_frame.guideRequested.connect(self.add_guide_at)
        self.ruler_frame.guidePreviewChanged.connect(self.view.set_guide_preview)

        self.status = QLabel(
            f"新建画布 {self.project.width} × {self.project.height} px"
        )
        self.status.setMinimumWidth(320)
        self.status.setMinimumHeight(26)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.statusBar().addWidget(self.status, 1)
        self._create_actions()
        self._create_toolbar()
        self._create_tool_rail()
        self.setWindowIcon(
            QIcon(str(ICON_DIR / "app-icon.svg"))
        )
        self._create_region_dock()
        self._create_guide_dock()
        self._create_element_dock()
        self._create_asset_store()
        self.setCentralWidget(self.ruler_frame)
        self._create_menu_bar_controls()
        self._update_rounded_window_shape()
        self.statusBar().setSizeGripEnabled(True)
        self._restore_user_interface_state()
        self._update_title()
        self._update_region_controls(None)
        self._refresh_element_list()

    def _create_actions(self) -> None:
        self.menuBar().setNativeMenuBar(False)
        self.file_menu = self.menuBar().addMenu("文件")
        self._action(
            self.file_menu, "新建画布", self.new_project,
            QKeySequence.StandardKey.New, "new-project"
        )
        self._action(
            self.file_menu, "打开图片…", self.open_image, QKeySequence("Ctrl+O"),
            "open-image"
        )
        self._action(
            self.file_menu, "打开 PSD…", self.open_psd, QKeySequence("Ctrl+Alt+O"),
            "open-psd"
        )
        self._action(
            self.file_menu, "打开模板…", self.open_template, QKeySequence("Ctrl+Shift+O"),
            "open-template"
        )
        self._action(
            self.file_menu, "保存模板", self.save_template,
            QKeySequence.StandardKey.Save, "save-template"
        )
        self._action(
            self.file_menu, "模板另存为…", self.save_template_as,
            QKeySequence("Ctrl+Shift+S"), "save-template-as"
        )
        self.file_menu.addSeparator()
        self._action(
            self.file_menu, "导出 PNG/JPEG…", self.export_image,
            QKeySequence("Ctrl+E"), "export-image"
        )
        self._action(
            self.file_menu, "导出 CMYK (TIFF/JPEG)…", self.export_cmyk,
            shortcut_id="export-cmyk"
        )
        self._action(
            self.file_menu, "批量生成封面…", self.batch_export,
            QKeySequence("Ctrl+Shift+E"), "batch-export"
        )
        self._action(
            self.file_menu, "退出", self.close,
            QKeySequence.StandardKey.Quit, "quit"
        )

        self.edit_menu = self.menuBar().addMenu("编辑")
        self.undo_action = self._action(
            self.edit_menu, "撤销", self.undo, QKeySequence.StandardKey.Undo, "undo"
        )
        self.redo_action = self._action(
            self.edit_menu, "重做", self.redo, QKeySequence.StandardKey.Redo, "redo"
        )
        self.layer_menu = self.menuBar().addMenu("图层")
        self._action(
            self.layer_menu, "添加文字图层…", self.add_text_element,
            QKeySequence("Ctrl+Shift+T"), "add-text"
        )
        self._action(
            self.layer_menu, "编辑所选图片/背景…", self.edit_selected_image,
            QKeySequence("E"), "edit-element"
        )
        self._action(
            self.layer_menu, "放置 PSD 标题素材…", self.place_psd_title_asset,
            QKeySequence("Ctrl+Alt+I"), "place-psd-title"
        )
        self._action(
            self.layer_menu, "刷新所选素材…", self.refresh_selected_asset,
            shortcut_id="refresh-asset"
        )
        self._action(
            self.layer_menu, "重新链接素材…", self.relink_selected_asset,
            shortcut_id="relink-asset"
        )
        self._action(
            self.layer_menu, "打开本机素材库…", self.open_asset_library,
            QKeySequence("Ctrl+Shift+A"), "open-assets"
        )
        self._action(
            self.layer_menu, "删除所选图层", self.remove_selected_element,
            shortcut_id="delete-layer"
        )
        self.view_menu = self.menuBar().addMenu("视图")
        self._action(
            self.view_menu, "适合窗口", self.view.fit_canvas,
            QKeySequence("Ctrl+0"), "fit-canvas"
        )
        self._action(
            self.view_menu, "放大", lambda: self.view.zoom_by(1.15),
            QKeySequence("Ctrl+="), "zoom-in"
        )
        self._action(
            self.view_menu, "缩小", lambda: self.view.zoom_by(1 / 1.15),
            QKeySequence("Ctrl+-"), "zoom-out"
        )
        self._action(
            self.view_menu, "切换全屏", self._toggle_fullscreen,
            QKeySequence("F11"), "toggle-fullscreen"
        )
        self.grid_menu_action = QAction("显示像素网格", self)
        self.grid_menu_action.setCheckable(True)
        self.grid_menu_action.setChecked(
            self._setting_bool("canvas/gridVisible", True)
        )
        self.grid_menu_action.toggled.connect(self._set_grid_visibility)
        self.view_menu.addAction(self.grid_menu_action)
        self._register_shortcut(
            self.grid_menu_action, "toggle-grid", QKeySequence("Ctrl+G")
        )
        self.print_guides_action = QAction("显示印刷参考线", self)
        self.print_guides_action.setCheckable(True)
        self.print_guides_action.setChecked(
            self._setting_bool("canvas/printGuidesVisible", False)
        )
        self.print_guides_action.toggled.connect(self._set_print_guides_visibility)
        self.view_menu.addAction(self.print_guides_action)
        self._register_shortcut(
            self.print_guides_action, "toggle-print-guides", QKeySequence()
        )
        self.view_menu.addSeparator()
        self._action(
            self.view_menu, "添加垂直参考线…", lambda: self.add_guide("x"),
            QKeySequence("Ctrl+Alt+G"), "add-vertical-guide"
        )
        self._action(
            self.view_menu, "添加水平参考线…", lambda: self.add_guide("y"),
            QKeySequence("Ctrl+Shift+G"), "add-horizontal-guide"
        )
        self.region_panel_action = QAction("显示区域面板", self)
        self.region_panel_action.setCheckable(True)
        self.region_panel_action.setChecked(True)
        self.view_menu.addAction(self.region_panel_action)
        self._register_shortcut(
            self.region_panel_action, "toggle-region-panel", QKeySequence()
        )
        self.element_panel_action = QAction("显示图层面板", self)
        self.element_panel_action.setCheckable(True)
        self.element_panel_action.setChecked(True)
        self.view_menu.addAction(self.element_panel_action)
        self._register_shortcut(
            self.element_panel_action, "toggle-element-panel", QKeySequence()
        )
        self.guides_panel_action = QAction("显示参考线面板", self)
        self.guides_panel_action.setCheckable(True)
        self.guides_panel_action.setChecked(
            self._setting_bool("inspector/guidesVisible", True)
        )
        self.guides_panel_action.toggled.connect(self._set_guides_panel_visible)
        self.view_menu.addAction(self.guides_panel_action)
        self._register_shortcut(
            self.guides_panel_action, "toggle-guides-panel", QKeySequence()
        )
        self._action(
            self.view_menu, "画布背景颜色…", self.choose_pasteboard_color,
            shortcut_id="choose-pasteboard-color"
        )
        self.tools_menu = self.menuBar().addMenu("工具")
        self._action(
            self.tools_menu, "OCR 设置…", self.configure_ocr,
            shortcut_id="ocr-settings"
        )
        self.settings_menu = self.menuBar().addMenu("设置")
        self._action(
            self.settings_menu, "偏好设置…", self._show_preferences,
            QKeySequence("Ctrl+,"), "preferences"
        )
        self._update_history_actions()

    def _create_menu_bar_controls(self) -> None:
        bar = self.menuBar()
        app_mark = QLabel("JC")
        app_mark.setObjectName("appMark")
        app_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QIcon(str(ICON_DIR / "app-icon.svg"))
        app_mark.setPixmap(icon.pixmap(QSize(22, 22)))
        app_mark.setFixedSize(30, 28)
        app_mark.setAccessibleName("JAVCover")
        bar.setCornerWidget(app_mark, Qt.Corner.TopLeftCorner)
        self.app_mark = app_mark

        controls = QWidget()
        controls.setObjectName("windowControls")
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)
        self.minimize_button = self._window_button(
            "minimize", "最小化窗口", self.showMinimized
        )
        self.maximize_button = self._window_button(
            "maximize", "最大化窗口", self._toggle_maximized
        )
        self.fullscreen_button = self._window_button(
            "fullscreen", "切换全屏", self._toggle_fullscreen
        )
        close_button = self._window_button("close", "关闭窗口", self.close)
        close_button.setObjectName("windowClose")
        self.close_button = close_button
        for button in (
            self.minimize_button,
            self.maximize_button,
            self.fullscreen_button,
            close_button,
        ):
            layout.addWidget(button)
        bar.setCornerWidget(controls, Qt.Corner.TopRightCorner)
        self.window_controls = controls
        bar.installEventFilter(self)

    def _window_button(
        self, control: str, accessible_name: str, callback: object
    ) -> _WindowControlButton:
        button = _WindowControlButton(control, accessible_name, self)
        button.clicked.connect(callback)
        return button

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._title_drag_offset = None
            self.fullscreen_button.set_fullscreen(False)
            if getattr(self, "_fullscreen_restore_maximized", False):
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._title_drag_offset = None
            self._fullscreen_restore_maximized = self.isMaximized()
            self.fullscreen_button.set_fullscreen(True)
            self.showFullScreen()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.menuBar():
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self.menuBar().actionAt(event.position().toPoint()) is None
                    and not self.isFullScreen()
                ):
                    self._toggle_maximized()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self.menuBar().actionAt(event.position().toPoint()) is None
                ):
                    if self.isFullScreen():
                        self._title_drag_offset = None
                        return super().eventFilter(watched, event)
                    handle = self.windowHandle()
                    if handle is not None and handle.startSystemMove():
                        return True
                    if not self.isMaximized() and not self.isFullScreen():
                        self._title_drag_offset = (
                            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                        )
            if event.type() == QEvent.Type.MouseMove:
                offset = getattr(self, "_title_drag_offset", None)
                if offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(event.globalPosition().toPoint() - offset)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._title_drag_offset = None
        return super().eventFilter(watched, event)

    def _action(
        self,
        menu: object,
        text: str,
        callback: object,
        shortcut: object = None,
        shortcut_id: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        default = QKeySequence()
        if shortcut is not None:
            default = QKeySequence(shortcut)
            action.setShortcut(default)
        action.triggered.connect(callback)
        menu.addAction(action)
        if shortcut_id is not None:
            self._register_shortcut(action, shortcut_id, default)
        return action

    def _register_shortcut(
        self, action: QAction, shortcut_id: str, default: QKeySequence
    ) -> None:
        settings_key = f"shortcuts/{shortcut_id}"
        if self.settings.contains(settings_key):
            action.setShortcut(QKeySequence(str(self.settings.value(settings_key))))
        self._shortcut_bindings[shortcut_id] = (
            action.text().replace("&", ""),
            action,
            default,
        )

    def _setting_bool(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def _setting_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.settings.value(key, default))
        except (TypeError, ValueError):
            value = default
        return min(max(value, minimum), maximum)

    def _restore_user_interface_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("window/state")
        if state:
            self.restoreState(state)
        # A stale/incompatible saved state used to leave the toolbars hidden with
        # no way to bring them back; force them visible at startup.
        if hasattr(self, "tool_rail") and not self.tool_rail.isVisible():
            self.tool_rail.setVisible(True)
        if (
            hasattr(self, "view_options_toolbar")
            and not self.view_options_toolbar.isVisible()
        ):
            self.view_options_toolbar.setVisible(True)

    def _save_user_interface_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.setValue("canvas/drawMode", self.view.draw_mode)
        self.settings.setValue("canvas/cropMode", self.view.crop_mode)
        self.settings.setValue("canvas/snapping", self.snap_checkbox.isChecked())
        self.settings.setValue("canvas/gridVisible", self.grid_checkbox.isChecked())
        self.settings.setValue("canvas/gridSnapping", self.grid_snap_checkbox.isChecked())
        self.settings.setValue("canvas/gridSize", self.grid_size.value())
        self.settings.setValue("canvas/gridSubdivisions", self.grid_subdivisions.value())
        self.settings.setValue(
            "canvas/wheelZoomModifier", self.view.wheel_zoom_modifier
        )
        self.settings.setValue(
            "inspector/guidesVisible", self.guides_panel_action.isChecked()
        )
        self.settings.setValue(
            "canvas/printGuidesVisible", self.print_guides_action.isChecked()
        )
        self.settings.setValue("canvas/bleedMargin", self.view.bleed_margin)
        self.settings.setValue("canvas/safeMargin", self.view.safe_margin)
        self.settings.sync()

    def _tool_action(
        self,
        text: str,
        icon_name: str,
        tooltip: str,
        callback: object,
        shortcut_id: str,
        shortcut: QKeySequence,
    ) -> QAction:
        icon_path = ICON_DIR / icon_name
        action = QAction(QIcon(str(icon_path)), text, self)
        action.setToolTip("")
        action.setData(tooltip)
        action.triggered.connect(callback)
        action.setShortcut(shortcut)
        self._register_shortcut(action, shortcut_id, shortcut)
        return action

    def _create_inspector_dock(self) -> None:
        self.inspector_card_scroll_areas: dict[str, QScrollArea] = {}
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )

    def _new_inspector_card(
        self, title: str, object_name: str
    ) -> tuple[QDockWidget, QVBoxLayout, QSplitter]:
        dock = PanelDock(title, object_name, self, minimum_width=250)
        splitter = QSplitter(Qt.Orientation.Vertical, dock)
        splitter.setObjectName(f"{title}CardSplitter")
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(True)
        scroll_area = QScrollArea(splitter)
        scroll_area.setObjectName(f"{title}CardScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll_area)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(9, 8, 9, 8)
        content_layout.setSpacing(6)
        scroll_area.setWidget(content)
        splitter.addWidget(scroll_area)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        dock.setWidget(splitter)
        self.inspector_card_scroll_areas[title] = scroll_area
        return dock, content_layout, splitter

    def _bind_panel_action(self, action: QAction, dock: QDockWidget) -> None:
        def on_toggled(visible: bool) -> None:
            dock.setVisible(visible)

        def on_visibility(visible: bool) -> None:
            if action.isChecked() != visible:
                action.blockSignals(True)
                action.setChecked(visible)
                action.blockSignals(False)

        action.toggled.connect(on_toggled)
        dock.visibilityChanged.connect(on_visibility)
        dock.setVisible(action.isChecked())

    def _region_row_button(self, icon_name: str, tooltip: str) -> QToolButton:
        return self._list_row_button(self.region_list, icon_name, tooltip)

    def _list_row_button(
        self, parent: QWidget, icon_name: str, tooltip: str
    ) -> QToolButton:
        icon_path = ICON_DIR / icon_name
        button = QToolButton(parent)
        button.setObjectName("regionRowAction")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(24, 24)
        button.setIconSize(QSize(15, 15))
        button.setIcon(QIcon(str(icon_path)))
        button.setAccessibleName(tooltip)
        button.setToolTip(tooltip)
        return button

    def closeEvent(self, event: object) -> None:
        worker = self._background_worker
        if worker is not None and worker.isRunning():
            event.ignore()
            return
        if self._confirm_discard():
            self._autosave_timer.stop()
            self._clear_recovery()
            self._save_user_interface_state()
            event.accept()
        else:
            event.ignore()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        if not getattr(self, "_initial_fit_scheduled", False):
            self._initial_fit_scheduled = True
            QTimer.singleShot(0, self.view.fit_canvas)
        if not getattr(self, "_recovery_offered", False):
            self._recovery_offered = True
            QTimer.singleShot(0, self._offer_recovery)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if hasattr(self, "maximize_button"):
            self.maximize_button.set_maximized(self.isMaximized())
            self.fullscreen_button.set_fullscreen(self.isFullScreen())
            self._update_rounded_window_shape()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._update_rounded_window_shape()

    def _update_rounded_window_shape(self) -> None:
        expanded = self.isMaximized() or self.isFullScreen()
        self.setProperty("windowExpanded", expanded)
        self.setProperty("windowCornerRadius", 0 if expanded else 6)
        self.update()

    def paintEvent(self, event: object) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        radius = int(self.property("windowCornerRadius") or 0)
        path.addRoundedRect(bounds, radius, radius)
        painter.fillPath(path, QColor("#f4f6f8"))
        if radius:
            painter.setPen(QPen(QColor("#d6dbe0"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _show_pointer(self, x: int, y: int) -> None:
        self.status.setText(f"坐标：X {x} px · Y {y} px    画布：{self.project.width} × {self.project.height} px")

    def _run_background(
        self,
        label: str,
        work: object,
        on_success: object,
        on_error: object,
        on_cancel: object = None,
    ) -> None:
        if self._background_worker is not None and self._background_worker.isRunning():
            self._error("操作进行中", "请等待当前操作完成后再试。")
            return
        dialog = QProgressDialog(label, "取消", 0, 0, self)
        dialog.setWindowTitle("JAVCover")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        worker = _BackgroundWorker(work, self)
        self._background_worker = worker

        def finish() -> None:
            dialog.close()
            dialog.deleteLater()
            self._background_worker = None
            worker.deleteLater()

        def handle_success(result: object) -> None:
            finish()
            on_success(result)

        def handle_failure(error: object) -> None:
            finish()
            on_error(error)

        def handle_cancel() -> None:
            finish()
            if on_cancel is not None:
                on_cancel()
            else:
                self.status.setText(f"已取消：{label}")

        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_failure)
        worker.cancelled.connect(handle_cancel)
        dialog.canceled.connect(worker.request_cancel)
        dialog.show()
        worker.start()

    def _update_title(self) -> None:
        self.setWindowTitle("JAVCover *" if self.dirty else "JAVCover")

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

