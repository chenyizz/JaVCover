"""A tab page hosting an :class:`ImageEditor` with a compact control bar.

Used as a non-modal alternative to the old modal editor: it lives in the main
window's central tab widget next to the cover canvas.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from javcover.ui.canvas.image_editor import ImageEditor
from javcover.ui.widgets.scrub import ScrubSpinBox


class EditorTab(QWidget):
    applied = Signal()
    cancelled = Signal()

    def __init__(
        self,
        image: QImage,
        frame: QSize,
        fit: str,
        offset: tuple[int, int],
        *,
        allow_pan: bool,
        allow_crop: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("模式"))
        self.mode = QComboBox()
        if allow_pan:
            self.mode.addItem("平移图片", "pan")
        if allow_crop:
            self.mode.addItem("裁剪", "crop")
        controls.addWidget(self.mode)
        controls.addWidget(QLabel("网格"))
        self.grid = ScrubSpinBox()
        self.grid.setRange(1, 5000)
        self.grid.setValue(50)
        self.grid.setSuffix(" px")
        controls.addWidget(self.grid)
        self.snap = QCheckBox("吸附网格/边缘")
        self.snap.setChecked(True)
        controls.addWidget(self.snap)
        controls.addStretch(1)
        controls.addWidget(QLabel("缩放"))
        self.zoom_label = QLabel("100%")
        controls.addWidget(self.zoom_label)
        fit_button = QPushButton("适应")
        fit_button.clicked.connect(lambda: self.editor.set_zoom(1.0))
        controls.addWidget(fit_button)
        layout.addLayout(controls)

        self.editor = ImageEditor(
            image, frame, fit, offset,
            allow_pan=allow_pan, allow_crop=allow_crop, parent=self,
        )
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.applied)
        buttons.rejected.connect(self.cancelled)
        layout.addWidget(buttons)

        self.mode.currentIndexChanged.connect(
            lambda _i: self.editor.set_mode(str(self.mode.currentData()))
        )
        self.grid.valueChanged.connect(self._grid_changed)
        self.snap.toggled.connect(self.set_snapping)
        self.editor.zoomChanged.connect(
            lambda zoom: self.zoom_label.setText(f"{round(zoom * 100)}%")
        )
        self.editor.set_mode(str(self.mode.currentData()))

    def _grid_changed(self, value: int) -> None:
        self.editor.grid_step = value
        self.editor.update()

    def set_snapping(self, enabled: bool) -> None:
        self.editor.snap_enabled = enabled

    def offset(self) -> tuple[int, int]:
        return self.editor.result_offset()

    def result(self):
        return self.editor.crop_result()
