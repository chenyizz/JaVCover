"""New-canvas dialog with print/disc presets."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget
from javcover.ui.widgets.scrub import ScrubSpinBox

CANVAS_PRESETS: list[tuple[str, int, int, str]] = [
    ("电影 2K 横板", 2048, 1152, "rect"),
    ("电影 4K 横板", 3840, 2160, "rect"),
    ("海报 4K 竖版", 2160, 3840, "rect"),
    ("A4 300dpi 横版", 3508, 2480, "rect"),
    ("A4 300dpi 竖版", 2480, 3508, "rect"),
    ("大光盘盘面 (120mm)", 1417, 1417, "disc"),
    ("小光盘盘面 (80mm)", 945, 945, "disc"),
    ("光盘封面 (方形)", 1417, 1417, "rect"),
]


class NewCanvasDialog(QDialog):
    """Create a new canvas with regular-print or disc presets."""

    def __init__(
        self, parent: QWidget | None, default_width: int, default_height: int
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建画布")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.preset = QComboBox()
        self.preset.addItem("自定义", None)
        for name, width, height, shape in CANVAS_PRESETS:
            self.preset.addItem(name, (width, height, shape))
        form.addRow("预设", self.preset)

        self.shape = QComboBox()
        self.shape.addItem("矩形（海报/封面）", "rect")
        self.shape.addItem("圆形（光盘盘面）", "disc")
        form.addRow("画布形状", self.shape)

        self.width = ScrubSpinBox()
        self.width.setRange(1, 100_000)
        self.width.setSuffix(" px")
        self.width.setValue(max(1, default_width))
        form.addRow("宽度", self.width)

        self.height = ScrubSpinBox()
        self.height.setRange(1, 100_000)
        self.height.setSuffix(" px")
        self.height.setValue(max(1, default_height))
        form.addRow("高度", self.height)

        layout.addLayout(form)
        hint = QLabel("圆形画布用于光盘盘面；导出时圆外区域透明（JPEG 为白）。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.preset.currentIndexChanged.connect(self._preset_changed)

    def _preset_changed(self, _index: int) -> None:
        data = self.preset.currentData()
        if data is None:
            return
        width, height, shape = data
        self.width.setValue(width)
        self.height.setValue(height)
        index = self.shape.findData(shape)
        self.shape.setCurrentIndex(index if index >= 0 else 0)

    def values(self) -> tuple[int, int, str]:
        return self.width.value(), self.height.value(), str(self.shape.currentData())
