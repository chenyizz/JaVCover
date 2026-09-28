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


_BLEND_MODE_LABELS = {
    "normal": "正常",
    "multiply": "正片叠底",
    "screen": "滤色",
    "overlay": "叠加",
    "darken": "变暗",
    "lighten": "变亮",
    "add": "线性减淡",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".psd"}


def format_output_name(pattern: str, stem: str, index: int, date_token: str) -> str:
    """Expand batch-export filename placeholders: {name}, {index}, {date}."""
    return (
        pattern.replace("{name}", stem)
        .replace("{index}", f"{index:03d}")
        .replace("{date}", date_token)
    )


class _ToolButtonFeedback(QObject):
    def __init__(self, button: QToolButton) -> None:
        super().__init__(button)
        self.button = button
        self.shadow = QGraphicsDropShadowEffect(button)
        self.shadow.setBlurRadius(0)
        self.shadow.setOffset(0, 0)
        self.shadow.setColor(QColor(20, 28, 36, 95))
        button.setGraphicsEffect(self.shadow)
        self._blur_animation = QPropertyAnimation(self.shadow, b"blurRadius", self)
        self._blur_animation.setDuration(160)
        self._offset_animation = QPropertyAnimation(self.shadow, b"yOffset", self)
        self._offset_animation.setDuration(160)
        button.toggled.connect(lambda _checked: self._animate_state())
        button.installEventFilter(self)
        self._animate_state()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.button and event.type() in (
            QEvent.Type.Enter,
            QEvent.Type.Leave,
        ):
            self._animate_state()
        return False

    def _animate_state(self) -> None:
        selected = self.button.isChecked()
        hovered = self.button.underMouse()
        self._blur_animation.stop()
        self._offset_animation.stop()
        self._blur_animation.setStartValue(self.shadow.blurRadius())
        self._blur_animation.setEndValue(12.0 if selected else (5.0 if hovered else 0.0))
        self._offset_animation.setStartValue(self.shadow.yOffset())
        self._offset_animation.setEndValue(3.0 if selected else 0.0)
        self._blur_animation.start()
        self._offset_animation.start()


class _WindowControlButton(QToolButton):
    def __init__(
        self, control: str, accessible_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.control = control
        self._maximized = False
        self._fullscreen = False
        self._hovered = False
        self._icons: dict[str, QIcon] = {}
        self.setObjectName("windowControl")
        self.setAccessibleName(accessible_name)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(46, 36)
        self.setIconSize(QSize(16, 16))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.installEventFilter(self)
        self._refresh_icon()

    def set_maximized(self, maximized: bool) -> None:
        if self._maximized != maximized:
            self._maximized = maximized
            self._refresh_icon()

    def set_fullscreen(self, fullscreen: bool) -> None:
        if self._fullscreen != fullscreen:
            self._fullscreen = fullscreen
            self._refresh_icon()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self and event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            hovered = event.type() == QEvent.Type.Enter
            if self._hovered != hovered:
                self._hovered = hovered
                self._refresh_icon()
        return super().eventFilter(watched, event)

    def _refresh_icon(self) -> None:
        if self.control == "minimize":
            name = "window-minimize.svg"
        elif self.control == "maximize":
            name = "window-restore.svg" if self._maximized else "window-maximize.svg"
        elif self.control == "fullscreen":
            name = (
                "window-fullscreen-exit.svg"
                if self._fullscreen
                else "window-fullscreen.svg"
            )
        else:
            name = "window-close-hover.svg" if self._hovered else "window-close.svg"

        icon = self._icons.get(name)
        if icon is None:
            icon_path = Path(__file__).resolve().parent / "icons" / name
            if not icon_path.is_file():
                raise FileNotFoundError(f"Window control icon not found: {icon_path}")
            icon = QIcon(str(icon_path))
            if icon.isNull():
                raise RuntimeError(f"Unable to load window control icon: {icon_path}")
            self._icons[name] = icon
        self.setIcon(icon)


class _DelayedToolTip(QObject):
    def __init__(self, widget: QWidget, text: str) -> None:
        super().__init__(widget)
        self.widget = widget
        self.text = text
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self._show)
        widget.setToolTip("")
        widget.installEventFilter(self)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.widget:
            if event.type() == QEvent.Type.Enter:
                self.timer.start()
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
                self.timer.stop()
                QToolTip.hideText()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return False

    def _show(self) -> None:
        if self.widget.underMouse():
            QToolTip.showText(QCursor.pos(), self.text, self.widget)


class _BackgroundWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, work: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as error:  # noqa: BLE001 - re-raised in the UI thread
            self.failed.emit(error)
            return
        self.succeeded.emit(result)


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

    def wheelEvent(self, event: object) -> None:
        if event.angleDelta().y() > 0:
            factor = 1.15
        else:
            factor = 1 / 1.15
        current = self.transform().m11()
        if 0.04 <= current * factor <= 24:
            self.scale(factor, factor)
            self.viewportChanged.emit()

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
            QDockWidget::title { background: #eef1f4; padding: 5px 8px; }
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
            QSplitter::handle { background: #f4f6f8; }
            QSplitter::handle:vertical { height: 7px; }
            QSplitter::handle:horizontal { width: 7px; }
            QToolButton#windowControl { background: transparent; border: none; border-radius: 5px; }
            QToolButton#windowControl:hover { background: #edf0f2; }
            QToolButton#windowClose { background: transparent; border: none; border-radius: 5px; }
            QToolButton#windowClose:hover { background: #d94c4c; }
            QWidget#regionListRow[active="true"] { background: #edf3f7; }
            QToolButton#regionRowAction { background: transparent; border: none; border-radius: 4px; padding: 2px; }
            QToolButton#regionRowAction:hover { background: #edf0f2; }
            QStatusBar { background: #ffffff; border: none; padding: 3px 6px; border-bottom-left-radius: 5px; border-bottom-right-radius: 5px; }
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
            QIcon(str(Path(__file__).resolve().parent / "icons" / "app-icon.svg"))
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
        icon = QIcon(str(Path(__file__).resolve().parent / "icons" / "app-icon.svg"))
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
        self.grid_size = QSpinBox()
        self.grid_size.setRange(1, 1000)
        self.grid_size.setSingleStep(1)
        self.grid_size.setValue(self._setting_int("canvas/gridSize", 100, 1, 1000))
        self.grid_size.setSuffix(" px")
        self.grid_size.setToolTip("主网格间距（像素）")
        self.grid_size.setObjectName("gridSizeSpinBox")
        self.grid_size.valueChanged.connect(self._refresh_grid)
        toolbar.addWidget(self.grid_size)
        self.grid_subdivisions = QSpinBox()
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
        self._set_grid_visibility(self.grid_checkbox.isChecked())

    def _create_tool_rail(self) -> None:
        toolbar = QToolBar("画布工具")
        toolbar.setObjectName("canvasToolRail")
        toolbar.setOrientation(Qt.Orientation.Vertical)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)
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
        draw_enabled = self._setting_bool("canvas/drawMode", True)
        self.view.draw_mode = draw_enabled
        select_action.setChecked(not draw_enabled)
        region_action.setChecked(draw_enabled)
        group = QActionGroup(self)
        group.setExclusive(True)
        group.addAction(select_action)
        group.addAction(region_action)
        region_action.toggled.connect(
            lambda checked: checked and self._set_draw_mode(True)
        )
        select_action.toggled.connect(
            lambda checked: checked and self._set_draw_mode(False)
        )
        for action in (select_action, region_action):
            toolbar.addAction(action)
            self._set_delayed_tooltip(toolbar, action)
        toolbar.addSeparator()
        for text, icon_name, tooltip, callback, shortcut_id, shortcut in (
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
        ):
            action = self._tool_action(
                text, icon_name, tooltip, callback, shortcut_id, shortcut
            )
            toolbar.addAction(action)
            self._set_delayed_tooltip(toolbar, action)
        self._tool_actions = (select_action, region_action)

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

    def _save_user_interface_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.setValue("canvas/drawMode", self.view.draw_mode)
        self.settings.setValue("canvas/snapping", self.snap_checkbox.isChecked())
        self.settings.setValue("canvas/gridVisible", self.grid_checkbox.isChecked())
        self.settings.setValue("canvas/gridSnapping", self.grid_snap_checkbox.isChecked())
        self.settings.setValue("canvas/gridSize", self.grid_size.value())
        self.settings.setValue("canvas/gridSubdivisions", self.grid_subdivisions.value())
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
        icon_path = Path(__file__).resolve().parent / "icons" / icon_name
        action = QAction(QIcon(str(icon_path)), text, self)
        action.setToolTip("")
        action.setData(tooltip)
        action.triggered.connect(callback)
        action.setShortcut(shortcut)
        self._register_shortcut(action, shortcut_id, shortcut)
        return action

    def _set_delayed_tooltip(
        self, toolbar: QToolBar, action: QAction
    ) -> None:
        button = toolbar.widgetForAction(action)
        if not isinstance(button, QToolButton):
            return
        button.setFixedSize(34, 34)
        button.setIconSize(QSize(18, 18))
        button.setAccessibleName(action.text())
        button.setProperty("javcoverAnimated", True)
        _ToolButtonFeedback(button)
        _DelayedToolTip(button, str(action.data() or ""))

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
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setMinimumWidth(250)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
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
            spin = QSpinBox()
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
        self.region_opacity = QSpinBox()
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
        self.guide_position = QSpinBox()
        self.guide_position.setRange(0, 100_000)
        self.guide_position.setSuffix(" px")
        self.guide_position.editingFinished.connect(self._move_guide)
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
            spin = QSpinBox()
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
        self.element_opacity = QSpinBox()
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
        self._update_region_controls(selected)

    def _region_row_button(self, icon_name: str, tooltip: str) -> QToolButton:
        return self._list_row_button(self.region_list, icon_name, tooltip)

    def _list_row_button(
        self, parent: QWidget, icon_name: str, tooltip: str
    ) -> QToolButton:
        icon_path = Path(__file__).resolve().parent / "icons" / icon_name
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
            self.guide_list.addItem(f"{axis} · {guide.position} px")
        if self.project.guides:
            self.guide_list.setCurrentRow(min(max(selected, 0), len(self.project.guides) - 1))
        self.guide_list.blockSignals(False)
        self._guide_selected(self.guide_list.currentRow())

    def _refresh_element_list(self) -> None:
        selected_id = self.view.selected_element_id
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
        dialog.resize(480, 440)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "素材仅保存在本机；放入画布后会嵌入当前 .javcover 项目。"
            "PSD 标题素材会保留来源，可在 Photoshop 修改后刷新。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        listing = QListWidget()
        listing.setIconSize(QSize(52, 52))
        layout.addWidget(listing, 1)

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
            for path in sorted(self.asset_directory.iterdir()):
                if path.suffix.lower() not in (
                    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".psd"
                ):
                    continue
                image = thumbnail(path)
                item = (
                    QListWidgetItem(QIcon(QPixmap.fromImage(image)), path.stem)
                    if image is not None
                    else QListWidgetItem(path.stem)
                )
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                listing.addItem(item)

        def import_assets() -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                dialog,
                "导入素材",
                "",
                "图片与 PSD (*.png *.jpg *.jpeg *.webp *.bmp *.psd);;所有文件 (*)",
            )
            for source in paths:
                src = Path(source)
                destination = self.asset_directory / f"{uuid4().hex}_{src.name}"
                try:
                    self._load_asset_image(src)
                    shutil.copy2(src, destination)
                except (ImageError, PsdImportError, OSError) as error:
                    self._error("素材导入失败", f"{src.name}：{error}")
            refresh()

        def place_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            dialog.accept()
            self._place_asset(Path(item.data(Qt.ItemDataRole.UserRole)))

        def delete_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            confirmed = QMessageBox.question(
                dialog,
                "删除素材",
                f"从本机素材库删除“{path.name}”？\n已放入画布的图层不受影响。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
            try:
                path.unlink()
            except OSError as error:
                self._error("删除素材失败", str(error))
            refresh()

        buttons = QHBoxLayout()
        add_button = QPushButton("导入素材…")
        add_button.clicked.connect(import_assets)
        delete_button = QPushButton("删除素材")
        delete_button.clicked.connect(delete_selected)
        place_button = QPushButton("放入画布")
        place_button.clicked.connect(place_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        buttons.addWidget(place_button)
        layout.addLayout(buttons)
        listing.itemDoubleClicked.connect(lambda _item: place_selected())
        refresh()
        dialog.exec()

    def _link_asset(self, element: DesignElement, path: Path) -> None:
        if path.parent != self.asset_directory:
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
                name=path.stem,
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
                name=path.stem,
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

    def run_color_block_assist(self) -> None:
        if not self.project.base_png:
            self._error("需要底图", "请先导入封面图片，再分析大色块。")
            return
        try:
            candidates = suggest_color_blocks(decode_png(self.project.base_png))
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
        if not self.project.base_png:
            self._error("需要底图", "请先导入封面图片，再运行日文 OCR。")
            return
        base_png = self.project.base_png
        executable = str(self.settings.value("ocr/tesseractPath", "") or "") or None
        tessdata_dir = str(self.settings.value("ocr/tessdataPath", "") or "") or None

        def work() -> list[tuple[Rect, str]]:
            return recognize_japanese_text(
                decode_png(base_png),
                executable=executable,
                tessdata_dir=tessdata_dir,
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
        if enabled:
            guide = self.project.guides[row]
            self.guide_position.setMaximum(self.project.width if guide.axis == "x" else self.project.height)
            self.guide_position.setValue(guide.position)
        else:
            self.guide_position.setValue(0)

    def _move_guide(self) -> None:
        row = self.guide_list.currentRow()
        if not 0 <= row < len(self.project.guides):
            return
        old = self.project.guides[row]
        position = self.guide_position.value()
        if position == old.position:
            return
        self._begin_edit()
        self.project.guides[row] = Guide(old.axis, position)
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
        width, accepted = QInputDialog.getInt(
            self,
            "新建画布",
            "宽度（px）",
            self._setting_int("canvas/defaultWidth", 1200, 1, 100_000),
            1,
            100_000,
        )
        if not accepted:
            return
        height, accepted = QInputDialog.getInt(
            self,
            "新建画布",
            "高度（px）",
            self._setting_int("canvas/defaultHeight", 800, 1, 100_000),
            1,
            100_000,
        )
        if not accepted:
            return
        if width * height > MAX_CANVAS_PIXELS:
            self._error("画布尺寸过大", "画布最多支持 1 亿像素，请减小宽度或高度。")
            return
        self._replace_project(Project(width, height), None)

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

        def work() -> Project:
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
        if not asset_name:
            return None
        candidate = self.asset_directory / asset_name
        return candidate if candidate.is_file() else None

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

        def work() -> Path:
            return self._render_export(project, destination, image_format, quality)

        def on_success(saved: Path) -> None:
            self.settings.setValue("export/lastDir", str(saved.parent))
            self.settings.sync()
            self.status.setText(f"已导出：{saved}")

        def on_error(error: object) -> None:
            self._error("导出失败", str(error))

        self._run_background("正在导出封面…", work, on_success, on_error)

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

        def work() -> tuple[list[Path], list[tuple[str, str]], int]:
            outputs: list[Path] = []
            failures: list[tuple[str, str]] = []
            partial = 0
            for index, stem in enumerate(stems, start=1):
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

    def _set_draw_mode(self, enabled: bool) -> None:
        self.view.draw_mode = enabled

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
    ) -> None:
        if self._background_worker is not None and self._background_worker.isRunning():
            self._error("操作进行中", "请等待当前操作完成后再试。")
            return
        dialog = QProgressDialog(label, "", 0, 0, self)
        dialog.setWindowTitle("JAVCover")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
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

        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_failure)
        dialog.show()
        worker.start()

    def _update_title(self) -> None:
        self.setWindowTitle("JAVCover *" if self.dirty else "JAVCover")

    def _error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("JAVCover")
    app.setOrganizationName("JAVCover")
    translator = QTranslator(app)
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
