"""Application dialogs (preferences, text element)."""
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


class PreferencesDialog(QDialog):
    def __init__(
        self,
        preferences: dict[str, bool | int | str],
        shortcuts: dict[str, tuple[str, QAction, QKeySequence]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("偏好设置")
        self.setMinimumSize(540, 500)
        self.shortcuts = shortcuts
        self._shortcut_edits: dict[str, QKeySequenceEdit] = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        layout.addWidget(tabs, 1)

        general_tab = QWidget(tabs)
        general_form = QFormLayout(general_tab)
        self.grid_visible = QCheckBox("显示像素网格")
        self.grid_visible.setChecked(bool(preferences["canvas/gridVisible"]))
        general_form.addRow(self.grid_visible)
        self.snapping_enabled = QCheckBox("启用常规磁吸")
        self.snapping_enabled.setChecked(bool(preferences["canvas/snapping"]))
        general_form.addRow(self.snapping_enabled)
        self.grid_snapping_enabled = QCheckBox("启用网格吸附")
        self.grid_snapping_enabled.setChecked(
            bool(preferences["canvas/gridSnapping"])
        )
        general_form.addRow(self.grid_snapping_enabled)
        self.guides_visible = QCheckBox("显示参考线面板")
        self.guides_visible.setChecked(bool(preferences["inspector/guidesVisible"]))
        general_form.addRow(self.guides_visible)
        self.print_guides = QCheckBox("显示印刷参考线（出血/安全区）")
        self.print_guides.setChecked(bool(preferences["canvas/printGuidesVisible"]))
        general_form.addRow(self.print_guides)
        self.bleed_margin = QSpinBox()
        self.bleed_margin.setRange(0, 100_000)
        self.bleed_margin.setSuffix(" px")
        self.bleed_margin.setValue(int(preferences["canvas/bleedMargin"]))
        general_form.addRow("出血（向内）", self.bleed_margin)
        self.safe_margin = QSpinBox()
        self.safe_margin.setRange(0, 100_000)
        self.safe_margin.setSuffix(" px")
        self.safe_margin.setValue(int(preferences["canvas/safeMargin"]))
        general_form.addRow("安全区（向内）", self.safe_margin)

        self.grid_size = QSpinBox()
        self.grid_size.setRange(1, 1000)
        self.grid_size.setSuffix(" px")
        self.grid_size.setValue(int(preferences["canvas/gridSize"]))
        general_form.addRow("主网格间距", self.grid_size)
        self.grid_subdivisions = QSpinBox()
        self.grid_subdivisions.setRange(1, 20)
        self.grid_subdivisions.setSuffix(" 分格")
        self.grid_subdivisions.setValue(int(preferences["canvas/gridSubdivisions"]))
        general_form.addRow("每格细分", self.grid_subdivisions)
        self.wheel_zoom = QComboBox()
        for label, value in (
            ("仅滚轮", "none"),
            ("Ctrl + 滚轮", "ctrl"),
            ("Alt + 滚轮", "alt"),
            ("Shift + 滚轮", "shift"),
            ("禁用滚轮缩放", "disabled"),
        ):
            self.wheel_zoom.addItem(label, value)
        wheel_index = self.wheel_zoom.findData(str(preferences["canvas/wheelZoomModifier"]))
        self.wheel_zoom.setCurrentIndex(wheel_index if wheel_index >= 0 else 0)
        general_form.addRow("滚轮缩放方式", self.wheel_zoom)
        self.canvas_width = QSpinBox()
        self.canvas_width.setRange(1, 100_000)
        self.canvas_width.setSuffix(" px")
        self.canvas_width.setValue(int(preferences["canvas/defaultWidth"]))
        general_form.addRow("新建画布默认宽度", self.canvas_width)
        self.canvas_height = QSpinBox()
        self.canvas_height.setRange(1, 100_000)
        self.canvas_height.setSuffix(" px")
        self.canvas_height.setValue(int(preferences["canvas/defaultHeight"]))
        general_form.addRow("新建画布默认高度", self.canvas_height)
        color_row = QWidget(general_tab)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.pasteboard_color = str(preferences["canvas/pasteboardColor"])
        self.pasteboard_color_button = QPushButton(self.pasteboard_color, color_row)
        self._update_color_button()
        self.pasteboard_color_button.clicked.connect(self._choose_pasteboard_color)
        color_layout.addWidget(self.pasteboard_color_button)
        general_form.addRow("画布外围颜色", color_row)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.jpeg_quality.setSuffix(" %")
        self.jpeg_quality.setValue(int(preferences["export/jpegQuality"]))
        general_form.addRow("JPEG 导出质量", self.jpeg_quality)
        recovery_row = QWidget(general_tab)
        recovery_layout = QHBoxLayout(recovery_row)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        self.recovery_dir = QLineEdit(str(preferences["recovery/directory"]))
        self.recovery_dir.setPlaceholderText("留空 = 系统用户数据目录")
        recovery_browse = QPushButton("浏览…")
        recovery_browse.clicked.connect(self._choose_recovery_dir)
        recovery_layout.addWidget(self.recovery_dir)
        recovery_layout.addWidget(recovery_browse)
        general_form.addRow("自动保存文件夹", recovery_row)
        icc_row = QWidget(general_tab)
        icc_layout = QHBoxLayout(icc_row)
        icc_layout.setContentsMargins(0, 0, 0, 0)
        self.icc_profile = QLineEdit(str(preferences["export/iccProfile"]))
        self.icc_profile.setPlaceholderText("可选：导出时嵌入的 ICC 颜色配置文件")
        icc_browse = QPushButton("浏览…")
        icc_browse.clicked.connect(self._choose_icc_profile)
        icc_layout.addWidget(self.icc_profile)
        icc_layout.addWidget(icc_browse)
        general_form.addRow("ICC 颜色配置文件", icc_row)
        tabs.addTab(general_tab, "常规")

        shortcuts_tab = QWidget(tabs)
        shortcuts_layout = QVBoxLayout(shortcuts_tab)
        shortcut_scroll = QScrollArea(shortcuts_tab)
        shortcut_scroll.setWidgetResizable(True)
        shortcut_content = QWidget(shortcut_scroll)
        shortcut_form = QFormLayout(shortcut_content)
        for shortcut_id, (label, action, _default) in shortcuts.items():
            editor = QKeySequenceEdit(action.shortcut(), shortcut_content)
            editor.setClearButtonEnabled(True)
            self._shortcut_edits[shortcut_id] = editor
            shortcut_form.addRow(label, editor)
        shortcut_scroll.setWidget(shortcut_content)
        shortcuts_layout.addWidget(shortcut_scroll, 1)
        reset_button = QPushButton("恢复默认快捷键", shortcuts_tab)
        reset_button.clicked.connect(self._reset_shortcuts)
        shortcuts_layout.addWidget(reset_button)
        tabs.addTab(shortcuts_tab, "快捷键")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def preference_values(self) -> dict[str, bool | int | str]:
        return {
            "canvas/gridVisible": self.grid_visible.isChecked(),
            "canvas/snapping": self.snapping_enabled.isChecked(),
            "canvas/gridSnapping": self.grid_snapping_enabled.isChecked(),
            "inspector/guidesVisible": self.guides_visible.isChecked(),
            "canvas/gridSize": self.grid_size.value(),
            "canvas/gridSubdivisions": self.grid_subdivisions.value(),
            "canvas/wheelZoomModifier": self.wheel_zoom.currentData(),
            "canvas/printGuidesVisible": self.print_guides.isChecked(),
            "canvas/bleedMargin": self.bleed_margin.value(),
            "canvas/safeMargin": self.safe_margin.value(),
            "canvas/defaultWidth": self.canvas_width.value(),
            "canvas/defaultHeight": self.canvas_height.value(),
            "canvas/pasteboardColor": self.pasteboard_color,
            "export/jpegQuality": self.jpeg_quality.value(),
            "recovery/directory": self.recovery_dir.text().strip(),
            "export/iccProfile": self.icc_profile.text().strip(),
        }

    def shortcut_sequences(self) -> dict[str, QKeySequence]:
        return {
            shortcut_id: editor.keySequence()
            for shortcut_id, editor in self._shortcut_edits.items()
        }

    def accept(self) -> None:
        width = self.canvas_width.value()
        height = self.canvas_height.value()
        if width * height > MAX_CANVAS_PIXELS:
            QMessageBox.warning(
                self,
                "默认画布尺寸过大",
                "默认画布最多支持 1 亿像素，请减小宽度或高度。",
            )
            return
        owners: dict[str, str] = {}
        for shortcut_id, sequence in self.shortcut_sequences().items():
            text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            if not text:
                continue
            normalized = text.casefold()
            label = self.shortcuts[shortcut_id][0]
            if normalized in owners:
                QMessageBox.warning(
                    self,
                    "快捷键冲突",
                    f"“{label}”与“{owners[normalized]}”使用了相同快捷键 {text}。",
                )
                return
            owners[normalized] = label
        super().accept()

    def _reset_shortcuts(self) -> None:
        for shortcut_id, (_label, _action, default) in self.shortcuts.items():
            self._shortcut_edits[shortcut_id].setKeySequence(default)

    def _choose_pasteboard_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self.pasteboard_color), self, "选择画布外围背景颜色"
        )
        if not color.isValid():
            return
        self.pasteboard_color = color.name()
        self._update_color_button()

    def _choose_recovery_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "选择自动保存文件夹", self.recovery_dir.text()
        )
        if chosen:
            self.recovery_dir.setText(chosen)

    def _choose_icc_profile(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ICC 颜色配置文件",
            self.icc_profile.text(),
            "ICC 配置 (*.icc *.icm);;所有文件 (*)",
        )
        if chosen:
            self.icc_profile.setText(chosen)

    def _update_color_button(self) -> None:
        self.pasteboard_color_button.setText(self.pasteboard_color)
        self.pasteboard_color_button.setStyleSheet(
            f"background-color: {self.pasteboard_color};"
        )


class TextElementDialog(QDialog):
    def __init__(self, parent: QWidget, existing: DesignElement | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文字图层")
        layout = QFormLayout(self)
        self.text_edit = QPlainTextEdit(existing.text if existing else "")
        self.text_edit.setPlaceholderText("输入封面文字，可使用日文和多行文本")
        self.font_combo = QFontComboBox()
        self.font_size = QSpinBox()
        self.font_size.setRange(1, 512)
        self.font_size.setValue(existing.font_size if existing else 56)
        self.color = QLineEdit(existing.color if existing else "#ffffff")
        self.outline_color = QLineEdit(
            existing.outline_color if existing else "#161923"
        )
        self.outline_width = QSpinBox()
        self.outline_width.setRange(0, 64)
        self.outline_width.setValue(existing.outline_width if existing else 2)
        self.vertical = QCheckBox("逐字竖排")
        self.vertical.setChecked(existing.vertical if existing else False)
        if existing:
            self.font_combo.setCurrentFont(QFont(existing.font_family))
        layout.addRow("内容", self.text_edit)
        layout.addRow("字体（Windows 已安装字体）", self.font_combo)
        layout.addRow("字号（px）", self.font_size)
        layout.addRow("填充颜色（#RRGGBB）", self.color)
        layout.addRow("描边颜色（#RRGGBB）", self.outline_color)
        layout.addRow("描边宽度（px）", self.outline_width)
        layout.addRow("", self.vertical)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str, int, str, str, int, bool]:
        return (
            self.text_edit.toPlainText(),
            self.font_combo.currentFont().family(),
            self.font_size.value(),
            self.color.text().strip(),
            self.outline_color.text().strip(),
            self.outline_width.value(),
            self.vertical.isChecked(),
        )


