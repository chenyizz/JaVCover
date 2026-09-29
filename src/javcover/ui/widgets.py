"""Small reusable Qt widgets/effects for the main window."""
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
from javcover.resources import ICON_DIR


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
            icon_path = ICON_DIR / name
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


