"""Feature mixin: GuidePanelMixin.

The panel always drives the *active* guide source through a shared
:class:`GuideInteraction`: the cover canvas when the cover tab is active, or the
current image-editor tab when an editor tab is active.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPushButton
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

    def _active_guide_interaction(self):
        editor = getattr(self, "_active_editor_tab", None)
        if editor is not None:
            return editor.editor.guide_interaction
        return self.view.guide_interaction

    def _refresh_guide_list(self) -> None:
        interaction = self._active_guide_interaction()
        guides = interaction.host.guide_list()
        selected = self.guide_list.currentRow()
        self.guide_list.blockSignals(True)
        self.guide_list.clear()
        for guide in guides:
            axis = "垂直" if guide.axis == "x" else "水平"
            label = f"{guide.name} · " if guide.name else ""
            self.guide_list.addItem(f"{label}{axis} · {guide.position} px")
        if guides:
            self.guide_list.setCurrentRow(min(max(selected, 0), len(guides) - 1))
        self.guide_list.blockSignals(False)
        self._guide_selected(self.guide_list.currentRow())

    def add_guide(self, axis: Literal["x", "y"]) -> None:
        interaction = self._active_guide_interaction()
        limit = interaction.host.guide_limit(axis)
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
        interaction = self._active_guide_interaction()
        interaction.add(axis, position)
        self.guide_list.setCurrentRow(len(interaction.host.guide_list()) - 1)

    def _guide_selected(self, row: int) -> None:
        interaction = self._active_guide_interaction()
        guides = interaction.host.guide_list()
        enabled = 0 <= row < len(guides)
        self.guide_position.setEnabled(enabled)
        self.guide_name.setEnabled(enabled)
        if enabled:
            guide = guides[row]
            self.guide_position.setMaximum(interaction.host.guide_limit(guide.axis))
            self.guide_position.setValue(guide.position)
            self.guide_name.setText(guide.name)
        else:
            self.guide_position.setValue(0)
            self.guide_name.clear()

    def _rename_guide(self) -> None:
        row = self.guide_list.currentRow()
        self._active_guide_interaction().rename(row, self.guide_name.text().strip())

    def _move_guide(self) -> None:
        row = self.guide_list.currentRow()
        self._active_guide_interaction().move_to(row, self.guide_position.value())

    def remove_guide(self) -> None:
        row = self.guide_list.currentRow()
        self._active_guide_interaction().remove(row)
