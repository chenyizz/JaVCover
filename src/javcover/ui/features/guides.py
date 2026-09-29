"""Feature mixin: GuidePanelMixin."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPushButton
from javcover.core.models import Guide
from javcover.ui.widgets.scrub import ScrubSpinBox
from typing import Literal


class GuidePanelMixin:
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

