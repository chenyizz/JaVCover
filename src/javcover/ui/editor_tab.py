"""A tab page hosting an :class:`ImageEditor` with a compact control bar.

Used as a non-modal alternative to the old modal editor: it lives in the main
window's central tab widget next to the cover canvas. Rulers, guides and the
coordinate readout come from the shared canvas widgets so the editor behaves
like the main canvas.
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

from javcover.services.canvas_widgets import RulerFrame
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
        clear_guides = QPushButton("清除参考线")
        controls.addWidget(clear_guides)
        controls.addStretch(1)
        controls.addWidget(QLabel("缩放"))
        self.zoom_label = QLabel("100%")
        controls.addWidget(self.zoom_label)
        fit_button = QPushButton("适应")
        controls.addWidget(fit_button)
        layout.addLayout(controls)

        self.editor = ImageEditor(
            image, frame, fit, offset,
            allow_pan=allow_pan, allow_crop=allow_crop, parent=self,
        )
        self.ruler_frame = RulerFrame(self.editor)
        layout.addWidget(self.ruler_frame, 1)

        status = QHBoxLayout()
        self.crop_label = QLabel("选区 —")
        self.cursor_label = QLabel("—")
        status.addWidget(self.crop_label)
        status.addStretch(1)
        status.addWidget(self.cursor_label)
        layout.addLayout(status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.applied)
        buttons.rejected.connect(self.cancelled)
        layout.addWidget(buttons)

        fit_button.clicked.connect(lambda: self.editor.set_zoom(1.0))
        clear_guides.clicked.connect(self.editor.clear_guides)
        self.mode.currentIndexChanged.connect(
            lambda _i: self.editor.set_mode(str(self.mode.currentData()))
        )
        self.grid.valueChanged.connect(self._grid_changed)
        self.snap.toggled.connect(self.set_snapping)
        self.editor.zoomChanged.connect(
            lambda zoom: self.zoom_label.setText(f"{round(zoom * 100)}%")
        )
        self.editor.pointerMoved.connect(self._pointer_moved)
        self.editor.changed.connect(self._update_crop_label)
        self.ruler_frame.guideRequested.connect(self.editor.guide_interaction.add)
        self.ruler_frame.guidePreviewChanged.connect(
            self.editor.guide_interaction.set_preview
        )
        self.editor.set_mode(str(self.mode.currentData()))
        self._update_crop_label()

    def _grid_changed(self, value: int) -> None:
        self.editor.grid_step = value
        self.editor.viewport().update()

    def _pointer_moved(self, x: int, y: int) -> None:
        self.cursor_label.setText(f"{x}, {y} px")

    def _update_crop_label(self) -> None:
        rect = self.editor.crop_rect()
        self.crop_label.setText(
            f"选区 {round(rect.width())} × {round(rect.height())} px"
        )

    def set_snapping(self, enabled: bool) -> None:
        self.editor.snap_enabled = enabled

    def offset(self) -> tuple[int, int]:
        return self.editor.result_offset()

    def result(self):
        return self.editor.crop_result()
