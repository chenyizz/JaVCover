"""Main application window."""
from __future__ import annotations

import copy
import hashlib
import re
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
    QBuffer,
    QEvent,
    QIODevice,
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
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QGridLayout,
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
from javcover.resources import ICON_DIR


from javcover.constants import (
    IMAGE_SUFFIXES,
    _BLEND_MODE_LABELS,
    format_output_name,
)
from javcover.ui.canvas import CoverScene, CoverView, DesignElementItem, RegionItem
from javcover.ui.dialogs import NewCanvasDialog, PreferencesDialog, TextElementDialog
from javcover.ui.flow_layout import FlowLayout
from javcover.ui.image_edit import ImageEditDialog
from javcover.ui.panel import PanelDock
from javcover.ui.widgets import (
    _DelayedToolTip,
    _ToolButtonFeedback,
    _WindowControlButton,
)
from javcover.ui.worker import _BackgroundWorker
from javcover.tasks import TaskCancelled
from javcover.ui.scrub import ScrubSpinBox

_ASSET_PREFIX = re.compile(r"^[0-9a-f]{32}_")


def _asset_display_name(path: Path) -> str:
    """Human-facing asset name: strips the uuid uniqueness prefix."""
    stripped = _ASSET_PREFIX.sub("", path.stem)
    return stripped or path.stem


class MainWindow(QMainWindow):
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
        self._update_recovery_path()

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

    def _create_guide_dock(self) -> None:
        self.guide_dock, layout, guide_splitter = self._new_inspector_card(
            "参考线", "guideDock"
        )
        self.guide_list = QListWidget()
        self.guide_list.currentRowChanged.connect(self._guide_selected)
        buttons = QHBoxLayout()
        for label, axis in (("＋垂直", "x"), ("＋水平", "y")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, a=axis: self.add_guide(a))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.guide_position = ScrubSpinBox()
        self.guide_position.setRange(0, 100_000)
        self.guide_position.setSuffix(" px")
        self.guide_position.editingFinished.connect(self._move_guide)
        layout.addWidget(QLabel("参考线名称"))
        self.guide_name = QLineEdit()
        self.guide_name.editingFinished.connect(self._rename_guide)
        layout.addWidget(self.guide_name)
        layout.addWidget(self.guide_position)
        delete_button = QPushButton("删除参考线")
        delete_button.clicked.connect(self.remove_guide)
        layout.addWidget(delete_button)
        layout.addStretch(1)
        guide_splitter.addWidget(self.guide_list)
        guide_splitter.setSizes([180, 220])
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.guide_dock)
        self._bind_panel_action(self.guides_panel_action, self.guide_dock)

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

    def _create_asset_store(self) -> None:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        self.asset_directory = Path(location) / "asset-library"
        self.asset_directory.mkdir(parents=True, exist_ok=True)
        self._update_recovery_path()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(4000)
        self._autosave_timer.timeout.connect(self._autosave)

    def _begin_edit(self) -> None:
        if self._edit_before is None:
            self._edit_before = copy.deepcopy(self.project)

    def _finish_edit(self) -> None:
        if self._edit_before is not None and self._edit_before != self.project:
            self.undo_stack.append(self._edit_before)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.dirty = True
            self._update_history_actions()
        self._edit_before = None
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_title()
        if self._recovery_enabled and self.dirty:
            self._autosave_timer.start()

    def _autosave(self) -> None:
        self._autosave_timer.stop()
        if not self.dirty:
            return
        try:
            save_project(self.project, self._recovery_path)
        except (OSError, TemplateError) as error:
            self.status.setText(f"自动保存失败：{error}")

    def _clear_recovery(self) -> None:
        try:
            self._recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _offer_recovery(self) -> None:
        if not self._recovery_enabled:
            return
        path = self._recovery_path
        if not path.is_file():
            return
        if self.current_path and Path(self.current_path).is_file():
            try:
                if Path(self.current_path).stat().st_mtime >= path.stat().st_mtime:
                    self._clear_recovery()
                    return
            except OSError:
                pass
        result = QMessageBox.question(
            self,
            "恢复上次会话",
            "检测到上次未正常退出时的自动保存。是否恢复到该状态？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if result != QMessageBox.StandardButton.Yes:
            self._clear_recovery()
            return
        try:
            project = load_project(path)
            self._replace_project(project, None)
            self.dirty = True
            self._update_title()
            self.status.setText("已从自动保存恢复；请“模板另存为…”保存到正式文件。")
        except (TemplateError, ImageError, OSError) as error:
            self._error("恢复失败", str(error))
            self._clear_recovery()

    def _replace_project(self, project: Project, path: Path | None) -> None:
        if project.base_png:
            base = decode_png(project.base_png)
            if base.width() != project.width or base.height() != project.height:
                raise ImageError("模板底图尺寸与画布尺寸不一致。")
        for region in project.regions:
            if region.background_png:
                decode_png(region.background_png)
        for element in project.elements:
            if element.kind == "image" and element.png:
                decode_png(element.png)
        self.view.set_project(project)
        self.project = project
        self.current_path = path
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_region_controls(None)
        self._update_history_actions()
        self._update_title()

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

    def _refresh_guide_list(self) -> None:
        selected = self.guide_list.currentRow()
        self.guide_list.blockSignals(True)
        self.guide_list.clear()
        for guide in self.project.guides:
            axis = "垂直" if guide.axis == "x" else "水平"
            label = f"{guide.name} · " if guide.name else ""
            self.guide_list.addItem(f"{label}{axis} · {guide.position} px")
        if self.project.guides:
            self.guide_list.setCurrentRow(min(max(selected, 0), len(self.project.guides) - 1))
        self.guide_list.blockSignals(False)
        self._guide_selected(self.guide_list.currentRow())

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

    def open_asset_library(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("本机素材库")
        dialog.resize(560, 520)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "素材仅保存在本机；放入画布后会嵌入当前 .javcover 项目。"
            "PSD 标题素材会保留来源，可在 Photoshop 修改后刷新。"
            "可用分类文件夹管理素材。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        category_row = QHBoxLayout()
        category_row.addWidget(QLabel("分类"))
        category_combo = QComboBox()
        category_row.addWidget(category_combo, 1)
        new_category_button = QPushButton("新建分类…")
        category_row.addWidget(new_category_button)
        layout.addLayout(category_row)

        listing = QListWidget()
        listing.setIconSize(QSize(52, 52))
        listing.setViewMode(QListView.ViewMode.IconMode)
        listing.setResizeMode(QListView.ResizeMode.Adjust)
        listing.setGridSize(QSize(96, 96))
        listing.setMovement(QListView.Movement.Static)
        layout.addWidget(listing, 1)

        def current_category_dir() -> Path:
            data = category_combo.currentData()
            if data:
                return self.asset_directory / str(data)
            return self.asset_directory

        def relist_categories(select: str | None = None) -> None:
            category_combo.blockSignals(True)
            category_combo.clear()
            category_combo.addItem("全部", None)
            subdirs = sorted(
                (p.name for p in self.asset_directory.iterdir() if p.is_dir()),
                key=str.casefold,
            )
            for name in subdirs:
                category_combo.addItem(name, name)
            if select is not None:
                index = category_combo.findData(select)
                category_combo.setCurrentIndex(index if index >= 0 else 0)
            category_combo.blockSignals(False)

        def thumbnail(path: Path) -> QImage | None:
            if path.suffix.lower() == ".psd":
                try:
                    image = rasterize_psd(path)
                except (PsdImportError, OSError):
                    return None
                return image.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if (
                size.width() <= 0
                or size.height() <= 0
                or size.width() * size.height() > MAX_CANVAS_PIXELS
            ):
                return None
            reader.setScaledSize(
                size.scaled(QSize(96, 96), Qt.AspectRatioMode.KeepAspectRatio)
            )
            image = reader.read()
            return None if image.isNull() else image

        def refresh() -> None:
            listing.clear()
            data = category_combo.currentData()
            if data:
                candidates = sorted((self.asset_directory / str(data)).iterdir())
            else:
                candidates = sorted(self.asset_directory.rglob("*"))
            for path in candidates:
                if not path.is_file() or path.suffix.lower() not in (
                    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".psd"
                ):
                    continue
                image = thumbnail(path)
                display = _asset_display_name(path)
                item = (
                    QListWidgetItem(QIcon(QPixmap.fromImage(image)), display)
                    if image is not None
                    else QListWidgetItem(display)
                )
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path.parent))
                listing.addItem(item)

        def import_paths(paths: list[Path], target: Path) -> None:
            target.mkdir(parents=True, exist_ok=True)
            for src in paths:
                if not src.is_file() or src.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                destination = target / f"{uuid4().hex}_{src.name}"
                try:
                    self._load_asset_image(src)
                    shutil.copy2(src, destination)
                except (ImageError, PsdImportError, OSError) as error:
                    self._error("素材导入失败", f"{src.name}：{error}")
            refresh()

        def import_assets() -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                dialog,
                "导入素材",
                "",
                "图片与 PSD (*.png *.jpg *.jpeg *.webp *.bmp *.psd);;所有文件 (*)",
            )
            if paths:
                import_paths([Path(p) for p in paths], current_category_dir())

        def import_folder() -> None:
            chosen = QFileDialog.getExistingDirectory(
                dialog, "导入素材文件夹（含子文件夹）", ""
            )
            if not chosen:
                return
            folder = Path(chosen)
            files = [p for p in folder.rglob("*") if p.is_file()]
            if not files:
                self._error("没有素材", "所选文件夹中没有文件。")
                return
            import_paths(files, current_category_dir())

        def create_category() -> None:
            name, accepted = QInputDialog.getText(dialog, "新建分类", "分类名称")
            if not accepted:
                return
            name = name.strip()
            if not name:
                return
            target = self.asset_directory / name
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self._error("创建分类失败", str(error))
                return
            relist_categories(name)
            refresh()

        def place_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            dialog.accept()
            self._place_asset(Path(item.data(Qt.ItemDataRole.UserRole)))

        def delete_selected() -> None:
            items = listing.selectedItems()
            if not items:
                return
            if len(items) == 1:
                label = _asset_display_name(Path(items[0].data(Qt.ItemDataRole.UserRole)))
                message = f"从本机素材库删除“{label}”？\n已放入画布的图层不受影响。"
            else:
                message = (
                    f"从本机素材库删除选中的 {len(items)} 个素材？\n"
                    "已放入画布的图层不受影响。"
                )
            confirmed = QMessageBox.question(
                dialog,
                "删除素材",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
            for item in items:
                path = Path(item.data(Qt.ItemDataRole.UserRole))
                try:
                    path.unlink()
                except OSError as error:
                    self._error("删除素材失败", str(error))
            refresh()

        def rename_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            current = _asset_display_name(path)
            name, accepted = QInputDialog.getText(
                dialog, "重命名素材", "名称", text=current
            )
            name = name.strip()
            if not accepted or not name or name == current:
                return
            match = _ASSET_PREFIX.match(path.stem)
            prefix = match.group(0) if match else ""
            destination = path.with_name(f"{prefix}{name}{path.suffix}")
            if destination.exists():
                self._error("重命名失败", "同名素材已存在。")
                return
            old_name = path.name
            try:
                path.rename(destination)
            except OSError as error:
                self._error("重命名失败", str(error))
                return
            for element in self.project.elements:
                if element.asset_name == old_name:
                    element.asset_name = destination.name
            refresh()

        category_combo.currentIndexChanged.connect(lambda _index: refresh())
        new_category_button.clicked.connect(create_category)
        listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        select_all = QShortcut(
            QKeySequence(QKeySequence.StandardKey.SelectAll), listing
        )
        select_all.activated.connect(listing.selectAll)
        rename_shortcut = QShortcut(QKeySequence("F2"), listing)
        rename_shortcut.activated.connect(rename_selected)
        delete_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.Delete), listing
        )
        delete_shortcut.activated.connect(delete_selected)
        buttons = QHBoxLayout()
        add_button = QPushButton("导入文件…")
        add_button.clicked.connect(import_assets)
        folder_button = QPushButton("导入文件夹…")
        folder_button.clicked.connect(import_folder)
        rename_button = QPushButton("重命名")
        rename_button.clicked.connect(rename_selected)
        delete_button = QPushButton("删除素材")
        delete_button.clicked.connect(delete_selected)
        place_button = QPushButton("放入画布")
        place_button.clicked.connect(place_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(folder_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        buttons.addWidget(place_button)
        layout.addLayout(buttons)
        listing.itemDoubleClicked.connect(lambda _item: place_selected())
        relist_categories()
        refresh()
        dialog.exec()

    def _link_asset(self, element: DesignElement, path: Path) -> None:
        try:
            path.relative_to(self.asset_directory)
        except ValueError:
            return
        element.asset_name = path.name
        element.asset_kind = "psd" if path.suffix.lower() == ".psd" else "image"
        try:
            element.asset_hash = self._hash_file(path)
        except OSError:
            element.asset_hash = None

    def _build_image_element(
        self, image: QImage, path: Path, scene_pos: QPointF, region: Region | None
    ) -> DesignElement:
        if region is not None:
            fitted = image.scaled(
                min(image.width(), region.rect.width),
                min(image.height(), region.rect.height),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            rect = Rect(
                int(scene_pos.x() - fitted.width() / 2),
                int(scene_pos.y() - fitted.height() / 2),
                fitted.width(),
                fitted.height(),
            ).bounded_within(region.rect)
            element = DesignElement(
                kind="image",
                x=rect.x,
                y=rect.y,
                width=rect.width,
                height=rect.height,
                name=_asset_display_name(path),
                png=encode_png(fitted),
                region_id=region.id,
            )
        else:
            if image.width() > self.project.width or image.height() > self.project.height:
                image = image.scaled(
                    min(image.width(), self.project.width),
                    min(image.height(), self.project.height),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            rect = Rect(
                int(scene_pos.x() - image.width() / 2),
                int(scene_pos.y() - image.height() / 2),
                image.width(),
                image.height(),
            ).bounded(self.project.width, self.project.height)
            element = DesignElement(
                kind="image",
                x=rect.x,
                y=rect.y,
                width=rect.width,
                height=rect.height,
                name=_asset_display_name(path),
                png=encode_png(image),
            )
        self._link_asset(element, path)
        return element

    def _on_files_dropped(self, paths: list[str], scene_pos: QPointF) -> None:
        if self.project is None or not paths:
            return
        region = self.view._region_at(scene_pos)
        self._begin_edit()
        placed: list[DesignElement] = []
        for raw in paths:
            path = Path(raw)
            try:
                image = self._load_asset_image(path)
            except (ImageError, PsdImportError, OSError) as error:
                self._error("素材读取失败", f"{path.name}：{error}")
                continue
            placed.append(self._build_image_element(image, path, scene_pos, region))
        if not placed:
            self._edit_before = None
            return
        self.project.elements.extend(placed)
        self.view.refresh_overlays()
        self.view.select_element(placed[-1].id)
        self._finish_edit()
        if region is not None:
            self.status.setText(f"已将 {len(placed)} 个图层放入区域“{region.name}”。")
        else:
            self.status.setText(f"已放置 {len(placed)} 个图层。")

    def _place_asset(self, path: Path) -> None:
        try:
            image = self._load_asset_image(path)
        except (ImageError, PsdImportError, OSError) as error:
            self._error("素材读取失败", str(error))
            return
        element = self._build_image_element(
            image, path, QPointF(self.project.width / 2, self.project.height / 2), None
        )
        self._begin_edit()
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def _analysis_image(self) -> QImage:
        """Image used by the color/OCR assists.

        Uses the composed cover (base + visible region backgrounds) so the tools
        also work on opened templates that carry their content as region
        backgrounds instead of a base image.
        """
        has_content = bool(self.project.base_png) or any(
            region.background_png for region in self.project.regions
        )
        if not has_content:
            raise ImageError(
                "请先导入封面图片，或为区域设置背景，再运行分析。"
            )
        return compose_project(self.project)

    def run_color_block_assist(self) -> None:
        try:
            analysis = self._analysis_image()
        except ImageError as error:
            self._error("需要底图", str(error))
            return
        try:
            candidates = suggest_color_blocks(analysis)
        except ImageError as error:
            self._error("色块分析失败", str(error))
            return
        if not candidates:
            self.status.setText("没有检测到明显的大色块边界；可以手动画框或调整参考线。")
            return
        self._begin_edit()
        for index, rect in enumerate(candidates, start=1):
            self.project.add_region(rect).name = f"色块候选 {index}"
        self.view.refresh_overlays()
        self.view.select_region(self.project.regions[-1].id)
        self._finish_edit()
        self.status.setText(f"已添加 {len(candidates)} 个色块候选，可在画布和属性栏中校正。")

    def run_ocr_assist(self) -> None:
        try:
            analysis = self._analysis_image()
        except ImageError as error:
            self._error("需要底图", str(error))
            return
        executable = str(self.settings.value("ocr/tesseractPath", "") or "") or None
        tessdata_dir = str(self.settings.value("ocr/tessdataPath", "") or "") or None

        def work(cancel) -> list[tuple[Rect, str]]:
            return recognize_japanese_text(
                analysis,
                executable=executable,
                tessdata_dir=tessdata_dir,
                cancel_event=cancel,
            )

        def on_success(candidates: list[tuple[Rect, str]]) -> None:
            self._apply_ocr_candidates(candidates)

        def on_error(error: object) -> None:
            result = QMessageBox.warning(
                self,
                "OCR 尚未配置",
                f"{error}\n\n现在打开 OCR 设置？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if result == QMessageBox.StandardButton.Yes:
                self.configure_ocr()

        self._run_background("正在本机识别日文文字…", work, on_success, on_error)

    def _apply_ocr_candidates(self, candidates: list[tuple[Rect, str]]) -> None:
        if not candidates:
            self.status.setText("OCR 未发现可用文字候选。")
            return
        clipped_candidates: list[tuple[Rect, str]] = []
        for rect, text in candidates:
            left = max(0, rect.x)
            top = max(0, rect.y)
            right = min(self.project.width, rect.right)
            bottom = min(self.project.height, rect.bottom)
            if right <= left or bottom <= top:
                continue
            clipped_candidates.append((Rect(left, top, right - left, bottom - top), text))
        if not clipped_candidates:
            self.status.setText("OCR 结果均位于画布外，没有添加区域。")
            return
        self._begin_edit()
        for clipped, text in clipped_candidates:
            region = self.project.add_region(clipped)
            region.name = f"OCR · {text[:18]}"
        self.view.refresh_overlays()
        self.view.select_region(self.project.regions[-1].id)
        self._finish_edit()
        self.status.setText(
            f"OCR 生成 {len(clipped_candidates)} 个文字区域候选；识别结果请人工校对。"
        )

    def configure_ocr(self) -> None:
        settings = self.settings
        dialog = QDialog(self)
        dialog.setWindowTitle("配置日文 OCR")
        dialog.resize(620, 260)
        layout = QVBoxLayout(dialog)
        instructions = QLabel(
            "JAVCover 使用本机 Tesseract，不会上传封面。请安装 Windows 版 "
            "Tesseract，并准备 jpn.traineddata（以及 eng.traineddata）；"
            "安装器中需勾选 Japanese language data。"
            '<br><a href="https://github.com/UB-Mannheim/tesseract/wiki">'
            "Windows 安装说明</a> · "
            '<a href="https://github.com/tesseract-ocr/tessdata_fast/blob/main/jpn.traineddata">'
            "下载官方日文语言数据</a>"
        )
        instructions.setWordWrap(True)
        instructions.setOpenExternalLinks(True)
        layout.addWidget(instructions)
        form = QFormLayout()
        executable_edit = QLineEdit(
            str(settings.value("ocr/tesseractPath", "") or "")
        )
        tessdata_edit = QLineEdit(
            str(settings.value("ocr/tessdataPath", "") or "")
        )
        executable_row = QHBoxLayout()
        executable_row.addWidget(executable_edit)
        executable_browse = QPushButton("浏览…")
        executable_row.addWidget(executable_browse)
        tessdata_row = QHBoxLayout()
        tessdata_row.addWidget(tessdata_edit)
        tessdata_browse = QPushButton("浏览…")
        tessdata_row.addWidget(tessdata_browse)
        form.addRow("tesseract.exe", executable_row)
        form.addRow("tessdata 文件夹", tessdata_row)
        layout.addLayout(form)
        check_status = QLabel("选择程序和语言目录后，点击“检查配置”。")
        check_status.setWordWrap(True)
        layout.addWidget(check_status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        check_button = buttons.addButton(
            "检查配置", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def browse_executable() -> None:
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                "选择 Tesseract 程序",
                executable_edit.text(),
                "Tesseract (tesseract.exe);;所有文件 (*)",
            )
            if path:
                executable_edit.setText(path)

        def browse_tessdata() -> None:
            path = QFileDialog.getExistingDirectory(
                dialog, "选择包含 jpn.traineddata 的 tessdata 文件夹",
                tessdata_edit.text(),
            )
            if path:
                tessdata_edit.setText(path)

        def validate_configuration() -> bool:
            try:
                executable = resolve_tesseract(executable_edit.text().strip() or None)
                tessdata_dir = tessdata_edit.text().strip() or None
                languages = list_tesseract_languages(executable, tessdata_dir)
                missing = {"jpn", "eng"} - languages
                if missing:
                    raise RuntimeError(
                        "语言目录缺少 "
                        + ", ".join(sorted(missing))
                        + "。请安装对应的 .traineddata 文件，再重新检查。"
                    )
            except (RuntimeError, OSError) as error:
                check_status.setText(str(error))
                check_status.setStyleSheet("color: #b42318;")
                return False
            check_status.setText(
                f"配置正常：找到 jpn 和 eng。Tesseract：{executable}"
            )
            check_status.setStyleSheet("color: #137333;")
            return True

        def accept_validated() -> None:
            if not validate_configuration():
                return
            executable = resolve_tesseract(executable_edit.text().strip() or None)
            settings.setValue("ocr/tesseractPath", executable)
            settings.setValue("ocr/tessdataPath", tessdata_edit.text().strip())
            settings.sync()
            dialog.accept()

        executable_browse.clicked.connect(browse_executable)
        tessdata_browse.clicked.connect(browse_tessdata)
        check_button.clicked.connect(validate_configuration)
        buttons.accepted.connect(accept_validated)
        dialog.exec()

    def add_guide(self, axis: Literal["x", "y"]) -> None:
        limit = self.project.width if axis == "x" else self.project.height
        axis_name = "垂直参考线 X" if axis == "x" else "水平参考线 Y"
        position, accepted = QInputDialog.getInt(
            self, "添加参考线", axis_name, limit // 2, 0, limit
        )
        if not accepted:
            return
        self.add_guide_at(axis, position)

    def add_guide_at(self, axis: str, position: int) -> None:
        if axis not in ("x", "y"):
            return
        guide_axis: Literal["x", "y"] = "x" if axis == "x" else "y"
        limit = self.project.width if axis == "x" else self.project.height
        position = min(max(0, position), limit)
        self._begin_edit()
        self.project.guides.append(Guide(guide_axis, position))
        self.view.refresh_overlays()
        self._finish_edit()
        self.guide_list.setCurrentRow(len(self.project.guides) - 1)

    def _guide_selected(self, row: int) -> None:
        enabled = 0 <= row < len(self.project.guides)
        self.guide_position.setEnabled(enabled)
        self.guide_name.setEnabled(enabled)
        if enabled:
            guide = self.project.guides[row]
            self.guide_position.setMaximum(self.project.width if guide.axis == "x" else self.project.height)
            self.guide_position.setValue(guide.position)
            self.guide_name.setText(guide.name)
        else:
            self.guide_position.setValue(0)
            self.guide_name.clear()

    def _rename_guide(self) -> None:
        row = self.guide_list.currentRow()
        if not 0 <= row < len(self.project.guides):
            return
        old = self.project.guides[row]
        name = self.guide_name.text().strip()
        if name == old.name:
            return
        self._begin_edit()
        self.project.guides[row] = Guide(old.axis, old.position, name)
        self._finish_edit()

    def _move_guide(self) -> None:
        row = self.guide_list.currentRow()
        if not 0 <= row < len(self.project.guides):
            return
        old = self.project.guides[row]
        position = self.guide_position.value()
        if position == old.position:
            return
        self._begin_edit()
        self.project.guides[row] = Guide(old.axis, position, old.name)
        self.view.refresh_overlays()
        self._finish_edit()

    def remove_guide(self) -> None:
        row = self.guide_list.currentRow()
        if not 0 <= row < len(self.project.guides):
            return
        self._begin_edit()
        del self.project.guides[row]
        self.view.refresh_overlays()
        self._finish_edit()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        dialog = NewCanvasDialog(
            self,
            self._setting_int("canvas/defaultWidth", 1200, 1, 100_000),
            self._setting_int("canvas/defaultHeight", 800, 1, 100_000),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height, shape = dialog.values()
        if width * height > MAX_CANVAS_PIXELS:
            self._error("画布尺寸过大", "画布最多支持 1 亿像素，请减小宽度或高度。")
            return
        self.settings.setValue("canvas/defaultWidth", width)
        self.settings.setValue("canvas/defaultHeight", height)
        self.settings.sync()
        self._replace_project(Project(width, height, shape=shape), None)

    def open_image(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开封面图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;所有文件 (*)"
        )
        if not path:
            return
        try:
            image = load_image(path)
            project = Project(image.width(), image.height(), base_png=encode_png(image))
            self._replace_project(project, None)
        except ImageError as error:
            self._error("图片读取失败", str(error))

    def open_psd(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Photoshop 文档", "", "Photoshop 文档 (*.psd)"
        )
        if not path:
            return

        def work(cancel) -> Project:
            if cancel.is_set():
                raise TaskCancelled()
            return import_psd(path)

        def on_success(project: Project) -> None:
            self._replace_project(project, None)
            editable = sum(element.kind == "text" for element in project.elements)
            self.status.setText(
                f"已导入 PSD 并提取 {editable} 个文字图层，可直接编辑替换文字。"
                "已保留首段字体/字号/颜色等基础样式；复杂图层效果不会完整转换。"
            )

        def on_error(error: object) -> None:
            self._error("PSD 导入失败", str(error))

        self._run_background("正在导入 PSD…", work, on_success, on_error)

    def place_psd_title_asset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "放置 PSD 标题素材", "", "Photoshop 文档 (*.psd)"
        )
        if not path:
            return
        try:
            destination = self._import_into_assets(Path(path))
        except OSError as error:
            self._error("素材导入失败", str(error))
            return
        self._place_asset(destination)

    def refresh_selected_asset(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.kind != "image" or not element.asset_name:
            self._error("无法刷新", "请先选择一个从素材库放置的图片图层。")
            return
        path = self._asset_path_for(element.asset_name)
        if path is None:
            self._error(
                "素材缺失",
                f"素材库中找不到“{element.asset_name}”。可使用“重新链接素材”指向新文件。",
            )
            return
        self._replace_element_asset(element, path)

    def relink_selected_asset(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.kind != "image":
            self._error("无法重新链接", "请先选择一个图片图层。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "重新链接素材",
            "",
            "图片与 PSD (*.psd *.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        source = Path(path)
        try:
            destination = (
                source
                if source.parent == self.asset_directory
                else self._import_into_assets(source)
            )
        except OSError as error:
            self._error("素材导入失败", str(error))
            return
        self._replace_element_asset(element, destination)

    def _replace_element_asset(self, element: DesignElement, path: Path) -> None:
        try:
            encoded = encode_png(self._load_asset_image(path))
            digest = self._hash_file(path)
        except (ImageError, PsdImportError, OSError) as error:
            self._error("素材刷新失败", str(error))
            return
        self._begin_edit()
        element.png = encoded
        element.asset_name = path.name
        element.asset_kind = "psd" if path.suffix.lower() == ".psd" else "image"
        element.asset_hash = digest
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()
        self.status.setText(f"已从素材刷新：{element.name}")

    def _load_asset_image(self, path: Path) -> QImage:
        if path.suffix.lower() == ".psd":
            return rasterize_psd(path)
        return load_image(path)

    def _import_into_assets(self, source: Path) -> Path:
        destination = self.asset_directory / f"{uuid4().hex}_{source.name}"
        shutil.copy2(source, destination)
        return destination

    def _asset_path_for(self, asset_name: str) -> Path | None:
        if not asset_name or "/" in asset_name or "\\" in asset_name:
            return None
        direct = self.asset_directory / asset_name
        if direct.is_file():
            return direct
        for candidate in self.asset_directory.rglob(asset_name):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def open_template(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 JAVCover 模板", "", "JAVCover 模板 (*.javcover);;所有文件 (*)"
        )
        if not path:
            return
        try:
            project = load_project(path)
            self._replace_project(project, Path(path))
        except (TemplateError, ImageError, OSError) as error:
            self._error("模板打开失败", str(error))

    def save_template(self) -> None:
        if self.current_path is None:
            self.save_template_as()
            return
        self._save_to(self.current_path)

    def save_template_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 JAVCover 模板", "", "JAVCover 模板 (*.javcover)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".javcover":
            destination = destination.with_suffix(".javcover")
        self._save_to(destination)

    def _save_to(self, path: Path) -> None:
        try:
            save_project(self.project, path)
        except OSError as error:
            self._error("模板保存失败", str(error))
            return
        self.current_path = path
        self.dirty = False
        self._autosave_timer.stop()
        self._clear_recovery()
        self._update_title()
        self.status.setText(f"已保存模板：{path}")

    def _default_export_path(self) -> str:
        directory = str(self.settings.value("export/lastDir", "") or "")
        stem = self.current_path.stem if self.current_path else "cover"
        name = f"{stem}.png"
        return str(Path(directory) / name) if directory else name

    def _render_export(
        self, project: Project, destination: Path, image_format: str, quality: int
    ) -> Path:
        image = compose_project(project)
        if image_format == "JPEG":
            flattened = QImage(image.size(), QImage.Format.Format_RGB32)
            flattened.fill(QColor("#ffffff"))
            painter = QPainter(flattened)
            painter.drawImage(0, 0, image)
            painter.end()
            image = flattened
        self._apply_icc_profile(image)
        save_quality = quality if image_format == "JPEG" else -1
        if not image.save(str(destination), image_format, save_quality):
            raise ImageError("Qt 无法写入所选图片格式。")
        return destination

    def _apply_icc_profile(self, image: QImage) -> None:
        profile = str(self.settings.value("export/iccProfile", "") or "").strip()
        if not profile:
            return
        path = Path(profile)
        if not path.is_file():
            return
        try:
            space = QColorSpace.fromIccProfile(path.read_bytes())
        except OSError:
            return
        if space.isValid():
            image.setColorSpace(space)

    def _render_batch_stem(
        self,
        template_project: Project,
        region_sources: list[tuple[str, Path]],
        destination: Path,
        image_format: str,
        quality: int,
    ) -> Path:
        project = copy.deepcopy(template_project)
        filled = False
        for region_id, source in region_sources:
            region = next(
                (item for item in project.regions if item.id == region_id), None
            )
            if region is None:
                continue
            region.background_png = encode_png(self._load_asset_image(source))
            filled = True
        if not filled:
            raise ImageError("没有任何区域获得素材。")
        return self._render_export(project, destination, image_format, quality)

    def _render_batch_item(
        self,
        template_project: Project,
        region_id: str,
        source: Path,
        destination: Path,
        image_format: str,
        quality: int,
    ) -> Path:
        return self._render_batch_stem(
            template_project, [(region_id, source)], destination, image_format, quality
        )

    def _pick_directory(self, parent: QWidget, edit: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(parent, "选择文件夹", edit.text())
        if chosen:
            edit.setText(chosen)

    def export_image(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出封面",
            self._default_export_path(),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            destination = destination.with_suffix(".jpg" if "JPEG" in selected_filter else ".png")
        image_format = "JPEG" if destination.suffix.lower() in (".jpg", ".jpeg") else "PNG"
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        project = self.project

        def work(cancel) -> Path:
            if cancel.is_set():
                raise TaskCancelled()
            return self._render_export(project, destination, image_format, quality)

        def on_success(saved: Path) -> None:
            self.settings.setValue("export/lastDir", str(saved.parent))
            self.settings.sync()
            self.status.setText(f"已导出：{saved}")

        def on_error(error: object) -> None:
            self._error("导出失败", str(error))

        self._run_background("正在导出封面…", work, on_success, on_error)

    def _render_cmyk(
        self,
        project: Project,
        destination: Path,
        profile: str,
        quality: int,
    ) -> Path:
        from io import BytesIO

        from PIL import Image, ImageCms

        image = compose_project(project)
        flattened = QImage(image.size(), QImage.Format.Format_RGB32)
        flattened.fill(QColor("#ffffff"))
        painter = QPainter(flattened)
        painter.drawImage(0, 0, image)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        flattened.save(buffer, "PNG")
        data = bytes(buffer.data())
        buffer.close()
        pil = Image.open(BytesIO(data)).convert("RGB")
        icc_bytes: bytes | None = None
        if profile:
            profile_path = Path(profile)
            if profile_path.is_file():
                icc_bytes = profile_path.read_bytes()
                try:
                    destination_profile = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
                    pil = ImageCms.profileToProfile(
                        pil,
                        ImageCms.createProfile("sRGB"),
                        destination_profile,
                        outputMode="CMYK",
                        renderingIntent=ImageCms.Intent.PERCEPTUAL,
                    )
                except Exception:  # noqa: BLE001 - fall back to a naive conversion
                    pil = pil.convert("CMYK")
            else:
                pil = pil.convert("CMYK")
        else:
            pil = pil.convert("CMYK")
        save_kwargs: dict[str, object] = {}
        if icc_bytes:
            save_kwargs["icc_profile"] = icc_bytes
        if destination.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs["quality"] = quality
        pil.save(str(destination), **save_kwargs)
        return destination

    def export_cmyk(self) -> None:
        try:
            import PIL  # noqa: F401
        except ImportError:
            self._error(
                "需要 Pillow",
                "CMYK 导出需要 Pillow 依赖，请运行：\n"
                '.\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e ".[cmyk]"',
            )
            return
        default = Path(self._default_export_path()).with_suffix(".tif")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CMYK",
            str(default),
            "TIFF 图片 (*.tif *.tiff);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() not in (".tif", ".tiff", ".jpg", ".jpeg"):
            destination = destination.with_suffix(".tif")
        profile = str(self.settings.value("export/cmykProfile", "") or "")
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        project = self.project

        def work(cancel) -> Path:
            if cancel.is_set():
                raise TaskCancelled()
            return self._render_cmyk(project, destination, profile, quality)

        def on_success(saved: Path) -> None:
            self.settings.setValue("export/lastDir", str(saved.parent))
            self.settings.sync()
            self.status.setText(f"已导出 CMYK：{saved}")

        def on_error(error: object) -> None:
            self._error("CMYK 导出失败", str(error))

        self._run_background("正在导出 CMYK…", work, on_success, on_error)

    def batch_export(self) -> None:
        if not self.project.regions:
            self._error(
                "缺少区域",
                "批量生成需要至少一个区域。请先创建区域或运行色块分析。",
            )
            return
        regions = list(self.project.regions)
        dialog = QDialog(self)
        dialog.setWindowTitle("批量生成封面（流水线）")
        dialog.resize(760, 460)
        outer = QVBoxLayout(dialog)
        hint = QLabel(
            "为每个目标区域选择一个素材文件夹；程序按文件名（不含扩展名）对应组合，"
            "例如 封面/1.jpg + 脊柱/1.jpg 一起生成 1.png。目标区域最多与模板区域数相同。"
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(4)
        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setWidget(rows_container)
        outer.addWidget(rows_scroll, 1)
        entries: list[dict[str, object]] = []

        def remove_row(row: dict[str, object]) -> None:
            if len(entries) <= 1:
                return
            entries.remove(row)
            widget = row["widget"]
            widget.setParent(None)
            widget.deleteLater()

        def add_row(region_index: int = 0) -> None:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            combo = QComboBox()
            for region in regions:
                combo.addItem(
                    f"{region.name} ({region.rect.width}×{region.rect.height})",
                    region.id,
                )
            combo.setCurrentIndex(min(region_index, combo.count() - 1))
            folder_edit = QLineEdit()
            folder_edit.setPlaceholderText("素材文件夹…")
            browse = QPushButton("浏览…")
            remove = QPushButton("移除")
            row_layout.addWidget(QLabel("区域"))
            row_layout.addWidget(combo, 2)
            row_layout.addWidget(QLabel("素材"))
            row_layout.addWidget(folder_edit, 3)
            row_layout.addWidget(browse)
            row_layout.addWidget(remove)
            row = {"widget": row_widget, "combo": combo, "folder": folder_edit}
            entries.append(row)
            rows_layout.addWidget(row_widget)
            browse.clicked.connect(
                lambda _checked=False, edit=folder_edit: self._pick_directory(dialog, edit)
            )
            remove.clicked.connect(lambda _checked=False, r=row: remove_row(r))

        def add_target() -> None:
            if len(entries) >= len(regions):
                QMessageBox.information(
                    dialog,
                    "已达上限",
                    f"模板有 {len(regions)} 个区域，目标区域最多 {len(regions)} 个。",
                )
                return
            add_row(len(entries) % len(regions))

        add_row(0)
        add_button = QPushButton("添加目标区域")
        add_button.clicked.connect(add_target)
        outer.addWidget(add_button)

        options = QFormLayout()
        output_row = QHBoxLayout()
        output_edit = QLineEdit()
        output_browse = QPushButton("浏览…")
        output_row.addWidget(output_edit)
        output_row.addWidget(output_browse)
        options.addRow("输出文件夹", output_row)
        format_combo = QComboBox()
        format_combo.addItem("PNG", "PNG")
        format_combo.addItem("JPEG", "JPEG")
        options.addRow("输出格式", format_combo)
        pattern_edit = QLineEdit("{name}")
        pattern_edit.setToolTip("可用 {name}（素材名）、{index}（序号）、{date}（日期）")
        options.addRow("文件名模式", pattern_edit)
        outer.addLayout(options)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons)
        output_browse.clicked.connect(lambda: self._pick_directory(dialog, output_edit))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        output_dir = Path(output_edit.text().strip())
        if not output_dir.is_dir():
            self._error("文件夹无效", "请选择存在的输出文件夹。")
            return
        per_region: list[tuple[str, dict[str, Path]]] = []
        all_stems: set[str] = set()
        for row in entries:
            folder = Path(str(row["folder"].text()).strip())
            combo = row["combo"]
            if not folder.is_dir():
                self._error(
                    "文件夹无效",
                    f"请为“{combo.currentText()}”选择存在的素材文件夹。",
                )
                return
            mapping: dict[str, Path] = {}
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    mapping.setdefault(path.stem, path)
            per_region.append((combo.currentData(), mapping))
            all_stems.update(mapping)
        if not all_stems:
            self._error("没有素材", "所选素材文件夹中没有支持的图片文件。")
            return
        image_format = format_combo.currentData()
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        pattern = pattern_edit.text().strip() or "{name}"
        extension = ".jpg" if image_format == "JPEG" else ".png"
        template_project = copy.deepcopy(self.project)
        stems = sorted(all_stems)
        date_token = datetime.now().strftime("%Y%m%d")

        def work(cancel) -> tuple[list[Path], list[tuple[str, str]], int]:
            outputs: list[Path] = []
            failures: list[tuple[str, str]] = []
            partial = 0
            for index, stem in enumerate(stems, start=1):
                if cancel.is_set():
                    raise TaskCancelled()
                region_sources = [
                    (region_id, mapping[stem])
                    for region_id, mapping in per_region
                    if stem in mapping
                ]
                if len(region_sources) < len(per_region):
                    partial += 1
                if not region_sources:
                    continue
                name = format_output_name(pattern, stem, index, date_token)
                destination = output_dir / f"{name}{extension}"
                try:
                    self._render_batch_stem(
                        template_project,
                        region_sources,
                        destination,
                        image_format,
                        quality,
                    )
                    outputs.append(destination)
                except (ImageError, PsdImportError, OSError) as error:
                    failures.append((stem, str(error)))
            return outputs, failures, partial

        def on_success(result: tuple[list[Path], list[tuple[str, str]], int]) -> None:
            outputs, failures, partial = result
            self.settings.setValue("export/lastDir", str(output_dir))
            self.settings.sync()
            message = (
                f"批量生成完成：成功 {len(outputs)} 张，失败 {len(failures)} 张，"
                f"{partial} 张存在缺失区域素材。"
            )
            self.status.setText(message)
            if failures:
                detail = "\n".join(f"{name}：{err}" for name, err in failures[:8])
                QMessageBox.warning(self, "部分素材失败", f"{message}\n{detail}")

        def on_error(error: object) -> None:
            self._error("批量生成失败", str(error))

        self._run_background(
            f"正在批量生成 {len(stems)} 张封面…", work, on_success, on_error
        )

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.project))
        self.project = self.undo_stack.pop()
        self.dirty = True
        self.view.set_project(self.project, preserve_view=True)
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_history_actions()
        self._update_title()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.project))
        self.project = self.redo_stack.pop()
        self.dirty = True
        self.view.set_project(self.project, preserve_view=True)
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_history_actions()
        self._update_title()

    def _update_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self.undo_stack))
            self.redo_action.setEnabled(bool(self.redo_stack))

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        result = QMessageBox.question(
            self,
            "未保存更改",
            "当前模板有未保存的更改。是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            self.save_template()
            return not self.dirty
        return True

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

    def open_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == ".javcover":
            try:
                project = load_project(path)
                self._replace_project(project, path)
            except (TemplateError, ImageError, OSError) as error:
                self._error("模板打开失败", str(error))
        elif suffix in IMAGE_SUFFIXES:
            try:
                image = load_image(path)
                self._replace_project(
                    Project(image.width(), image.height(), base_png=encode_png(image)),
                    None,
                )
            except ImageError as error:
                self._error("图片读取失败", str(error))


