"""Text design-element editor dialog."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFontComboBox, QFormLayout, QLineEdit, QPlainTextEdit, QWidget
from javcover.core.models import DesignElement
from javcover.ui.widgets.scrub import ScrubSpinBox



class TextElementDialog(QDialog):
    def __init__(self, parent: QWidget, existing: DesignElement | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文字图层")
        layout = QFormLayout(self)
        self.text_edit = QPlainTextEdit(existing.text if existing else "")
        self.text_edit.setPlaceholderText("输入封面文字，可使用日文和多行文本")
        self.font_combo = QFontComboBox()
        self.font_size = ScrubSpinBox()
        self.font_size.setRange(1, 512)
        self.font_size.setValue(existing.font_size if existing else 56)
        self.color = QLineEdit(existing.color if existing else "#ffffff")
        self.outline_color = QLineEdit(
            existing.outline_color if existing else "#161923"
        )
        self.outline_width = ScrubSpinBox()
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
